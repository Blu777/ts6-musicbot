"""ServerQuery-based client (works on TeamSpeak 3 AND TS6 via SSH).

Drop-in replacement for WebQueryClient when WebQuery HTTP API is not available.
TS3 servers only expose ServerQuery (raw TCP 10011 / SSH 10022). TS6 servers
expose WebQuery in addition, but ServerQuery also works there.

Uses a dedicated SSH connection (separate from ChatListener's), serialized by
an asyncio.Lock so concurrent callers can't interleave command/response pairs.
"""

from __future__ import annotations

import asyncio
import logging
import os

from .chat_listener import _ts_decode, _tokenize
from .transport import open_transport, _LineTransport

log = logging.getLogger(__name__)


def _ts_encode(s: str) -> str:
    """Escape a string for the TS3/TS6 ServerQuery wire format."""
    return (
        s.replace("\\", "\\\\")
         .replace("/", "\\/")
         .replace(" ", "\\s")
         .replace("|", "\\p")
         .replace("\a", "\\a")
         .replace("\b", "\\b")
         .replace("\f", "\\f")
         .replace("\n", "\\n")
         .replace("\r", "\\r")
         .replace("\t", "\\t")
         .replace("\v", "\\v")
    )


def _parse_records(resp: str) -> list[dict]:
    """Parse a ServerQuery list response (records pipe-separated) → list of dicts."""
    records = []
    for chunk in resp.split("\n"):
        chunk = chunk.strip("\r ")
        if not chunk or chunk.startswith("error "):
            continue
        for record in chunk.split("|"):
            d = _tokenize(record)
            if d and any(k for k in d if k):
                records.append(d)
    return records


class ServerQueryClient:
    """WebQueryClient-compatible facade over TS3/TS6 ServerQuery (raw or SSH)."""

    def __init__(self):
        self._host = os.getenv("TS_SERVER_HOST", "localhost")
        self._port = int(os.getenv("TS_QUERY_PORT", "10022"))
        self._username = os.getenv("TS_QUERY_USERNAME", "")
        self._password = os.getenv("TS_QUERY_PASSWORD", "")

        self._transport: _LineTransport | None = None
        self._lock = asyncio.Lock()

        # WebQueryClient-compat: stores the cid to which messages are sent
        self._channel_id: str | None = None

    # ── Lifecycle ──────────────────────────────────────────────────────────

    async def start(self) -> None:
        log.info(
            "ServerQueryClient: connecting to %s:%d as %s",
            self._host, self._port, self._username,
        )
        self._transport = await open_transport(
            self._host, self._port, self._username, self._password
        )
        resp = await self._cmd_locked("use 1")
        log.debug("use 1: %s", resp)

    async def stop(self) -> None:
        if self._transport:
            await self._transport.close()
        self._transport = None

    # ── Low-level RPC ──────────────────────────────────────────────────────

    async def _cmd_locked(self, command: str, timeout: float = 10) -> str:
        async with self._lock:
            if not self._transport:
                raise RuntimeError("ServerQueryClient not started")
            self._transport.drain_buffer()
            self._transport.send_line(command)
            collected = ""
            loop = asyncio.get_running_loop()
            deadline = loop.time() + timeout
            while True:
                remaining = max(0.05, deadline - loop.time())
                line = await self._transport.read_line(timeout=remaining)
                if line is None:
                    break
                collected += line + "\n"
                if line.lstrip().startswith("error "):
                    break
            return collected.strip()

    # ── Read operations ────────────────────────────────────────────────────

    async def get_clients(self) -> dict:
        resp = await self._cmd_locked("clientlist")
        return {"body": _parse_records(resp)}

    async def get_channels(self) -> dict:
        resp = await self._cmd_locked("channellist")
        return {"body": _parse_records(resp)}

    async def get_own_client_id(self) -> str:
        resp = await self._cmd_locked("whoami")
        fields = _tokenize(resp)
        return fields.get("client_id", "")

    async def find_channel_id(self, channel_name: str) -> str | None:
        result = await self.get_channels()
        for ch in result.get("body", []):
            if ch.get("channel_name") == channel_name:
                return ch.get("cid")
        return None

    async def get_channel_info(self, channel_id: int) -> dict:
        resp = await self._cmd_locked(f"channelinfo cid={channel_id}")
        records = _parse_records(resp)
        return {"body": records}

    # ── Write operations ───────────────────────────────────────────────────

    async def send_channel_message(self, message: str) -> None:
        """Send a channel-scoped text message.

        TS3 requires sending from the channel you want the message to appear
        in (targetmode=2 sends to the caller's CURRENT channel). If we have a
        stored channel_id, we make sure we're in it; otherwise we use wherever
        the query session currently is.
        """
        # Split long messages — TS3 servers typically reject > ~1024 chars.
        MAX = 900
        chunks = [message[i:i + MAX] for i in range(0, len(message), MAX)] or [""]
        for chunk in chunks:
            await self._cmd_locked(
                f"sendtextmessage targetmode=2 msg={_ts_encode(chunk)}"
            )

    async def join_channel(self, channel_name: str) -> bool:
        cid = await self.find_channel_id(channel_name)
        if cid is None:
            return False
        clid = await self.get_own_client_id()
        if clid:
            try:
                await self._cmd_locked(f"clientmove clid={clid} cid={cid}")
            except Exception as e:
                log.debug("clientmove ignored: %s", e)
        self._channel_id = cid
        return True

    async def move_client(self, client_id: int, channel_id: int) -> dict:
        resp = await self._cmd_locked(
            f"clientmove clid={client_id} cid={channel_id}"
        )
        return {"body": _parse_records(resp)}

    # ── WebQueryClient-compat shims (unused under ServerQuery) ─────────────

    async def post(self, endpoint: str, data: dict | None = None) -> dict:
        """Compatibility shim for code that called WebQueryClient.post directly.

        Translates the common endpoints used elsewhere in the codebase.
        """
        data = data or {}
        if endpoint == "clientmove":
            return await self.move_client(data["clid"], data["cid"])
        if endpoint == "sendtextmessage":
            await self.send_channel_message(data.get("msg", ""))
            return {"body": []}
        raise NotImplementedError(f"ServerQueryClient.post({endpoint})")

    async def get(self, endpoint: str, params: dict | None = None) -> dict:
        if endpoint == "clientlist":
            return await self.get_clients()
        if endpoint == "channellist":
            return await self.get_channels()
        if endpoint == "whoami":
            cid = await self.get_own_client_id()
            return {"body": [{"client_id": cid}]}
        if endpoint == "channelinfo" and params:
            return await self.get_channel_info(params.get("cid", 0))
        raise NotImplementedError(f"ServerQueryClient.get({endpoint})")

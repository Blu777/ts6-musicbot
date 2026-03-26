"""
Receives channel chat messages from TS6 via SSH ServerQuery (port 10012).

Connects with the dedicated query login (TS_QUERY_USERNAME / TS_QUERY_PASSWORD),
selects virtual server 1, moves into the target channel, and registers for
'textchannel' and 'textprivate' events.

TS6 event types for servernotifyregister:
  server | channel | textserver | textchannel | textprivate | bans

Notifications arrive as: notifytextmessage targetmode=2 msg=... invokername=...

Reconnects automatically on disconnect.
"""

import asyncio
import logging
import os
import re

import asyncssh

log = logging.getLogger(__name__)

_TS_UNESCAPE = {r'\s': ' ', r'\p': '|', r'\/': '/', r'\\': '\\'}


def _ts_decode(s: str) -> str:
    for k, v in _TS_UNESCAPE.items():
        s = s.replace(k, v)
    return s


_NOTIFY_RE = re.compile(
    r"notifytextmessage\b"
    r".*?\bmsg=(?P<msg>\S+)"
    r".*?\binvokername=(?P<sender>\S+)",
    re.IGNORECASE,
)


def _parse_notify(line: str) -> tuple[str, str] | None:
    """Parse a notifytextmessage line → (sender, message) or None."""
    m = _NOTIFY_RE.search(line)
    if not m:
        return None
    msg = _ts_decode(m.group("msg"))
    sender = _ts_decode(m.group("sender"))
    return (sender, msg) if sender and msg else None


class _TSQuerySession(asyncssh.SSHClientSession):
    """Event-based ServerQuery session — no Queue, avoids timeout accumulation."""

    def __init__(self):
        self._buf = ""
        self._ev = asyncio.Event()

    def data_received(self, data, datatype):
        self._buf += data
        self._ev.set()

    def connection_lost(self, exc):
        self._ev.set()

    async def cmd(self, chan, command: str, timeout: float = 5) -> str:
        """Send a command and return the full response (waits for 'msg=')."""
        self._ev.clear()
        chan.write(command + "\n")
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while True:
            if "msg=" in self._buf:
                out = self._buf
                self._buf = ""
                return out.strip()
            remaining = max(0.05, deadline - loop.time())
            self._ev.clear()
            try:
                await asyncio.wait_for(self._ev.wait(), timeout=remaining)
            except asyncio.TimeoutError:
                break
        out = self._buf
        self._buf = ""
        return out.strip()

    async def wait_for_notify(self, timeout: float = 30) -> str | None:
        """Wait for a 'notify*' push event from the server."""
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while True:
            lines = self._buf.split("\n")
            for i, line in enumerate(lines):
                stripped = line.strip("\r ")
                if stripped.startswith("notify"):
                    self._buf = "\n".join(lines[i + 1 :])
                    return stripped
            remaining = max(0.05, deadline - loop.time())
            self._ev.clear()
            try:
                await asyncio.wait_for(self._ev.wait(), timeout=remaining)
            except asyncio.TimeoutError:
                return None


class ChatListener:
    def __init__(self, client, on_message_callback, poll_interval: float = 1.5):
        self.client = client  # WebQueryClient — used to look up channel ID
        self.on_message = on_message_callback
        self._running = False

        self._host = os.getenv("TS_SERVER_HOST", "localhost")
        self._port = int(os.getenv("TS_QUERY_PORT", "10012"))
        self._username = os.getenv("TS_QUERY_USERNAME", "musicbot")
        self._password = os.getenv("TS_QUERY_PASSWORD", "")
        self._channel = os.getenv("TS_CHANNEL", "")

    async def start(self):
        self._running = True
        while self._running:
            try:
                await self._connect_and_listen()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.warning("ServerQuery connection lost: %s — reconnecting in 5s", e)
                await asyncio.sleep(5)

    async def stop(self):
        self._running = False

    async def _connect_and_listen(self):
        log.info(
            "Connecting to SSH ServerQuery at %s:%d as %s",
            self._host, self._port, self._username,
        )
        conn, _ = await asyncssh.create_connection(
            asyncssh.SSHClient,
            self._host,
            self._port,
            username=self._username,
            password=self._password,
            known_hosts=None,
        )
        async with conn:
            chan, session = await conn.create_session(_TSQuerySession)

            # Let banner arrive then discard it
            await asyncio.sleep(0.5)
            session._buf = ""

            resp = await session.cmd(chan, "use 1")
            log.debug("use 1: %s", resp)

            whoami = await session.cmd(chan, "whoami")
            log.debug("whoami: %s", whoami)
            clid = None
            for part in whoami.split():
                if part.startswith("client_id="):
                    clid = part.split("=", 1)[1]
                    break

            # Resolve channel ID via WebQueryClient (already cached after join_channel)
            cid = getattr(self.client, "_channel_id", None)
            if cid is None and self._channel:
                try:
                    cid = await self.client.find_channel_id(self._channel)
                except Exception:
                    pass

            if clid and cid:
                resp = await session.cmd(chan, f"clientmove clid={clid} cid={cid}")
                log.info("Moved to channel %s (cid=%s): %s", self._channel, cid, resp)
            else:
                log.warning("Could not move to channel (clid=%s cid=%s)", clid, cid)

            r1 = await session.cmd(chan, "servernotifyregister event=textchannel")
            log.info("Register textchannel: %s", r1)
            r2 = await session.cmd(chan, "servernotifyregister event=textprivate")
            log.info("Register textprivate: %s", r2)
            log.info("ChatListener ready — waiting for messages in %s...", self._channel)

            while self._running:
                notify = await session.wait_for_notify(timeout=30)
                if notify is None:
                    # keepalive
                    await session.cmd(chan, "version", timeout=5)
                    continue
                log.debug("Event: %s", notify)
                parsed = _parse_notify(notify)
                if parsed:
                    sender, text = parsed
                    log.debug("Chat from %s: %s", sender, text)
                    await self.on_message(sender, text)

            chan.close()

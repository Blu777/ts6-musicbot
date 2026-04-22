"""
Receives channel chat messages from TS6 via SSH ServerQuery (port 10012).

Connects with the dedicated query login (TS_QUERY_USERNAME / TS_QUERY_PASSWORD),
selects virtual server 1, moves into the target channel, and registers for
'textchannel' and 'textprivate' events.

Notifications arrive as: notifytextmessage targetmode=2 msg=... invokername=...

Reconnects automatically on disconnect.
"""

import asyncio
import logging
import os

import asyncssh

log = logging.getLogger(__name__)


# ── TS3/TS6 ServerQuery escape decoding ───────────────────────────────────────
# Ref: https://yat.qa/ressourcen/escape-sequences/
_TS_UNESCAPE = [
    (r"\\", "\\"),  # must come first to avoid double-unescape
    (r"\/", "/"),
    (r"\s", " "),
    (r"\p", "|"),
    (r"\a", "\x07"),
    (r"\b", "\b"),
    (r"\f", "\f"),
    (r"\n", "\n"),
    (r"\r", "\r"),
    (r"\t", "\t"),
    (r"\v", "\v"),
]


def _ts_decode(s: str) -> str:
    for k, v in _TS_UNESCAPE:
        s = s.replace(k, v)
    return s


def _tokenize(line: str) -> dict:
    """Parse a ServerQuery line (space-separated key=value tokens) into a dict.

    Order-independent; robust to extra fields. Values are TS-decoded.
    Tokens without '=' are stored under empty-string key as a list of flags.
    """
    out: dict = {}
    for tok in line.split(" "):
        tok = tok.strip()
        if not tok:
            continue
        if "=" in tok:
            k, _, v = tok.partition("=")
            out[k] = _ts_decode(v)
        else:
            out.setdefault("_verb", tok)
    return out


def _parse_notify(line: str) -> tuple[str, str] | None:
    """Parse a notifytextmessage line → (sender, message) or None.

    Accepts any order of fields, any extra fields. Returns None if it's not a
    textmessage or required fields are missing.
    """
    stripped = line.lstrip()
    # Accept both `notifytextmessage ...` and the chat_log style
    # `textmessage ...` that the client echoes to its log file.
    if not (stripped.startswith("notifytextmessage") or " textmessage " in stripped or stripped.startswith("textmessage")):
        return None
    fields = _tokenize(stripped)
    sender = fields.get("invokername")
    msg = fields.get("msg")
    if not sender or not msg:
        return None
    return sender, msg


# Backward-compat alias used by tests / downstream code
_parse_line = _parse_notify


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

        # Exposed for live channel moves
        self._chan = None       # asyncssh channel
        self._session = None    # _TSQuerySession
        self._clid = None       # SSH query client ID

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

    async def move_to_channel(self, channel_name: str) -> bool:
        """Move the SSH query session to a different channel at runtime.

        Also moves the TS6 desktop client (the audio source) via WebQuery
        and re-registers for text events in the new channel.
        """
        cid = await self.client.find_channel_id(channel_name)
        if cid is None:
            return False

        try:
            ts_clid = await self.client.get_own_client_id()
            await self.client.post("clientmove", {"clid": ts_clid, "cid": cid})
        except Exception as e:
            log.warning("Could not move TS6 client: %s", e)

        if self._chan and self._session and self._clid:
            resp = await self._session.cmd(
                self._chan, f"clientmove clid={self._clid} cid={cid}"
            )
            log.info("SSH query moved to %s (cid=%s): %s", channel_name, cid, resp)

            await self._session.cmd(self._chan, "servernotifyregister event=textchannel")
            await self._session.cmd(self._chan, "servernotifyregister event=textprivate")
            log.info("Re-registered text events in %s", channel_name)

        self._channel = channel_name
        self.client._channel_id = cid
        return True

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
            self._chan = chan
            self._session = session

            await asyncio.sleep(0.5)
            session._buf = ""

            resp = await session.cmd(chan, "use 1")
            log.debug("use 1: %s", resp)

            whoami = await session.cmd(chan, "whoami")
            log.debug("whoami: %s", whoami)
            self._clid = None
            for part in whoami.split():
                if part.startswith("client_id="):
                    self._clid = part.split("=", 1)[1]
                    break

            cid = getattr(self.client, "_channel_id", None)
            if cid is None and self._channel:
                try:
                    cid = await self.client.find_channel_id(self._channel)
                except Exception:
                    pass

            if self._clid and cid:
                resp = await session.cmd(chan, f"clientmove clid={self._clid} cid={cid}")
                log.info("Moved to channel %s (cid=%s): %s", self._channel, cid, resp)
            else:
                log.warning("Could not move to channel (clid=%s cid=%s)", self._clid, cid)

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

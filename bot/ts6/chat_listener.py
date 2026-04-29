"""
Receives channel chat messages from TS3/TS6 via ServerQuery.

Uses the `transport` module so it works with either raw TCP (port 10011) or
SSH (port 10022), auto-selected by the TS_QUERY_PORT env var.

Connects with the dedicated query login (TS_QUERY_USERNAME / TS_QUERY_PASSWORD),
selects virtual server 1, moves into the target channel, and registers for
'textchannel' and 'textprivate' events.

Notifications arrive as: notifytextmessage targetmode=2 msg=... invokername=...

Reconnects automatically on disconnect.
"""

import asyncio
import logging
import os

log = logging.getLogger(__name__)


# ── TS3/TS6 ServerQuery escape decoding ───────────────────────────────────────
# Ref: https://yat.qa/ressourcen/escape-sequences/
_TS_ESCAPE_MAP: dict[str, str] = {
    "\\": "\\",
    "/": "/",
    "s": " ",
    "p": "|",
    "a": "\x07",
    "b": "\b",
    "f": "\f",
    "n": "\n",
    "r": "\r",
    "t": "\t",
    "v": "\v",
}


def _ts_decode(s: str) -> str:
    out: list[str] = []
    i = 0
    while i < len(s):
        if s[i] == "\\" and i + 1 < len(s) and s[i + 1] in _TS_ESCAPE_MAP:
            out.append(_TS_ESCAPE_MAP[s[i + 1]])
            i += 2
        else:
            out.append(s[i])
            i += 1
    return "".join(out)


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


class ChatListener:
    def __init__(self, client, on_message_callback, poll_interval: float = 1.5):
        self.client = client  # WebQueryClient or ServerQueryClient — used to look up channel ID
        self.on_message = on_message_callback
        self._running = False

        self._host = os.getenv("TS_SERVER_HOST", "localhost")
        self._port = int(os.getenv("TS_QUERY_PORT", "10022"))
        self._username = os.getenv("TS_QUERY_USERNAME", "musicbot")
        self._password = os.getenv("TS_QUERY_PASSWORD", "")
        self._channel = os.getenv("TS_CHANNEL", "")

        # Exposed for live channel moves
        self._transport = None
        self._clid: str | None = None

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
        """Move the query session to a different channel at runtime.

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

        if self._transport and self._clid:
            resp = await self._cmd(f"clientmove clid={self._clid} cid={cid}")
            log.info("Query session moved to %s (cid=%s): %s", channel_name, cid, resp)

            await self._cmd("servernotifyregister event=textchannel")
            await self._cmd("servernotifyregister event=textprivate")
            log.info("Re-registered text events in %s", channel_name)

        self._channel = channel_name
        self.client._channel_id = cid
        return True

    async def _cmd(self, command: str, timeout: float = 5,
                   flood_retries: int = 3) -> str:
        """Send a command and collect response lines up to `error id=...`.

        Discards any notify* lines that arrive in the middle (they are handled
        by the main loop via `wait_for_notify`).

        On error id=524 (flood) automatically waits `extra_msg` seconds and
        retries up to `flood_retries` times.
        """
        assert self._transport is not None
        for attempt in range(flood_retries + 1):
            self._transport.send_line(command)
            collected = ""
            loop = asyncio.get_running_loop()
            deadline = loop.time() + timeout
            error_line = ""
            while True:
                remaining = max(0.05, deadline - loop.time())
                line = await self._transport.read_line(timeout=remaining)
                if line is None:
                    break
                if line.lstrip().startswith("notify"):
                    self._transport._feed(line + "\n")  # type: ignore[attr-defined]
                    continue
                collected += line + "\n"
                if line.lstrip().startswith("error "):
                    error_line = line
                    break
            if "error id=524" in error_line and attempt < flood_retries:
                # "please wait N seconds" — parse N, default 1
                wait_s = 1.0
                for tok in error_line.split():
                    if tok.startswith("extra_msg=please\\swait\\s"):
                        try:
                            wait_s = float(tok.split("\\s")[2])
                        except (ValueError, IndexError):
                            pass
                log.info("Flood protection hit, retrying in %.1fs", wait_s + 0.2)
                await asyncio.sleep(wait_s + 0.2)
                continue
            return collected.strip()
        return collected.strip()

    async def _wait_for_notify(self, timeout: float = 30) -> str | None:
        assert self._transport is not None
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while True:
            remaining = max(0.05, deadline - loop.time())
            line = await self._transport.read_line(timeout=remaining)
            if line is None:
                return None
            if line.lstrip().startswith("notify"):
                return line.strip()
            # Ignore stray lines (shouldn't happen outside of an active _cmd)

    async def _connect_and_listen(self):
        from .transport import open_transport
        log.info(
            "Connecting to ServerQuery at %s:%d as %s",
            self._host, self._port, self._username,
        )
        self._transport = await open_transport(
            self._host, self._port, self._username, self._password
        )
        try:
            resp = await self._cmd("use 1")
            log.debug("use 1: %s", resp)

            whoami = await self._cmd("whoami")
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
                resp = await self._cmd(f"clientmove clid={self._clid} cid={cid}")
                log.info("Moved to channel %s (cid=%s)", self._channel, cid)
            else:
                log.warning("Could not move to channel (clid=%s cid=%s)", self._clid, cid)

            r1 = await self._cmd("servernotifyregister event=textchannel")
            log.info("Register textchannel: %s", r1)
            r2 = await self._cmd("servernotifyregister event=textprivate")
            log.info("Register textprivate: %s", r2)
            log.info("ChatListener ready — waiting for messages in %s...", self._channel)

            while self._running:
                notify = await self._wait_for_notify(timeout=30)
                if notify is None:
                    await self._cmd("version", timeout=5)
                    continue
                log.debug("Event: %s", notify)
                parsed = _parse_notify(notify)
                if parsed:
                    sender, text = parsed
                    log.debug("Chat from %s: %s", sender, text)
                    await self.on_message(sender, text)
        finally:
            if self._transport:
                await self._transport.close()
            self._transport = None

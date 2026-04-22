"""Transport layer for TS3/TS6 ServerQuery.

Supports two wire protocols with an identical high-level API:

- **raw**: plain TCP telnet-style (typically port 10011).
  Plain-text credentials; enabled by default on TS3 servers.

- **ssh**: SSH-encrypted (typically port 10022).
  Encrypted credentials; enabled by default on TS6 and on TS3 when
  `query_ssh_port` is configured.

Both expose:
    send_line(line: str) -> None
    read_line(timeout: float) -> str | None  (strips trailing \r\n)
    close() -> None

The caller (ServerQueryClient / ChatListener) speaks the same text protocol
regardless of which transport is underneath.

Auto-selection:
    TS_QUERY_TRANSPORT in {auto, raw, ssh}, default auto.
    In auto mode, port 10011 -> raw, any other port -> ssh.
"""

from __future__ import annotations

import asyncio
import logging
import os

log = logging.getLogger(__name__)


def pick_transport_kind(port: int) -> str:
    """Return 'raw' or 'ssh' based on env + heuristics."""
    kind = os.getenv("TS_QUERY_TRANSPORT", "auto").lower()
    if kind in ("raw", "ssh"):
        return kind
    # auto: 10011 is the TS3/TS6 raw ServerQuery default, everything else SSH
    return "raw" if port == 10011 else "ssh"


class _LineTransport:
    """Common base with a shared inbound line buffer."""

    def __init__(self):
        self._buf = ""
        self._ev = asyncio.Event()
        self._closed = False

    def _feed(self, text: str) -> None:
        self._buf += text
        self._ev.set()

    async def read_line(self, timeout: float = 30) -> str | None:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while not self._closed:
            if "\n" in self._buf:
                line, _, rest = self._buf.partition("\n")
                self._buf = rest
                return line.rstrip("\r")
            remaining = max(0.05, deadline - loop.time())
            self._ev.clear()
            try:
                await asyncio.wait_for(self._ev.wait(), timeout=remaining)
            except asyncio.TimeoutError:
                return None
        return None

    def peek_buffer(self) -> str:
        return self._buf

    def drain_buffer(self) -> str:
        out = self._buf
        self._buf = ""
        return out


class RawTCPTransport(_LineTransport):
    """TS3 raw ServerQuery over plain TCP (port 10011)."""

    def __init__(self):
        super().__init__()
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._reader_task: asyncio.Task | None = None

    async def connect(
        self,
        host: str,
        port: int,
        username: str,
        password: str,
    ) -> None:
        self._reader, self._writer = await asyncio.open_connection(host, port)
        # Start background reader
        self._reader_task = asyncio.create_task(self._read_loop())

        # Wait for the banner:   TS3\nWelcome to the TeamSpeak 3 ServerQuery...
        # The second line ends just before the first command prompt.
        # Practical approach: wait a short moment, then drain whatever arrived.
        await asyncio.sleep(0.3)
        self.drain_buffer()

        # Authenticate.
        if username:
            self.send_line(
                f"login client_login_name={username} "
                f"client_login_password={password}"
            )
            resp = ""
            loop = asyncio.get_running_loop()
            deadline = loop.time() + 5
            while loop.time() < deadline:
                line = await self.read_line(timeout=max(0.1, deadline - loop.time()))
                if line is None:
                    break
                resp += line + "\n"
                if line.startswith("error "):
                    break
            if "error id=0" not in resp:
                raise ConnectionError(f"ServerQuery login failed: {resp.strip()}")
            log.debug("Raw TCP login OK")

    async def _read_loop(self) -> None:
        try:
            assert self._reader is not None
            while not self._closed:
                chunk = await self._reader.read(4096)
                if not chunk:
                    break
                self._feed(chunk.decode("utf-8", errors="replace"))
        except (asyncio.CancelledError, ConnectionResetError, OSError):
            pass
        finally:
            self._closed = True
            self._ev.set()

    def send_line(self, line: str) -> None:
        assert self._writer is not None
        self._writer.write((line + "\n").encode("utf-8"))

    async def close(self) -> None:
        self._closed = True
        if self._writer:
            try:
                self._writer.close()
                await self._writer.wait_closed()
            except Exception:
                pass
        if self._reader_task:
            self._reader_task.cancel()


class SSHTransport(_LineTransport):
    """TS3/TS6 ServerQuery over SSH (port 10022)."""

    def __init__(self):
        super().__init__()
        self._conn = None
        self._chan = None
        self._session = None

    async def connect(
        self,
        host: str,
        port: int,
        username: str,
        password: str,
    ) -> None:
        import asyncssh

        parent = self

        class _Session(asyncssh.SSHClientSession):
            def data_received(self, data, datatype):
                parent._feed(data)

            def connection_lost(self, exc):
                parent._closed = True
                parent._ev.set()

        self._conn, _ = await asyncssh.create_connection(
            asyncssh.SSHClient,
            host,
            port,
            username=username,
            password=password,
            known_hosts=None,
        )
        self._chan, self._session = await self._conn.create_session(_Session)

        # Drain initial banner
        await asyncio.sleep(0.3)
        self.drain_buffer()

    def send_line(self, line: str) -> None:
        assert self._chan is not None
        self._chan.write(line + "\n")

    async def close(self) -> None:
        self._closed = True
        if self._chan:
            try:
                self._chan.close()
            except Exception:
                pass
        if self._conn:
            try:
                self._conn.close()
                await self._conn.wait_closed()
            except Exception:
                pass


async def open_transport(
    host: str,
    port: int,
    username: str,
    password: str,
) -> _LineTransport:
    """Open a transport, picking raw vs ssh based on port/env."""
    kind = pick_transport_kind(port)
    if kind == "raw":
        t = RawTCPTransport()
    else:
        t = SSHTransport()
    await t.connect(host, port, username, password)
    log.info("ServerQuery transport: %s on %s:%d", kind, host, port)
    return t

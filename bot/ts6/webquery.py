import aiohttp
import os


class WebQueryClient:
    def __init__(self):
        self.base_url = (
            f"http://{os.getenv('TS_WEBQUERY_HOST', 'localhost')}"
            f":{os.getenv('TS_WEBQUERY_PORT', '10081')}"
        )
        self.api_key = os.getenv("TS_WEBQUERY_APIKEY", "")
        self.vserver = "1"
        self.session: aiohttp.ClientSession | None = None
        self._channel_id: str | None = None  # set by join_channel

    async def start(self):
        self.session = aiohttp.ClientSession(
            headers={"X-API-Key": self.api_key}
        )

    async def stop(self):
        if self.session:
            await self.session.close()
            self.session = None

    async def _new_session(self):
        """Replace the current session (called after a connection reset)."""
        if self.session:
            await self.session.close()
        self.session = aiohttp.ClientSession(
            headers={"X-API-Key": self.api_key}
        )

    async def get(self, endpoint: str, params: dict | None = None) -> dict:
        url = f"{self.base_url}/{self.vserver}/{endpoint}"
        try:
            async with self.session.get(url, params=params) as resp:
                resp.raise_for_status()
                return await resp.json()
        except (aiohttp.ServerDisconnectedError, aiohttp.ClientOSError):
            # TS6 WebQuery closes the connection after each response;
            # retry once with a fresh session.
            await self._new_session()
            async with self.session.get(url, params=params) as resp:
                resp.raise_for_status()
                return await resp.json()

    async def post(self, endpoint: str, data: dict | None = None) -> dict:
        url = f"{self.base_url}/{self.vserver}/{endpoint}"
        try:
            async with self.session.post(url, json=data) as resp:
                resp.raise_for_status()
                return await resp.json()
        except (aiohttp.ServerDisconnectedError, aiohttp.ClientOSError):
            await self._new_session()
            async with self.session.post(url, json=data) as resp:
                resp.raise_for_status()
                return await resp.json()

    async def send_channel_message(self, message: str) -> None:
        data: dict = {"targetmode": 2, "msg": message}
        if self._channel_id is not None:
            data["target"] = self._channel_id
        await self.post("sendtextmessage", data)

    async def get_clients(self) -> dict:
        return await self.get("clientlist")

    async def get_channels(self) -> dict:
        return await self.get("channellist")

    async def get_own_client_id(self) -> str:
        """Returns the clid of the current query session (from whoami)."""
        result = await self.get("whoami")
        return result["body"][0]["client_id"]

    async def find_channel_id(self, channel_name: str) -> str | None:
        """Returns the cid for the first channel matching channel_name, or None."""
        result = await self.get_channels()
        for ch in result.get("body", []):
            if ch.get("channel_name") == channel_name:
                return ch["cid"]
        return None

    async def join_channel(self, channel_name: str) -> bool:
        """Moves the serverquery client into the named channel. Returns True on success."""
        cid = await self.find_channel_id(channel_name)
        if cid is None:
            return False
        clid = await self.get_own_client_id()
        try:
            await self.post("clientmove", {"clid": clid, "cid": cid})
        except Exception:
            pass  # 770 = already member of channel is OK
        self._channel_id = cid  # store for send_channel_message
        return True

    async def move_client(self, client_id: int, channel_id: int) -> dict:
        return await self.post("clientmove", {"clid": client_id, "cid": channel_id})

    async def get_channel_info(self, channel_id: int) -> dict:
        return await self.get("channelinfo", {"cid": channel_id})

import pytest
from aioresponses import aioresponses
from ts6.webquery import WebQueryClient

BASE = "http://localhost:10081"

@pytest.fixture
def client():
    return WebQueryClient()

@pytest.mark.asyncio
async def test_start_creates_session(client):
    await client.start()
    assert client.session is not None
    await client.stop()

@pytest.mark.asyncio
async def test_get_clientlist(client):
    with aioresponses() as m:
        m.get(f"{BASE}/1/clientlist", payload={"body": [{"client_nickname": "alice"}]})
        await client.start()
        result = await client.get_clients()
        await client.stop()
    assert result["body"][0]["client_nickname"] == "alice"

@pytest.mark.asyncio
async def test_send_channel_message(client):
    with aioresponses() as m:
        m.post(f"{BASE}/1/sendtextmessage", payload={"status": {"code": 0}})
        await client.start()
        await client.send_channel_message("hello")
        await client.stop()
    # No exception = success

@pytest.mark.asyncio
async def test_get_channels(client):
    with aioresponses() as m:
        m.get(f"{BASE}/1/channellist", payload={"body": [{"channel_name": "TendroAudio"}]})
        await client.start()
        result = await client.get_channels()
        await client.stop()
    assert result["body"][0]["channel_name"] == "TendroAudio"

@pytest.mark.asyncio
async def test_join_channel_moves_client(client):
    """join_channel looks up the channel name and calls clientmove."""
    with aioresponses() as m:
        m.get(f"{BASE}/1/channellist", payload={"body": [{"channel_name": "TendroAudio", "cid": "7"}]})
        m.get(f"{BASE}/1/whoami", payload={"body": [{"client_id": "2"}]})
        m.post(f"{BASE}/1/clientmove", payload={"status": {"code": 0}})
        await client.start()
        ok = await client.join_channel("TendroAudio")
        await client.stop()
    assert ok is True


@pytest.mark.asyncio
async def test_join_channel_returns_false_when_not_found(client):
    with aioresponses() as m:
        m.get(f"{BASE}/1/channellist", payload={"body": [{"channel_name": "Lobby", "cid": "1"}]})
        await client.start()
        ok = await client.join_channel("TendroAudio")
        await client.stop()
    assert ok is False

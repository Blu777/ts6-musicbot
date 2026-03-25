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
async def test_textmessagereceive(client):
    """Tests the textmessagereceive endpoint used by ChatListener."""
    with aioresponses() as m:
        m.get(f"{BASE}/1/textmessagereceive", payload={"body": []})
        await client.start()
        result = await client.get_text_messages()
        await client.stop()
    assert "body" in result

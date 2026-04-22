"""
Integration tests against the real TS6 WebQuery server at ts.tendrolapio.cl.

Run with:
    pytest bot/tests/test_integration.py -v

These tests require the .env file at the project root with:
    TS_WEBQUERY_HOST, TS_WEBQUERY_PORT, TS_WEBQUERY_APIKEY, TS_CHANNEL

Note: TS6 WebQuery closes the TCP connection after each response. The client
retries automatically (retry logic in WebQueryClient.get/post). A 1s pause
between tests prevents triggering the server's connection rate limit.
"""

import asyncio
import os
import pathlib
import pytest
from dotenv import load_dotenv

# Load .env from project root (two levels up from this file)
_env_path = pathlib.Path(__file__).parent.parent.parent / ".env"
load_dotenv(_env_path, override=True)

from ts6.webquery import WebQueryClient  # noqa: E402

# Mark all tests in this module as integration (skipped in CI by default).
pytestmark = pytest.mark.integration


# Shared client for the whole test module — minimises new TCP connections.
@pytest.fixture(scope="module")
async def client():
    c = WebQueryClient()
    await c.start()
    yield c
    await c.stop()


# Pause 1 second between every test to avoid the server's rate limiter.
@pytest.fixture(autouse=True)
async def pace():
    await asyncio.sleep(1.0)
    yield


# ── Server connectivity ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_whoami_returns_serveradmin(client):
    """Serverquery session should report itself as connected."""
    result = await client.get("whoami")
    body = result["body"][0]
    assert result["status"]["code"] == 0
    assert "client_id" in body
    assert "virtualserver_status" in body
    assert body["virtualserver_status"] == "online"


# ── Channel list ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_channellist_contains_tendroaudio(client):
    """TendroAudio channel (cid=7) must be present."""
    result = await client.get_channels()
    channels = result.get("body", [])
    names = [ch["channel_name"] for ch in channels]
    assert "TendroAudio" in names, f"TendroAudio not found in channels: {names}"


@pytest.mark.asyncio
async def test_find_channel_id_tendroaudio(client):
    """find_channel_id must return cid '7' for TendroAudio."""
    cid = await client.find_channel_id("TendroAudio")
    assert cid == "7", f"Expected cid '7', got {cid!r}"


@pytest.mark.asyncio
async def test_find_channel_id_nonexistent_returns_none(client):
    cid = await client.find_channel_id("ChannelThatDoesNotExist_XYZ")
    assert cid is None


# ── Client list ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_clientlist_returns_list(client):
    result = await client.get_clients()
    assert "body" in result
    assert isinstance(result["body"], list)


# ── Own client identity ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_own_client_id_returns_valid_id(client):
    clid = await client.get_own_client_id()
    assert clid.isdigit(), f"Expected numeric clid, got {clid!r}"


# ── Channel join ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_join_tendroaudio_returns_true(client):
    """Bot session must be able to join (or already be in) TendroAudio."""
    ok = await client.join_channel("TendroAudio")
    assert ok is True


@pytest.mark.asyncio
async def test_join_nonexistent_channel_returns_false(client):
    ok = await client.join_channel("ChannelThatDoesNotExist_XYZ")
    assert ok is False


# ── After joining, serveradmin should be in channel 7 ─────────────────────────

@pytest.mark.asyncio
async def test_serveradmin_in_tendroaudio_after_join(client):
    await client.join_channel("TendroAudio")
    result = await client.get("whoami")
    channel_id = result["body"][0].get("client_channel_id")
    assert channel_id == "7", f"Expected to be in channel 7, got {channel_id!r}"


# ── Send channel message ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_send_channel_message_no_error(client):
    """Sending a message to TendroAudio must not raise."""
    await client.join_channel("TendroAudio")
    # This actually sends a visible message — intentionally minimal
    await client.send_channel_message("[integration test] bot connectivity ok")

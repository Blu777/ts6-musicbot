import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import commands.parser as parser_module
from commands.parser import CommandParser

TRACK = {
    "title": "Never Gonna Give You Up",
    "url": "x",
    "duration": 213,
    "uploader": "Rick Astley",
    "webpage_url": "x",
}


@pytest.fixture
def setup():
    parser_module.BOT_NICKNAME = "testbot"
    player = MagicMock()
    player.enqueue = AsyncMock(return_value=1)
    player.enqueue_many = AsyncMock(return_value=2)
    player.skip = AsyncMock()
    player.stop = AsyncMock()
    player.pause = AsyncMock(return_value=True)
    player.resume = AsyncMock(return_value=True)
    player.shuffle = AsyncMock(return_value=0)
    player.clear_queue = AsyncMock(return_value=0)
    player.set_volume = AsyncMock()
    player.queue = []
    player.volume = 85
    player.current_track = MagicMock(return_value=None)
    player.is_paused = MagicMock(return_value=False)
    ts = MagicMock()
    ts.send_channel_message = AsyncMock()
    return CommandParser(player, ts), player, ts


@pytest.mark.asyncio
async def test_non_command_ignored(setup):
    parser, player, ts = setup
    await parser.handle("alice", "hello world")
    ts.send_channel_message.assert_not_called()


@pytest.mark.asyncio
async def test_bot_message_ignored(setup):
    parser, player, ts = setup
    await parser.handle("testbot", "!play something")
    player.enqueue.assert_not_called()


@pytest.mark.asyncio
async def test_play_resolves_and_enqueues(setup):
    parser, player, ts = setup
    with patch("commands.parser.resolve", AsyncMock(return_value=TRACK)), \
         patch("commands.parser.download_track", AsyncMock(return_value="/tmp/x.m4a")):
        await parser.handle("alice", "!play rick astley")
    player.enqueue.assert_awaited_once()


@pytest.mark.asyncio
async def test_play_without_args_sends_error(setup):
    parser, player, ts = setup
    await parser.handle("alice", "!play")
    ts.send_channel_message.assert_awaited_once()
    assert "Uso" in ts.send_channel_message.call_args[0][0]


@pytest.mark.asyncio
async def test_play_download_failure_still_enqueues(setup):
    """If download fails, parser should still enqueue so player streams directly."""
    parser, player, ts = setup
    with patch("commands.parser.resolve", AsyncMock(return_value=TRACK)), \
         patch("commands.parser.download_track", AsyncMock(side_effect=RuntimeError("boom"))):
        await parser.handle("alice", "!play rick astley")
    player.enqueue.assert_awaited_once()


@pytest.mark.asyncio
async def test_playlist_enqueues_many(setup):
    parser, player, ts = setup
    tracks = [TRACK, {**TRACK, "title": "T2"}]
    with patch("commands.parser.resolve_playlist", AsyncMock(return_value=tracks)):
        await parser.handle("alice", "!playlist https://youtube.com/playlist?list=xxx")
    player.enqueue_many.assert_awaited_once()


@pytest.mark.asyncio
async def test_playlist_requires_url(setup):
    parser, player, ts = setup
    await parser.handle("alice", "!playlist not-a-url")
    ts.send_channel_message.assert_awaited_once()
    assert "Uso" in ts.send_channel_message.call_args[0][0]


@pytest.mark.asyncio
async def test_skip_delegates(setup):
    parser, player, ts = setup
    await parser.handle("alice", "!skip")
    player.skip.assert_awaited_once()


@pytest.mark.asyncio
async def test_stop_delegates(setup):
    parser, player, ts = setup
    await parser.handle("alice", "!stop")
    player.stop.assert_awaited_once()


@pytest.mark.asyncio
async def test_pause_delegates(setup):
    parser, player, ts = setup
    await parser.handle("alice", "!pause")
    player.pause.assert_awaited_once()


@pytest.mark.asyncio
async def test_resume_delegates(setup):
    parser, player, ts = setup
    await parser.handle("alice", "!resume")
    player.resume.assert_awaited_once()


@pytest.mark.asyncio
async def test_shuffle_delegates(setup):
    parser, player, ts = setup
    await parser.handle("alice", "!shuffle")
    player.shuffle.assert_awaited_once()


@pytest.mark.asyncio
async def test_clear_delegates(setup):
    parser, player, ts = setup
    await parser.handle("alice", "!clear")
    player.clear_queue.assert_awaited_once()


@pytest.mark.asyncio
async def test_vol_valid(setup):
    parser, player, ts = setup
    await parser.handle("alice", "!vol 70")
    player.set_volume.assert_awaited_once_with(70)


@pytest.mark.asyncio
async def test_vol_invalid(setup):
    parser, player, ts = setup
    await parser.handle("alice", "!vol abc")
    ts.send_channel_message.assert_awaited_once()
    assert "Uso" in ts.send_channel_message.call_args[0][0]


@pytest.mark.asyncio
async def test_help_sends_message(setup):
    parser, player, ts = setup
    await parser.handle("alice", "!help")
    ts.send_channel_message.assert_awaited_once()


@pytest.mark.asyncio
async def test_queue_empty(setup):
    parser, player, ts = setup
    await parser.handle("alice", "!queue")
    msg = ts.send_channel_message.call_args[0][0]
    assert "vac" in msg.lower()


@pytest.mark.asyncio
async def test_handler_exception_sends_error_message(setup):
    parser, player, ts = setup
    player.skip.side_effect = RuntimeError("kaboom")
    await parser.handle("alice", "!skip")
    # At least one error message should be sent to the channel
    sent = [c.args[0] for c in ts.send_channel_message.await_args_list]
    assert any("Error" in s or "kaboom" in s for s in sent)

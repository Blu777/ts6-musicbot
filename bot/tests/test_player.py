import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from audio.player import AudioPlayer

TRACK = {"title": "Test Track", "url": "https://example.com/stream.m4a", "duration": 60}


@pytest.fixture
def player():
    return AudioPlayer()


@pytest.mark.asyncio
async def test_enqueue_returns_position(player):
    with patch.object(player, "_play_loop", new_callable=AsyncMock):
        pos = await player.enqueue(TRACK)
    assert pos == 1


@pytest.mark.asyncio
async def test_enqueue_multiple_tracks(player):
    with patch.object(player, "_play_loop", new_callable=AsyncMock):
        p1 = await player.enqueue(TRACK)
        p2 = await player.enqueue({**TRACK, "title": "Track 2"})
    assert p1 == 1
    assert p2 == 2


@pytest.mark.asyncio
async def test_stop_clears_queue(player):
    with patch.object(player, "_play_loop", new_callable=AsyncMock):
        await player.enqueue(TRACK)
        await player.enqueue(TRACK)
    mock_proc = MagicMock()
    player._current_process = mock_proc
    await player.stop()
    assert player.queue == []
    mock_proc.terminate.assert_called_once()


@pytest.mark.asyncio
async def test_skip_terminates_current(player):
    mock_proc = MagicMock()
    player._current_process = mock_proc
    await player.skip()
    mock_proc.terminate.assert_called_once()


@pytest.mark.asyncio
async def test_set_volume_clamps(player):
    with patch("audio.player.os") as mock_os:
        await player.set_volume(150)
        assert player.volume == 100
        await player.set_volume(-10)
        assert player.volume == 0


@pytest.mark.asyncio
async def test_play_loop_consumes_queue(player):
    async def fake_play_track(track):
        pass

    player.queue = [TRACK, {**TRACK, "title": "Track 2"}]
    with patch.object(player, "_play_track", side_effect=fake_play_track):
        await player._play_loop()

    assert player.queue == []
    assert player._playing is False

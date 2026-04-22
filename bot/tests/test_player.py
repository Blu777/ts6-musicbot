import signal
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from audio.player import AudioPlayer

_has_sigstop = hasattr(signal, "SIGSTOP")

TRACK = {
    "title": "Test Track",
    "url": "https://example.com/stream.m4a",
    "duration": 60,
    "webpage_url": "https://example.com/stream.m4a",
}


@pytest.fixture
def player():
    return AudioPlayer()


@pytest.mark.asyncio
async def test_enqueue_returns_position(player):
    with patch.object(AudioPlayer, "_play_loop", new_callable=AsyncMock):
        pos = await player.enqueue(TRACK)
    assert pos == 1


@pytest.mark.asyncio
async def test_enqueue_many_returns_total(player):
    with patch.object(AudioPlayer, "_play_loop", new_callable=AsyncMock):
        total = await player.enqueue_many([TRACK, {**TRACK, "title": "B"}])
    assert total == 2
    assert len(player.queue) == 2


@pytest.mark.asyncio
async def test_stop_clears_queue(player):
    with patch.object(AudioPlayer, "_play_loop", new_callable=AsyncMock):
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
    with patch("audio.player.subprocess.run"):
        await player.set_volume(150)
        assert player.volume == 100
        await player.set_volume(-10)
        assert player.volume == 0


@pytest.mark.skipif(not _has_sigstop, reason="SIGSTOP only available on Unix")
@pytest.mark.asyncio
async def test_pause_resume(player):
    mock_proc = MagicMock()
    player._current_process = mock_proc
    ok = await player.pause()
    assert ok
    assert player.is_paused()
    mock_proc.send_signal.assert_called_once()
    ok = await player.resume()
    assert ok
    assert not player.is_paused()


@pytest.mark.asyncio
async def test_pause_without_track_returns_false(player):
    assert await player.pause() is False
    assert await player.resume() is False


@pytest.mark.asyncio
async def test_shuffle_randomizes(player):
    tracks = [{**TRACK, "title": f"T{i}"} for i in range(20)]
    player.queue = list(tracks)
    import random
    random.seed(42)
    n = await player.shuffle()
    assert n == 20
    # Extremely unlikely to remain identical after a seeded shuffle
    assert [t["title"] for t in player.queue] != [t["title"] for t in tracks]


@pytest.mark.asyncio
async def test_clear_queue(player):
    player.queue = [TRACK, TRACK, TRACK]
    dropped = await player.clear_queue()
    assert dropped == 3
    assert player.queue == []


@pytest.mark.asyncio
async def test_play_loop_consumes_queue(player):
    async def fake_play_track(track):
        pass

    player.queue = [TRACK, {**TRACK, "title": "Track 2"}]
    with patch.object(player, "_play_track", side_effect=fake_play_track), \
         patch.object(player, "_flush_sink", new_callable=AsyncMock), \
         patch.object(player, "_apply_volume_to_sink", new_callable=AsyncMock):
        await player._play_loop()

    assert player.queue == []
    assert player._playing is False

"""
AudioPlayer: queue management + FFmpeg -> PulseAudio virtual sink.

FFmpeg streams audio to the `musicbot_sink` PulseAudio sink.
The TS6 client captures `musicbot_sink.monitor` as its microphone input.
"""

import asyncio
import subprocess
import logging
import os

log = logging.getLogger(__name__)

PULSE_SINK = "musicbot_sink"


class AudioPlayer:
    def __init__(self):
        self.queue: list[dict] = []
        self._current_process: subprocess.Popen | None = None
        self._playing = False
        self.volume = int(os.getenv("AUDIO_VOLUME", "85"))

    async def enqueue(self, track: dict) -> int:
        """Add track to queue. Returns queue position (1-indexed). Starts playback if idle."""
        self.queue.append(track)
        if not self._playing:
            asyncio.create_task(self._play_loop())
        return len(self.queue)

    async def skip(self) -> None:
        if self._current_process:
            self._current_process.terminate()
            log.info("Skipped current track.")

    async def stop(self) -> None:
        self.queue.clear()
        if self._current_process:
            self._current_process.terminate()
        self._playing = False

    async def set_volume(self, vol: int) -> None:
        self.volume = max(0, min(100, vol))
        os.system(f"pactl set-sink-volume {PULSE_SINK} {self.volume}%")

    def current_track(self) -> dict | None:
        return self._current_track if hasattr(self, "_current_track") else None

    async def _play_loop(self) -> None:
        self._playing = True
        while self.queue:
            track = self.queue.pop(0)
            self._current_track = track
            await self._play_track(track)
        self._current_track = None
        self._playing = False

    async def _play_track(self, track: dict) -> None:
        log.info("Playing: %s", track["title"])
        cmd = [
            "ffmpeg",
            "-reconnect", "1",
            "-reconnect_streamed", "1",
            "-reconnect_delay_max", "5",
            "-i", track["url"],
            "-acodec", "pcm_s16le",
            "-ar", "48000",
            "-ac", "2",
            "-af", f"volume={self.volume / 100}",
            "-f", "pulse",
            PULSE_SINK,
            "-loglevel", "warning",
        ]
        loop = asyncio.get_running_loop()
        self._current_process = await loop.run_in_executor(
            None, lambda: subprocess.Popen(cmd)
        )
        await loop.run_in_executor(None, self._current_process.wait)
        self._current_process = None

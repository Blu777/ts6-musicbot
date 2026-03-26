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
        self._loop_task: asyncio.Task | None = None
        self._current_track: dict | None = None

    async def enqueue(self, track: dict) -> int:
        """Add track to queue. Returns queue position (1-indexed). Starts playback if idle."""
        self.queue.append(track)
        if not self._playing:
            self._loop_task = asyncio.create_task(self._play_loop())
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
        subprocess.run(
            ["pactl", "set-sink-volume", PULSE_SINK, f"{self.volume}%"],
            check=False,
        )

    def current_track(self) -> dict | None:
        return self._current_track

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
            "-thread_queue_size", "4096",
            "-i", track["url"],
            "-acodec", "pcm_s16le",
            "-ar", "48000",
            "-ac", "2",
            "-af", f"volume={self.volume / 100}",
            "-f", "pulse",
            "-fragment_size", "32768",    # 32 KB PulseAudio write chunks
            PULSE_SINK,
            "-loglevel", "warning",
        ]
        env = os.environ.copy()
        # Ensure ffmpeg finds the PulseAudio socket even if the inherited
        # environment doesn't carry PULSE_SERVER (e.g. under some container runtimes).
        if "PULSE_SERVER" not in env:
            env["PULSE_SERVER"] = "unix:/tmp/pulse/native"

        loop = asyncio.get_running_loop()
        self._current_process = await loop.run_in_executor(
            None, lambda: subprocess.Popen(cmd, env=env)
        )
        await loop.run_in_executor(None, self._current_process.wait)
        self._current_process = None

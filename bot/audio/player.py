"""
AudioPlayer: queue management + FFmpeg -> PulseAudio virtual sink.

FFmpeg streams audio to the `musicbot_sink` PulseAudio sink.
The TS6 client captures `musicbot_sink.monitor` as its microphone input.
"""

import asyncio
import subprocess
import logging
import os

from audio.resolver import re_resolve

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

    async def _flush_sink(self) -> None:
        """Suspend/resume the sink to drain residual audio between tracks."""
        env = os.environ.copy()
        env.setdefault("PULSE_SERVER", "unix:/tmp/pulse/native")
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, lambda: subprocess.run(
            ["pactl", "suspend-sink", PULSE_SINK, "1"], env=env, check=False
        ))
        await asyncio.sleep(0.2)
        await loop.run_in_executor(None, lambda: subprocess.run(
            ["pactl", "suspend-sink", PULSE_SINK, "0"], env=env, check=False
        ))

    async def _play_loop(self) -> None:
        self._playing = True
        while self.queue:
            track = self.queue.pop(0)
            self._current_track = track
            await self._play_track(track)
            await self._flush_sink()
        self._current_track = None
        self._playing = False

    async def _play_track(self, track: dict) -> None:
        # Re-resolve stream URL just before playback — YouTube URLs expire in ~6h.
        # This ensures queued tracks always start with a fresh URL.
        if track.get("webpage_url"):
            try:
                fresh_url = await re_resolve(track["webpage_url"])
                track = {**track, "url": fresh_url}
            except Exception as e:
                log.warning("Re-resolve failed, using cached URL: %s", e)

        log.info("Playing: %s", track["title"])
        cmd = [
            "ffmpeg",
            "-loglevel", "warning",
            # ── Input: network stream with large buffer ──
            "-reconnect", "1",
            "-reconnect_streamed", "1",
            "-reconnect_delay_max", "15",
            "-probesize", "100M",
            "-analyzeduration", "20000000",     # 20 s
            "-fflags", "+discardcorrupt",
            "-thread_queue_size", "8192",
            "-i", track["url"],
            # ── Audio processing: float32 matches PulseAudio sink, SoX resampler ──
            "-acodec", "pcm_f32le",
            "-ar", "48000",
            "-ac", "2",
            "-af", f"volume={self.volume / 100},"
                   "aresample=resampler=soxr:precision=28:async=1000",
            # ── PulseAudio output with 5 s target buffer ──
            "-f", "pulse",
            "-buffer_duration", "5000",
            PULSE_SINK,
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

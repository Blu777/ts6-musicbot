"""
AudioPlayer: queue management + FFmpeg -> PulseAudio virtual sink.

FFmpeg streams audio to the `musicbot_sink` PulseAudio sink.
The TS6 client captures `musicbot_sink.monitor` as its microphone input.

Volume is applied via `pactl set-sink-volume` on the sink (unified, so
changes take effect mid-track). FFmpeg no longer carries `-af volume=`.
"""

import asyncio
import logging
import os
import random
import signal
import subprocess

from audio.resolver import re_resolve, clear_cache, delete_track_file

log = logging.getLogger(__name__)

PULSE_SINK = os.getenv("PULSE_SINK_NAME", "musicbot_sink")


class AudioPlayer:
    def __init__(self):
        self.queue: list[dict] = []
        self._current_process: subprocess.Popen | None = None
        self._playing = False
        self._paused = False
        self.volume = int(os.getenv("AUDIO_VOLUME", "85"))
        self._loop_task: asyncio.Task | None = None
        self._current_track: dict | None = None

    # ── Queue API ─────────────────────────────────────────────────────────

    async def enqueue(self, track: dict) -> int:
        """Add track to queue. Returns queue position (1-indexed)."""
        self.queue.append(track)
        if not self._playing:
            self._loop_task = asyncio.create_task(self._play_loop())
        return len(self.queue)

    async def enqueue_many(self, tracks: list[dict]) -> int:
        """Bulk enqueue. Returns total queue length after."""
        self.queue.extend(tracks)
        if not self._playing:
            self._loop_task = asyncio.create_task(self._play_loop())
        return len(self.queue)

    async def skip(self) -> None:
        if self._current_process:
            self._current_process.terminate()
            log.info("Skipped current track.")
        self._paused = False

    async def stop(self) -> None:
        for t in self.queue:
            if t.get("local_path"):
                delete_track_file(t["local_path"])
        self.queue.clear()
        if self._current_process:
            self._current_process.terminate()
        if self._current_track and self._current_track.get("local_path"):
            delete_track_file(self._current_track["local_path"])
        self._playing = False
        self._paused = False

    async def pause(self) -> bool:
        """Pause ffmpeg via SIGSTOP (Unix only). Returns True if actually paused."""
        sig = getattr(signal, "SIGSTOP", None)
        if sig is None:
            log.warning("pause() not supported on this platform (no SIGSTOP)")
            return False
        if self._current_process and not self._paused:
            try:
                self._current_process.send_signal(sig)
                self._paused = True
                return True
            except (OSError, ProcessLookupError):
                return False
        return False

    async def resume(self) -> bool:
        """Resume ffmpeg via SIGCONT (Unix only). Returns True if actually resumed."""
        sig = getattr(signal, "SIGCONT", None)
        if sig is None:
            return False
        if self._current_process and self._paused:
            try:
                self._current_process.send_signal(sig)
                self._paused = False
                return True
            except (OSError, ProcessLookupError):
                return False
        return False

    async def shuffle(self) -> int:
        """Randomize the pending queue in place. Returns queue length."""
        random.shuffle(self.queue)
        return len(self.queue)

    async def clear_queue(self) -> int:
        """Drop pending tracks (but keep current). Returns how many were dropped."""
        dropped = len(self.queue)
        for t in self.queue:
            if t.get("local_path"):
                delete_track_file(t["local_path"])
        self.queue.clear()
        return dropped

    # ── Volume ────────────────────────────────────────────────────────────

    async def set_volume(self, vol: int) -> None:
        self.volume = max(0, min(100, vol))
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, lambda: subprocess.run(
            ["pactl", "set-sink-volume", PULSE_SINK, f"{self.volume}%"],
            check=False,
        ))

    def current_track(self) -> dict | None:
        return self._current_track

    def is_paused(self) -> bool:
        return self._paused

    # ── Internal ──────────────────────────────────────────────────────────

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

    async def _apply_volume_to_sink(self) -> None:
        """Reapply current volume to the sink (used on startup / after sink reset)."""
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, lambda: subprocess.run(
            ["pactl", "set-sink-volume", PULSE_SINK, f"{self.volume}%"],
            check=False,
        ))

    async def _play_loop(self) -> None:
        self._playing = True
        await self._apply_volume_to_sink()
        try:
            while self.queue:
                track = self.queue.pop(0)
                self._current_track = track
                try:
                    await self._play_track(track)
                except Exception as e:
                    log.warning("Playback failed for %s: %s", track.get("title"), e)
                if track.get("local_path"):
                    delete_track_file(track["local_path"])
                await self._flush_sink()
        finally:
            self._current_track = None
            self._playing = False
            self._paused = False

    async def _play_track(self, track: dict) -> None:
        local_path = track.get("local_path")
        if local_path:
            source = local_path
            log.info("Playing (local): %s", track["title"])
            extra_input_flags: list[str] = []
        else:
            # Fallback: stream directly — re-resolve to get a fresh URL.
            if track.get("webpage_url"):
                try:
                    fresh_url = await re_resolve(track["webpage_url"])
                    track = {**track, "url": fresh_url}
                except Exception as e:
                    log.warning("Re-resolve failed, using cached URL: %s", e)
            source = track["url"]
            log.info("Playing (stream): %s", track["title"])
            extra_input_flags = [
                "-reconnect", "1",
                "-reconnect_streamed", "1",
                "-reconnect_delay_max", "15",
                "-probesize", "100M",
                "-analyzeduration", "20000000",
                "-fflags", "+discardcorrupt",
                "-thread_queue_size", "8192",
            ]

        # Bigger buffer helps smooth out:
        #  - yt-dlp -> ffmpeg read hiccups
        #  - Pulse sink underruns if the TS6 encoder grabs late
        # Configurable via AUDIO_BUFFER_MS (default 10s).
        buffer_ms = os.getenv("AUDIO_BUFFER_MS", "10000")

        # Anti-VAD trick: mix in ~-72 dB of white noise so the TS6 client's
        # Voice Activity Detection always sees energy and doesn't gate music
        # passages as silence. Totally inaudible to humans (below the noise
        # floor of most speakers), but keeps the Opus transmission continuous.
        #
        # Disabled by default now that `scripts/ts6_patch_audio.py` turns
        # VAD/AGC/denoise off directly in the TS6 client, which gives cleaner
        # audio than injecting any noise. Set AUDIO_ANTI_VAD=1 to re-enable
        # the hack as a safety net if your TS6 client has VAD on anyway.
        anti_vad = os.getenv("AUDIO_ANTI_VAD", "0") != "0"
        if anti_vad:
            filter_args = [
                "-filter_complex",
                # Generate mono white noise at gain 0.00025 (~-72 dB), upmix to
                # stereo (pan=stereo|c0=c0|c1=c0), then mix with the track.
                # Total output level ≈ track level (noise is -72 dB below).
                "anoisesrc=color=white:amplitude=0.00025:sample_rate=48000,"
                "pan=stereo|c0=c0|c1=c0[noise];"
                "[0:a][noise]amix=inputs=2:duration=first:normalize=0[out]",
                "-map", "[out]",
            ]
        else:
            filter_args = []

        cmd = [
            "ffmpeg",
            "-loglevel", "warning",
            *extra_input_flags,
            "-i", source,
            *filter_args,
            # float32 matches PulseAudio sink, SoX resampler
            "-acodec", "pcm_f32le",
            "-ar", "48000",
            "-ac", "2",
            # No -af volume=: volume is controlled at the sink level via pactl.
            "-f", "pulse",
            "-buffer_duration", buffer_ms,
            PULSE_SINK,
        ]
        env = os.environ.copy()
        if "PULSE_SERVER" not in env:
            env["PULSE_SERVER"] = "unix:/tmp/pulse/native"

        loop = asyncio.get_running_loop()
        self._current_process = await loop.run_in_executor(
            None, lambda: subprocess.Popen(cmd, env=env)
        )
        try:
            await loop.run_in_executor(None, self._current_process.wait)
        finally:
            self._current_process = None
            self._paused = False

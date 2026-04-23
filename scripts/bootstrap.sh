#!/bin/bash
# Second stage of the entrypoint: runs as the unprivileged musicbot user.
# Starts Xvfb, PulseAudio, the TS6 client, and finally the Python bot.
set -e

echo "[bootstrap] Running as $(id)"

echo "[bootstrap] Starting Xvfb on :99..."
# Tiny resolution + 16bpp → Xvfb uses 10x less RAM and CPU. The bot has no
# real UI interaction, so we don't need a big framebuffer.
Xvfb :99 -screen 0 "${XVFB_SCREEN:-320x240x16}" -nolisten tcp &
XVFB_PID=$!
sleep 1

echo "[bootstrap] Starting PulseAudio..."
PULSE_SOCKET=/tmp/pulse/native
PULSE_SINK_NAME="${PULSE_SINK_NAME:-musicbot_sink}"
mkdir -p /tmp/pulse
# Latency: module-virtual-source's buffer is the one TS6 reads from, so
# that's where it matters. module-null-sink doesn't accept latency_msec
# (passing it makes the module fail to load, which leaves the sink absent).
PULSE_LATENCY_MS="${PULSE_LATENCY_MS:-1000}"
pulseaudio -n \
    --exit-idle-time=-1 \
    --daemonize=no \
    --log-target=stderr \
    --load="module-native-protocol-unix socket=${PULSE_SOCKET} auth-anonymous=1" \
    --load="module-null-sink sink_name=${PULSE_SINK_NAME} sink_properties=device.description=MusicBot_Virtual_Sink rate=48000 format=float32le channels=2 channel_map=front-left,front-right" \
    --load="module-virtual-source source_name=${PULSE_SINK_NAME}.mic master=${PULSE_SINK_NAME}.monitor rate=48000 format=float32le channels=2 channel_map=front-left,front-right latency_msec=${PULSE_LATENCY_MS}" \
    --load="module-null-sink sink_name=musicbot_deaf sink_properties=device.description=MusicBot_Deaf_Sink rate=48000 format=float32le channels=2 channel_map=front-left,front-right" &
PULSE_PID=$!
export PULSE_SERVER="unix:${PULSE_SOCKET}"
export PULSE_SINK_NAME
sleep 2
if ! kill -0 $PULSE_PID 2>/dev/null; then
    echo "[bootstrap] FATAL: PulseAudio failed to start — audio will not work"
    exit 1
fi
# Verify the sink was actually created. If a module fails to load (e.g. bad
# arg), the daemon stays up but the sink is missing — causing ffmpeg to spin
# with "No such entity". Fail loud here instead.
if ! pactl list short sinks 2>/dev/null | grep -q "^[0-9]*[[:space:]]\+${PULSE_SINK_NAME}[[:space:]]"; then
    echo "[bootstrap] FATAL: null-sink ${PULSE_SINK_NAME} did not load; check PulseAudio module args" >&2
    pactl list short sinks >&2 || true
    exit 1
fi
echo "[bootstrap] PulseAudio socket: ${PULSE_SOCKET} (sink ${PULSE_SINK_NAME} present)"

# ── Disable VAD / AGC / denoise in TS6 client ──────────────────────────────
# The TS6 desktop client stores its audio preprocessor config inside
# settings.db (json_blobs.audio_settings). We want raw pass-through of the
# music stream: no voice-activity gating, no AGC, no denoise.
#
# The TS6 client creates settings.db inside a profile subdirectory
# (`Default/settings.db` — same layout as the Windows client). On the very
# first container boot it doesn't exist yet, so we do a short warm-up run
# to let TS6 write its defaults, then patch, then launch for real.
TS6_DIR="${TS6_CONFIG_DIR:-/data/ts6-config}"
# Match either a top-level settings.db or any <profile>/settings.db
find_settings_db() {
    local hit
    hit="$(find "$TS6_DIR" -maxdepth 2 -name settings.db -type f 2>/dev/null | head -n1)"
    echo "$hit"
}

if [ -z "$(find_settings_db)" ]; then
    echo "[bootstrap] First run — warming up TS6 so it creates settings.db..."
    /app/scripts/launch_ts6.sh &
    WARMUP_PID=$!
    # Wait up to 30s for settings.db to appear
    for _ in $(seq 1 30); do
        [ -n "$(find_settings_db)" ] && break
        sleep 1
    done
    # Give the client a few more seconds to actually write audio_settings
    if [ -n "$(find_settings_db)" ]; then
        sleep 6
    fi
    echo "[bootstrap] Stopping warm-up TS6 instance..."
    pkill -TERM -f /opt/ts6/TeamSpeak 2>/dev/null || true
    sleep 2
    pkill -KILL -f /opt/ts6/TeamSpeak 2>/dev/null || true
    wait "$WARMUP_PID" 2>/dev/null || true
fi

SETTINGS_DB="$(find_settings_db)"
echo "[bootstrap] Patching TS6 audio preprocessor (VAD/AGC/denoise off)..."
echo "[bootstrap] settings.db: ${SETTINGS_DB:-<not found>}"
python3 /app/scripts/ts6_patch_audio.py "$TS6_DIR" || \
    echo "[bootstrap] Warning: TS6 audio patch failed (non-fatal)"

echo "[bootstrap] Launching TS6 client..."
/app/scripts/launch_ts6.sh &
TS6_PID=$!
sleep 8  # allow client to connect and register with WebQuery

# Graceful shutdown on SIGTERM/SIGINT
trap 'echo "[bootstrap] Shutting down..."; kill $TS6_PID $PULSE_PID $XVFB_PID 2>/dev/null; exit 0' TERM INT

echo "[bootstrap] Starting Python orchestrator..."
cd /app
python3 bot/main.py

# Cleanup if Python exits on its own
kill $XVFB_PID $TS6_PID $PULSE_PID 2>/dev/null || true

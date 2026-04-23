#!/bin/bash
# Second stage of the entrypoint: runs as the unprivileged musicbot user.
# Starts Xvfb, PulseAudio, the TS6 client, and finally the Python bot.
set -e

echo "[bootstrap] Running as $(id)"

echo "[bootstrap] Starting Xvfb on :99..."
# Tiny resolution + 16bpp → Xvfb uses 10x less RAM and CPU. The bot has no
# real UI interaction, so we don't need a big framebuffer. When VNC is on
# we bump to a usable desktop size automatically (overrideable via XVFB_SCREEN).
if [ -z "${XVFB_SCREEN:-}" ]; then
    if [ "${VNC_ENABLED:-0}" = "1" ] || [ -n "${VNC_PASSWORD:-}" ]; then
        XVFB_SCREEN="1280x800x24"
    else
        XVFB_SCREEN="320x240x16"
    fi
fi
echo "[bootstrap] Xvfb screen size: ${XVFB_SCREEN}"
Xvfb :99 -screen 0 "${XVFB_SCREEN}" -nolisten tcp &
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

# ── Optional: remote desktop (VNC) for configuring the TS6 client by hand ──
# When VNC_ENABLED=1 (or a VNC_PASSWORD is set), expose the Xvfb display :99
# over VNC so you can point a viewer at the container and interact with the
# TS6 UI (e.g. to toggle VAD/AGC, pick devices, accept EULAs, etc).
#
#   VNC_ENABLED       : "1" to turn it on (default off)
#   VNC_PASSWORD      : required when enabled; clients must auth with it
#   VNC_PORT          : TCP port inside the container (default 5900)
#   NOVNC_ENABLED     : "1" to also start a browser-based noVNC proxy
#   NOVNC_PORT        : HTTP port for noVNC (default 6080)
#   XVFB_SCREEN       : bumped automatically to 1280x800x24 when VNC is on,
#                       unless you override it explicitly
#   TS6_WINDOW_SIZE   : TS6 client window size (same default as Xvfb when VNC
#                       is on; override via env var e.g. "1920x1080")
if [ "${VNC_ENABLED:-0}" = "1" ] || [ -n "${VNC_PASSWORD:-}" ]; then
    if [ -z "${VNC_PASSWORD:-}" ]; then
        echo "[bootstrap] WARNING: VNC_ENABLED=1 but VNC_PASSWORD is empty."
        echo "[bootstrap] Refusing to start x11vnc without a password."
    else
        VNC_PORT="${VNC_PORT:-5900}"
        mkdir -p /home/musicbot/.vnc
        x11vnc -storepasswd "$VNC_PASSWORD" /home/musicbot/.vnc/passwd >/dev/null
        echo "[bootstrap] Starting x11vnc on :${VNC_PORT} (display :99)..."
        x11vnc \
            -display :99 \
            -rfbport "$VNC_PORT" \
            -rfbauth /home/musicbot/.vnc/passwd \
            -forever \
            -shared \
            -noxdamage \
            -quiet \
            -bg \
            -o /tmp/x11vnc.log
        VNC_RUNNING=1

        if [ "${NOVNC_ENABLED:-0}" = "1" ]; then
            NOVNC_PORT="${NOVNC_PORT:-6080}"
            echo "[bootstrap] Starting noVNC on http://0.0.0.0:${NOVNC_PORT}/vnc.html..."
            websockify --web /usr/share/novnc "$NOVNC_PORT" "localhost:${VNC_PORT}" \
                >/tmp/novnc.log 2>&1 &
            NOVNC_PID=$!
        fi
    fi
fi

echo "[bootstrap] Launching TS6 client..."
/app/scripts/launch_ts6.sh &
TS6_PID=$!
sleep 8  # allow client to connect and register with WebQuery

# Graceful shutdown on SIGTERM/SIGINT
trap 'echo "[bootstrap] Shutting down..."; kill $TS6_PID $PULSE_PID $XVFB_PID ${NOVNC_PID:-} 2>/dev/null; pkill -f x11vnc 2>/dev/null; exit 0' TERM INT

echo "[bootstrap] Starting Python orchestrator..."
cd /app
python3 bot/main.py

# Cleanup if Python exits on its own
kill $XVFB_PID $TS6_PID $PULSE_PID 2>/dev/null || true

#!/bin/bash
set -e

# Clean up stale lock from previous runs
rm -f /tmp/.X99-lock

echo "[entrypoint] Starting Xvfb on :99..."
Xvfb :99 -screen 0 1280x720x24 &
XVFB_PID=$!
sleep 1

echo "[entrypoint] Starting PulseAudio..."
# Run with explicit socket so pactl and the TS6 client know where to connect.
# Use -n + manual module load to avoid system.pa config issues in Docker as root.
PULSE_SOCKET=/tmp/pulse/native
mkdir -p /tmp/pulse
pulseaudio -n \
    --exit-idle-time=-1 \
    --daemonize=no \
    --log-target=stderr \
    --load="module-native-protocol-unix socket=${PULSE_SOCKET} auth-anonymous=1" \
    --load="module-null-sink sink_name=musicbot_sink sink_properties=device.description=MusicBot_Virtual_Sink" \
    --load="module-virtual-source source_name=musicbot_sink.mic master=musicbot_sink.monitor" &
PULSE_PID=$!
export PULSE_SERVER="unix:${PULSE_SOCKET}"
sleep 2
if ! kill -0 $PULSE_PID 2>/dev/null; then
    echo "[entrypoint] WARNING: PulseAudio failed to start — audio will not work"
fi
echo "[entrypoint] PulseAudio socket: ${PULSE_SOCKET}"

echo "[entrypoint] Launching TS6 client..."
/app/scripts/launch_ts6.sh &
TS6_PID=$!
sleep 8  # allow client to connect and register with WebQuery

echo "[entrypoint] Starting Python orchestrator..."
cd /app
python3 bot/main.py

# Cleanup
kill $XVFB_PID $TS6_PID $PULSE_PID 2>/dev/null || true

#!/bin/bash
set -e

# Clean up stale lock from previous runs
rm -f /tmp/.X99-lock

echo "[entrypoint] Starting Xvfb on :99..."
Xvfb :99 -screen 0 1280x720x24 &
XVFB_PID=$!
sleep 1

echo "[entrypoint] Starting PulseAudio..."
# In Docker as root: system mode requires the socket dir to exist
mkdir -p /var/run/pulse
# Start in foreground as background process (avoids daemonize issues in Docker)
pulseaudio --system --disallow-exit --exit-idle-time=-1 --log-target=stderr &
PULSE_PID=$!
sleep 2
# Verify it started
if ! kill -0 $PULSE_PID 2>/dev/null; then
    echo "[entrypoint] WARNING: PulseAudio failed to start — audio will not work"
fi

echo "[entrypoint] Setting up virtual audio..."
/app/scripts/setup_audio.sh

echo "[entrypoint] Launching TS6 client..."
/app/scripts/launch_ts6.sh &
TS6_PID=$!
sleep 8  # allow client to connect and register with WebQuery

echo "[entrypoint] Starting Python orchestrator..."
cd /app
python3 bot/main.py

# Cleanup
kill $XVFB_PID $TS6_PID $PULSE_PID 2>/dev/null || true

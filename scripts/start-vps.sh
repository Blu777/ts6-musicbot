#!/bin/bash
set -e

APP_DIR="/opt/ts6-musicbot"

# Clean up stale locks from previous runs
rm -f /tmp/.X99-lock
pkill -9 pulseaudio 2>/dev/null || true
rm -f /run/pulse.pid /run/pulseaudio.pid /root/.config/pulse/pid 2>/dev/null || true
rm -rf /tmp/pulse* 2>/dev/null || true

echo "[start] Starting Xvfb on :99..."
Xvfb :99 -screen 0 1280x720x24 &
XVFB_PID=$!
sleep 1

echo "[start] Starting PulseAudio..."
PULSE_SOCKET=/tmp/pulse/native
mkdir -p /tmp/pulse
pulseaudio -n \
    --exit-idle-time=-1 \
    --daemonize=no \
    --log-target=stderr \
    --load="module-native-protocol-unix socket=${PULSE_SOCKET} auth-anonymous=1" \
    --load="module-null-sink sink_name=musicbot_sink sink_properties=device.description=MusicBot_Virtual_Sink rate=48000 format=float32le channels=2 channel_map=front-left,front-right" \
    --load="module-virtual-source source_name=musicbot_sink.mic master=musicbot_sink.monitor rate=48000 format=float32le channels=2 channel_map=front-left,front-right" \
    --load="module-null-sink sink_name=musicbot_deaf sink_properties=device.description=MusicBot_Deaf_Sink rate=48000 format=float32le channels=2 channel_map=front-left,front-right" &
PULSE_PID=$!
export PULSE_SERVER="unix:${PULSE_SOCKET}"
sleep 2
if ! kill -0 $PULSE_PID 2>/dev/null; then
    echo "[start] WARNING: PulseAudio failed to start"
fi

# Copy settings.ini to TS6 config dir
mkdir -p /root/.config/TeamSpeak
cp "$APP_DIR/ts6_config/settings.ini" /root/.config/TeamSpeak/settings.ini

echo "[start] Launching TS6 client..."
"$APP_DIR/scripts/launch_ts6.sh" &
TS6_PID=$!
sleep 8

echo "[start] Starting Python bot..."
cd "$APP_DIR"
python3 bot/main.py

# Cleanup on exit
kill $XVFB_PID $TS6_PID $PULSE_PID 2>/dev/null || true

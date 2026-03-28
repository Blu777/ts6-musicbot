#!/bin/bash
# Launches the TS6 client headless and connects to the configured server.
# Binary name confirmed: TeamSpeak (from teamspeak-client.tar.gz)

TS6_BIN="/opt/ts6/TeamSpeak"

if [ ! -f "$TS6_BIN" ]; then
    echo "[ts6] ERROR: TeamSpeak binary not found at $TS6_BIN"
    exit 1
fi

# TS6 client only registers ts3server:// scheme handler (confirmed from binary strings)
CONNECT_URI="ts3server://${TS_SERVER_HOST}?port=${TS_SERVER_PORT:-9988}&nickname=${TS_BOT_NICKNAME:-tendroaudio}${TS_CHANNEL:+&channel=$TS_CHANNEL}${TS_SERVER_PASSWORD:+&password=$TS_SERVER_PASSWORD}"

echo "[ts6] Connecting to: $CONNECT_URI"

DISPLAY=:99 PULSE_SINK=musicbot_deaf PULSE_SOURCE=musicbot_sink.monitor "$TS6_BIN" --no-sandbox "$CONNECT_URI" > /tmp/ts6_client.log 2>&1 &

# If URI argument is not honored by the client, use xdotool fallback:
# xdotool search --sync --name "TeamSpeak" key ctrl+s
# (see docs/workarounds section in README)

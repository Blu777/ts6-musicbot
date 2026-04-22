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

# Electron flags to minimise CPU usage. The TS6 client is a Chromium app and
# by default eats ~1+ CPU on a headless server doing nothing. Disabling GPU
# paths, background work, animations and telemetry can easily halve the load.
ELECTRON_FLAGS=(
    --no-sandbox
    --disable-gpu
    --disable-software-rasterizer
    --disable-dev-shm-usage
    --disable-extensions
    --disable-background-networking
    --disable-background-timer-throttling
    --disable-backgrounding-occluded-windows
    --disable-renderer-backgrounding
    --disable-breakpad
    --disable-component-update
    --disable-default-apps
    --disable-sync
    --disable-translate
    --disable-features=TranslateUI,BlinkGenPropertyTrees,Vulkan
    --metrics-recording-only
    --mute-audio
    --no-first-run
    --window-size=320,240
    # Cap V8 heap → smaller / quicker garbage collections, shorter GC pauses
    --js-flags=--max-old-space-size=256
)

DISPLAY=:99 \
PULSE_SINK=musicbot_deaf \
PULSE_SOURCE="${PULSE_SINK_NAME:-musicbot_sink}.monitor" \
    "$TS6_BIN" "${ELECTRON_FLAGS[@]}" "$CONNECT_URI" \
    > /var/log/musicbot/ts6_client.log 2>&1 &

# If URI argument is not honored by the client, use xdotool fallback:
# xdotool search --sync --name "TeamSpeak" key ctrl+s
# (see docs/workarounds section in README)

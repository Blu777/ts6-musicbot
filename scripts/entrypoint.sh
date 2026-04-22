#!/bin/bash
# TS6 MusicBot entrypoint.
#
# Runs as root initially to:
#   1. Remap the `musicbot` user UID/GID to PUID/PGID (TrueNAS style)
#   2. Fix ownership on mounted volumes
#   3. Drop privileges via gosu and exec the actual bootstrap as `musicbot`.
set -e

# ── Remap UID/GID if requested ───────────────────────────────────────────────
PUID="${PUID:-1000}"
PGID="${PGID:-1000}"
CUR_UID="$(id -u musicbot 2>/dev/null || echo 0)"
CUR_GID="$(id -g musicbot 2>/dev/null || echo 0)"

if [ "$CUR_UID" != "$PUID" ] || [ "$CUR_GID" != "$PGID" ]; then
    echo "[entrypoint] Remapping musicbot to UID=$PUID GID=$PGID"
    groupmod -o -g "$PGID" musicbot
    usermod -o -u "$PUID" musicbot
fi

# ── Prepare data directories ─────────────────────────────────────────────────
AUDIO_CACHE_DIR="${AUDIO_CACHE_DIR:-/data/cache}"
TS6_CONFIG_DIR="${TS6_CONFIG_DIR:-/data/ts6-config}"
mkdir -p "$AUDIO_CACHE_DIR" "$TS6_CONFIG_DIR" /tmp/pulse /var/log/musicbot
chown -R musicbot:musicbot "$AUDIO_CACHE_DIR" "$TS6_CONFIG_DIR" /tmp/pulse /var/log/musicbot

# TS6 client reads its config from $HOME/.config/TeamSpeak by default.
# We point $HOME at the persistent dir and symlink the config.
MUSICBOT_HOME="$(getent passwd musicbot | cut -d: -f6)"
mkdir -p "$MUSICBOT_HOME/.config"
if [ ! -L "$MUSICBOT_HOME/.config/TeamSpeak" ]; then
    rm -rf "$MUSICBOT_HOME/.config/TeamSpeak"
    ln -s "$TS6_CONFIG_DIR" "$MUSICBOT_HOME/.config/TeamSpeak"
fi
# Always refresh the settings.ini from the image (overrides stale copies)
cp /app/ts6_config/settings.ini "$TS6_CONFIG_DIR/settings.ini"
chown -R musicbot:musicbot "$MUSICBOT_HOME/.config" "$TS6_CONFIG_DIR"

# Clean up stale locks from previous runs
rm -f /tmp/.X99-lock
pkill -9 pulseaudio 2>/dev/null || true
rm -f /run/pulse.pid /run/pulseaudio.pid "$MUSICBOT_HOME/.config/pulse/pid" 2>/dev/null || true
rm -rf /tmp/pulse-* 2>/dev/null || true

export HOME="$MUSICBOT_HOME"
export AUDIO_CACHE_DIR TS6_CONFIG_DIR

# ── Drop privileges and run the real bootstrap ───────────────────────────────
exec gosu musicbot /app/scripts/bootstrap.sh

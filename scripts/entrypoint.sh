#!/bin/bash
# TS6 MusicBot entrypoint.
#
# Runs as root initially to:
#   1. Remap the `musicbot` user UID/GID to PUID/PGID (TrueNAS style)
#   2. Fix ownership on mounted volumes
#   3. Drop privileges via gosu and exec the actual bootstrap as `musicbot`.
set -e

# ── Sanity check: the image MUST have a musicbot user baked in ──────────────
if ! id musicbot >/dev/null 2>&1; then
    echo "[entrypoint] FATAL: user 'musicbot' does not exist in the image." >&2
    echo "[entrypoint] This is an image build bug — please rebuild or pull a newer tag." >&2
    exit 1
fi

# ── Remap UID/GID if requested ───────────────────────────────────────────────
PUID="${PUID:-1000}"
PGID="${PGID:-1000}"
CUR_UID="$(id -u musicbot)"
CUR_GID="$(id -g musicbot)"

if [ "$CUR_UID" != "$PUID" ] || [ "$CUR_GID" != "$PGID" ]; then
    echo "[entrypoint] Remapping musicbot to UID=$PUID GID=$PGID"
    groupmod -o -g "$PGID" musicbot
    usermod -o -u "$PUID" -g "$PGID" musicbot
fi

# ── Prepare data directories ─────────────────────────────────────────────────
AUDIO_CACHE_DIR="${AUDIO_CACHE_DIR:-/data/cache}"
TS6_CONFIG_DIR="${TS6_CONFIG_DIR:-/data/ts6-config}"
mkdir -p "$AUDIO_CACHE_DIR" "$TS6_CONFIG_DIR" /tmp/pulse /var/log/musicbot /opt/ts6
chown -R musicbot:musicbot "$AUDIO_CACHE_DIR" "$TS6_CONFIG_DIR" /tmp/pulse /var/log/musicbot

# X11 socket dir — Xvfb (running as musicbot) can't create this under /tmp
# with euid!=0, so we pre-create it here as root.
mkdir -p /tmp/.X11-unix
chmod 1777 /tmp/.X11-unix

# PulseAudio cookie: Pulse logs warnings when the cookie file is missing.
# Create an empty one owned by musicbot to silence the noise.
MUSICBOT_HOME_EARLY="$(getent passwd musicbot | cut -d: -f6)"
mkdir -p "$MUSICBOT_HOME_EARLY/.config/pulse"
touch "$MUSICBOT_HOME_EARLY/.config/pulse/cookie"
chown -R musicbot:musicbot "$MUSICBOT_HOME_EARLY/.config"

# ── Extract TS6 client from /data if the image doesn't already include it ────
# The proprietary binary is NOT shipped in public images. On first boot we look
# for /data/teamspeak-client.tar.gz and extract it to /opt/ts6/.
if [ ! -x /opt/ts6/TeamSpeak ]; then
    if [ -f /data/teamspeak-client.tar.gz ]; then
        echo "[entrypoint] First run — extracting TS6 client from /data/teamspeak-client.tar.gz"
        tar -xzf /data/teamspeak-client.tar.gz -C /opt/ts6 \
            --no-same-permissions --no-same-owner
        chmod +x /opt/ts6/TeamSpeak
        echo "[entrypoint] TS6 client extracted to /opt/ts6/"
    else
        echo "[entrypoint] FATAL: TS6 client not found."
        echo "[entrypoint] Download the Linux 64-bit client from"
        echo "[entrypoint]   https://teamspeak.com/en/downloads/#client"
        echo "[entrypoint] and place it as /data/teamspeak-client.tar.gz"
        echo "[entrypoint] (host path: <your-data-mount>/teamspeak-client.tar.gz)."
        exit 1
    fi
fi

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

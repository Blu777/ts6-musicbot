FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive
ENV DISPLAY=:99
# PULSE_SERVER is set at runtime in entrypoint.sh after PulseAudio starts
ENV PYTHONUNBUFFERED=1

# x11vnc / novnc / websockify → optional remote desktop (off by default,
# enabled at runtime via VNC_ENABLED=1). Lets you connect to the TS6
# client UI to configure audio settings, VAD/AGC, pick devices, etc.
RUN apt-get update && apt-get install -y \
    pulseaudio \
    pulseaudio-utils \
    xvfb \
    x11-utils \
    xdotool \
    x11vnc \
    novnc \
    websockify \
    ffmpeg \
    python3 \
    python3-pip \
    python3-venv \
    wget \
    curl \
    ca-certificates \
    jq \
    gosu \
    procps \
    libglib2.0-0 \
    libnss3 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libasound2t64 \
    libnotify4 \
    sqlite3 \
    && rm -rf /var/lib/apt/lists/*

# yt-dlp (latest from GitHub). Will be further upgraded at container start
# by bot/main.py (AUTO_UPDATE_YT_DLP=1) to keep up with extractor changes.
RUN curl -L https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp \
    -o /usr/local/bin/yt-dlp && chmod +x /usr/local/bin/yt-dlp

# ── Cliente TeamSpeak 6 ──────────────────────────────────────────────────────
# El binario es propietario (EULA de TeamSpeak Systems) y NO se redistribuye
# en esta imagen. El usuario debe colocar teamspeak-client.tar.gz en el volumen
# /data antes del primer arranque. El entrypoint lo detecta y lo extrae a
# /opt/ts6 en el primer run (idempotente).
#
# Si existe teamspeak-client.tar.gz al lado del Dockerfile durante `docker build`,
# se incluye igualmente — útil para builds locales que no quieren tocar /data.
# ─────────────────────────────────────────────────────────────────────────────
RUN mkdir -p /opt/ts6 /tmp/ts6src
# NOTICE.md is included as a "guaranteed sibling" so the glob always matches
# at least one file — otherwise buildkit errors when teamspeak-client.tar.gz
# is absent (public builds for ghcr.io / Docker Hub).
COPY teamspeak-client.tar.gz* NOTICE.md /tmp/ts6src/
RUN if [ -f /tmp/ts6src/teamspeak-client.tar.gz ]; then \
        tar -xzf /tmp/ts6src/teamspeak-client.tar.gz -C /opt/ts6 \
            --no-same-permissions --no-same-owner \
        && chmod +x /opt/ts6/TeamSpeak \
        && echo "[build] TS6 baked into image"; \
    else \
        echo "[build] No TS6 tarball bundled — will extract from /data at runtime"; \
    fi \
    && rm -rf /tmp/ts6src

# Create non-root user `musicbot` (UID/GID can be remapped at runtime via
# PUID/PGID env vars, TrueNAS-style). We use --no-sandbox for TS6 so we
# don't need the SUID chrome-sandbox.
#
# ubuntu:24.04 ships with a default `ubuntu` user at UID/GID 1000, so we
# remove it first — otherwise `groupadd -g 1000` would fail and the previous
# `|| true` hid the failure, leaving the image without a `musicbot` group.
RUN userdel -r ubuntu 2>/dev/null || true \
    && groupadd -g 1000 musicbot \
    && useradd -u 1000 -g 1000 -m -s /bin/bash musicbot
RUN usermod -a -G audio,pulse,pulse-access musicbot 2>/dev/null || true

WORKDIR /app

COPY bot/requirements.txt .
RUN pip3 install --break-system-packages -r requirements.txt

COPY bot/ ./bot/
COPY scripts/ ./scripts/
COPY ts6_config/ ./ts6_config/
RUN chmod +x scripts/*.sh

# Default runtime dirs (can be overridden via env)
ENV AUDIO_CACHE_DIR=/data/cache
ENV TS6_CONFIG_DIR=/data/ts6-config

HEALTHCHECK --interval=30s --timeout=10s --start-period=45s --retries=3 \
    CMD python3 /app/bot/healthcheck.py || exit 1

CMD ["./scripts/entrypoint.sh"]

FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive
ENV DISPLAY=:99
# PULSE_SERVER is set at runtime in entrypoint.sh after PulseAudio starts
ENV PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y \
    pulseaudio \
    pulseaudio-utils \
    xvfb \
    x11-utils \
    xdotool \
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
    && rm -rf /var/lib/apt/lists/*

# yt-dlp (latest from GitHub). Will be further upgraded at container start
# by bot/main.py (AUTO_UPDATE_YT_DLP=1) to keep up with extractor changes.
RUN curl -L https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp \
    -o /usr/local/bin/yt-dlp && chmod +x /usr/local/bin/yt-dlp

# TeamSpeak 6 client from local tar.gz
# ── Versión verificada ────────────────────────────────────────────────────────
# Archivo: teamspeak-client.tar.gz  (excluido del repo por tamaño, 183 MB)
# SHA-256: b9ba408a0b58170ce32384fc8bba56800840d694bd310050cbadd09246d4bf27
# Fuente:  https://teamspeak.com/en/downloads/#client  (Linux, 64-bit)
# ─────────────────────────────────────────────────────────────────────────────
COPY teamspeak-client.tar.gz /tmp/ts6client.tar.gz
RUN mkdir -p /opt/ts6 \
    && tar -xzf /tmp/ts6client.tar.gz -C /opt/ts6 --no-same-permissions --no-same-owner \
    && rm /tmp/ts6client.tar.gz \
    && chmod +x /opt/ts6/TeamSpeak

# Create non-root user `musicbot` (UID/GID can be remapped at runtime via
# PUID/PGID env vars, TrueNAS-style). We use --no-sandbox for TS6 so we
# don't need the SUID chrome-sandbox.
RUN groupadd -g 1000 musicbot \
    && useradd -u 1000 -g 1000 -m -s /bin/bash musicbot \
    && usermod -a -G audio,pulse,pulse-access musicbot 2>/dev/null || true

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

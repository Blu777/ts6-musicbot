FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive
ENV DISPLAY=:99
# PULSE_SERVER is set dynamically in entrypoint.sh after PulseAudio starts

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

# yt-dlp (latest from GitHub, more up to date than pip)
RUN curl -L https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp \
    -o /usr/local/bin/yt-dlp && chmod +x /usr/local/bin/yt-dlp

# TeamSpeak 6 client from local tar.gz
# ── Versión verificada ────────────────────────────────────────────────────────
# Archivo: teamspeak-client.tar.gz  (excluido del repo por tamaño, 183 MB)
# SHA-256: b9ba408a0b58170ce32384fc8bba56800840d694bd310050cbadd09246d4bf27
# MD5:     0464db3534303c5e32ea0aaec300ad90
# Fecha descarga: 2025-03-25
# Fuente:  https://teamspeak.com/en/downloads/#client  (Linux, 64-bit)
# Extraído en /opt/ts6/ — binario principal: TeamSpeak
# ─────────────────────────────────────────────────────────────────────────────
COPY teamspeak-client.tar.gz /tmp/ts6client.tar.gz
RUN mkdir -p /opt/ts6 \
    && tar -xzf /tmp/ts6client.tar.gz -C /opt/ts6 \
    && rm /tmp/ts6client.tar.gz \
    && chmod +x /opt/ts6/TeamSpeak \
    && chown root:root /opt/ts6/chrome-sandbox \
    && chmod 4755 /opt/ts6/chrome-sandbox

# Pre-configure TS6 client
RUN mkdir -p /root/.config/TeamSpeak
COPY ts6_config/settings.ini /root/.config/TeamSpeak/settings.ini

WORKDIR /app

COPY bot/requirements.txt .
RUN pip3 install --break-system-packages -r requirements.txt

COPY bot/ ./bot/
COPY scripts/ ./scripts/
COPY ts6_config/ ./ts6_config/
RUN chmod +x scripts/*.sh

CMD ["./scripts/entrypoint.sh"]

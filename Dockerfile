FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive
ENV DISPLAY=:99
ENV PULSE_SERVER=unix:/tmp/pulse/native

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
    && rm -rf /var/lib/apt/lists/*

# yt-dlp (latest from GitHub, more up to date than pip)
RUN curl -L https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp \
    -o /usr/local/bin/yt-dlp && chmod +x /usr/local/bin/yt-dlp

# TeamSpeak 6 client from local tar.gz
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
RUN chmod +x scripts/*.sh

CMD ["./scripts/entrypoint.sh"]

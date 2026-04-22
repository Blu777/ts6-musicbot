"""
Orchestrator entry point. Wires all modules and runs the async event loop.
"""

import asyncio
import logging
import os
import subprocess
import sys

from dotenv import load_dotenv

from ts6.webquery import WebQueryClient
from ts6.serverquery import ServerQueryClient
from ts6.chat_listener import ChatListener
from audio.player import AudioPlayer
from audio.resolver import clear_cache
from commands.parser import CommandParser
import commands.parser as parser_module


load_dotenv()

_LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, _LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
)
# Silence very noisy third-party loggers unless DEBUG is explicitly requested.
if _LOG_LEVEL != "DEBUG":
    for noisy in ("asyncssh", "aiohttp.access", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

log = logging.getLogger("main")


def _try_update_yt_dlp() -> None:
    """Best-effort upgrade of yt-dlp at startup.

    YouTube breaks extractors often, so we try to pull the latest yt-dlp on every
    container start. Failures are logged and ignored. Can be disabled by
    setting AUTO_UPDATE_YT_DLP=0.
    """
    if os.getenv("AUTO_UPDATE_YT_DLP", "1") == "0":
        return
    try:
        log.info("Updating yt-dlp...")
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", "--quiet",
             "--upgrade", "--break-system-packages", "yt-dlp"],
            capture_output=True, text=True, timeout=60,
        )
        if result.returncode == 0:
            log.info("yt-dlp update OK")
        else:
            log.warning("yt-dlp update returned %d: %s",
                        result.returncode, result.stderr.strip()[:200])
    except Exception as e:
        log.warning("yt-dlp update failed: %s", e)


async def main():
    parser_module.BOT_NICKNAME = os.getenv("TS_BOT_NICKNAME", "MusicBot")

    _try_update_yt_dlp()
    clear_cache()

    # Pick the ServerQuery transport:
    #   - WebQuery HTTP  (TS6 only — requires TS_WEBQUERY_APIKEY)
    #   - SSH ServerQuery (works on TS3 AND TS6)
    use_webquery = bool(os.getenv("TS_WEBQUERY_APIKEY"))
    if use_webquery:
        log.info("Using WebQuery HTTP client (TS6 mode)")
        ts_client = WebQueryClient()
    else:
        log.info("Using SSH ServerQuery client (TS3/universal mode)")
        ts_client = ServerQueryClient()
    await ts_client.start()

    player = AudioPlayer()

    # ChatListener created first so the parser can reference it for !move
    listener = ChatListener(ts_client, None)
    cmd_parser = CommandParser(player, ts_client, listener)

    async def on_message(sender: str, message: str):
        await cmd_parser.handle(sender, message)

    listener.on_message = on_message

    channel = os.getenv("TS_CHANNEL", "")
    log.info("Bot started. Channel: %s", channel)

    if channel:
        try:
            ok = await ts_client.join_channel(channel)
            if ok:
                log.info("Query session joined channel: %s", channel)
            else:
                log.warning("Channel not found: %s", channel)
        except Exception as e:
            log.warning("Could not join channel: %s", e)

    # Apply configured volume to the sink up front so it's consistent even
    # before the first track plays.
    try:
        await player.set_volume(player.volume)
    except Exception as e:
        log.debug("Initial volume set failed: %s", e)

    try:
        await ts_client.send_channel_message(
            "MusicBot connected. Type !help for commands."
        )
    except Exception as e:
        log.warning("Could not send startup message: %s", e)

    try:
        await listener.start()
    except asyncio.CancelledError:
        log.info("Shutting down...")
    finally:
        await player.stop()
        await ts_client.stop()
        clear_cache()


if __name__ == "__main__":
    asyncio.run(main())

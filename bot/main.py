"""
Orchestrator entry point. Wires all modules and runs the async event loop.
"""

import asyncio
import logging
import os
from dotenv import load_dotenv

from ts6.webquery import WebQueryClient
from ts6.chat_listener import ChatListener
from audio.player import AudioPlayer
from commands.parser import CommandParser
import commands.parser as parser_module

load_dotenv()
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
)
log = logging.getLogger("main")


async def main():
    parser_module.BOT_NICKNAME = os.getenv("TS_BOT_NICKNAME", "MusicBot")

    ts_client = WebQueryClient()
    await ts_client.start()

    player = AudioPlayer()
    cmd_parser = CommandParser(player, ts_client)

    async def on_message(sender: str, message: str):
        await cmd_parser.handle(sender, message)

    listener = ChatListener(ts_client, on_message)

    log.info("Bot started. Channel: %s", os.getenv("TS_CHANNEL"))
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
        await ts_client.stop()


if __name__ == "__main__":
    asyncio.run(main())

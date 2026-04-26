import logging
from telegram import Bot
import asyncio
logger = logging.getLogger(__name__)

BOT: Bot | None = None
BOT_LOOP = None

def set_bot(bot: Bot, loop=None):
    global BOT
    BOT = bot
    logger.info("✅ Bot instance set")


async def send_message(chat_id: int, text: str, parse_mode: str | None = None):
    if not BOT:
        logger.error("❌ Bot not initialized")
        return

    try:
        await BOT.send_message(
            chat_id=chat_id,
            text=text,
            parse_mode=parse_mode
        )
    except Exception as e:
        logger.error(f"Telegram send failed: {e}")

def send_plain_safe(chat_id: int, text: str):
    if BOT_LOOP is None:
        logger.error("❌ Bot loop not initialized")
        return

    async def _send():
        await send_message(chat_id, text)

    asyncio.run_coroutine_threadsafe(_send(), BOT_LOOP)

async def send_plain(chat_id: int, text: str):
    await send_message(chat_id, text)

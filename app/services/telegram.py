import logging
from telegram import Bot

logger = logging.getLogger(__name__)

_bot: Bot | None = None


def set_bot(bot: Bot):
    global _bot
    _bot = bot


async def send_message(chat_id: int, text: str, parse_mode: str = "MarkdownV2"):
    if not _bot:
        logger.error("❌ Bot not initialized")
        return

    try:
        await _bot.send_message(
            chat_id=chat_id,
            text=text,
            parse_mode=parse_mode if parse_mode else None,
        )
    except Exception as e:
        logger.error(f"Telegram send failed: {e}")


async def send_plain(chat_id: int, text: str):
    await send_message(chat_id, text, parse_mode=None)
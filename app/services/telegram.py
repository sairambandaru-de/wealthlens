import os
import httpx
import logging

logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
BASE_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"


async def send_message(chat_id: int, text: str, parse_mode: str = "MarkdownV2"):
    async with httpx.AsyncClient() as client:
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": parse_mode,
        }
        try:
            resp = await client.post(f"{BASE_URL}/sendMessage", json=payload, timeout=10)
            if not resp.is_success:
                logger.error(f"Telegram error: {resp.text}")
        except Exception as e:
            logger.error(f"Failed to send message: {e}")


async def send_plain(chat_id: int, text: str):
    await send_message(chat_id, text, parse_mode="")

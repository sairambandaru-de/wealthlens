import asyncio
import datetime
import logging

from app.database import get_all_users, get_user_id
from app.services.telegram import send_plain,send_plain_safe
from app.services.analytics import build_portfolio, build_daily_message
#from services.daily_update import (
#    calculate_portfolio_metrics,
#    format_daily_message,
#    format_nifty_section
#)

logger = logging.getLogger(__name__)


def get_ist_now():
    """Return current IST time"""
    return datetime.datetime.utcnow() + datetime.timedelta(hours=5, minutes=30)

def get_portfolio_by_chat(chat_id: int):
    user_id = get_user_id(chat_id)
    if not user_id:
        return None
    return get_portfolio(user_id)

async def process_user(chat_id: int):
    try:
        message = await build_daily_message(chat_id)
        send_plain(chat_id, message)

        # ✅ throttle (Telegram safe)
        await asyncio.sleep(0.05)

    except Exception as e:
        logger.error(f"❌ User {chat_id} failed: {e}", exc_info=True)


async def run_daily_job():
    logger.info("🚀 Running daily job")

    try:
        users = await asyncio.to_thread(get_all_users)

        success = 0
        failed = 0
        for user in users:
            try:
                chat_id = user["telegram_id"]

                user_id = get_user_id(chat_id)
                if not user_id:
                    logger.warning(f"User not found for chat_id={chat_id}")
                    continue

                message = await build_daily_message(user_id)

                send_plain_safe(chat_id, message)
                success += 1

            except Exception as e:
                logger.error(f"User {chat_id} failed: {e}", exc_info=True)
                failed += 1
        
        logger.info(f"✅ Scheduler done | Success: {success} | Failed: {failed}")

    except Exception as e:
        logger.exception(f"Scheduler job failed: {e}")

async def run_scheduler():
    logger.info("⏰ Scheduler started (IST based)")
    await asyncio.sleep(5)
    last_run_date = None

    while True:
        try:
            now = get_ist_now()

            # ✅ LOG CURRENT TIME
            logger.debug(f"⏰ Scheduler check: {now.strftime('%Y-%m-%d %H:%M:%S')} IST")

            # ✅ safer time window
            if now.hour == 17 and now.minute < 5:
                today = now.date()

                if last_run_date != today:
                    logger.info(f"🚀 Triggering 5PM job at {now.strftime('%H:%M:%S')} IST")

                    await run_daily_job()
                    last_run_date = today

                else:
                    logger.info("⏭️ Already executed today, skipping")

            await asyncio.sleep(30)

        except Exception as e:
            logger.error(f"Scheduler loop error: {e}", exc_info=True)
            await asyncio.sleep(5)

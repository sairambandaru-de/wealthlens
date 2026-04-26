import asyncio
import time
import os
from datetime import datetime
from dotenv import load_dotenv
from app.database import get_connection, get_all_users, get_assets, get_user_id, get_active_users, set_user_inactive
from app.services.analytics import build_daily_message
from telegram import Bot
import traceback

load_dotenv()
TEST_MODE=False #True
test_user_id=1302442231

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("TELEGRAM_BOT_TOKEN not found in .env")


def store_nifty(db, price_service):
    today = datetime.now().strftime("%Y-%m-%d")

    nifty_price = price_service.get_nifty_price()  # e.g. ^NSEI

    if nifty_price:
        db.execute("""
            INSERT OR REPLACE INTO market_history (date, nifty_close)
            VALUES (?, ?)
        """, (today, nifty_price))
        db.commit()

def get_last_two_nifty(db):
    rows = db.execute("""
        SELECT date, nifty_close
        FROM market_history
        ORDER BY date DESC
        LIMIT 2
    """).fetchall()

    return rows

def calculate_nifty_return(nifty_rows):
    if len(nifty_rows) < 2:
        return None  # Not enough data

    today = nifty_rows[0][1]
    yesterday = nifty_rows[1][1]

    if not yesterday:
        return None

    return ((today - yesterday) / yesterday) * 100


def get_all_users_id():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT telegram_id FROM users")
    users = cursor.fetchall()

    conn.close()

    return [u[0] for u in users]


async def send_updates():
    bot = Bot(token=BOT_TOKEN)

    users = get_all_users_id()
    test_user_id
    if TEST_MODE:
        for us in users:
            print(us,"telgram_id")
        users = [u for u in users if u  == test_user_id]
        print(f"🧪 Test mode active → sending to {len(users)} user\n")
        print(users," Users*****************")
    for user_id in users:
        try:
            u_id = get_user_id(user_id)
            msg = await build_daily_message(u_id)
            await bot.send_message(chat_id=user_id, text=msg)


            # 🔥 IMPORTANT: avoid Telegram rate limits
            await asyncio.sleep(0.1)

        except Exception as e:
            print(f"Failed for {user_id}: {e}")
            set_user_inactive(user_id)
            continue


if __name__ == "__main__":
    asyncio.run(send_updates())

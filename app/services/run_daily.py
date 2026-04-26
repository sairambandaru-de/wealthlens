import asyncio
import os
from datetime import datetime
from dotenv import load_dotenv
from telegram import Bot
import traceback

from app.database import (
    get_connection,
    get_user_id,
    set_user_inactive
)
from app.services.analytics import build_daily_message
from app.services.market_service import fetch_nifty, store_index

load_dotenv()

TEST_MODE = False #False  # True for testing
TEST_USER_ID = 1302442231

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("❌ TELEGRAM_BOT_TOKEN not found in .env")


# -----------------------------
# DB Helpers
# -----------------------------
def get_all_users_id():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT telegram_id FROM users")
    users = cursor.fetchall()

    conn.close()

    return [u[0] for u in users if u[0] is not None]


# -----------------------------
# Step 1: Update Market Data
# -----------------------------
def update_market_data():
    try:
        data = fetch_nifty()

        if not data:
            print("⚠️ Nifty fetch failed or insufficient data")
            return

        store_index(data)
        print(f"✅ Nifty stored: {data['change_percent']}%")

    except Exception as e:
        print("❌ Error updating market data:", e)
        traceback.print_exc()


# -----------------------------
# Step 2: Send Daily Updates
# -----------------------------
async def send_updates():
    bot = Bot(token=BOT_TOKEN)

    try:
        users = get_all_users_id()

        if not users:
            print("⚠️ No users found")
            return

        # ✅ Test mode filter
        if TEST_MODE:
            users = [u for u in users if u == TEST_USER_ID]
            print(f"🧪 Test mode → {len(users)} user")

        print(f"🚀 Sending updates to {len(users)} users")

        success = 0
        failed = 0

        for user_id in users:
            try:
                # Validate user_id
                if not isinstance(user_id, int):
                    print(f"⚠️ Invalid user_id skipped: {user_id}")
                    continue

                u_id = get_user_id(user_id)
                if not u_id:
                    print(f"⚠️ No internal user_id for {user_id}")
                    continue

                # Build message
                msg = await build_daily_message(u_id)

                if not msg:
                    print(f"⚠️ Empty message for {user_id}")
                    continue

                # Send message
                await bot.send_message(
                    chat_id=user_id,
                    text=msg
                )

                success += 1

                # Rate limit protection (~10 msg/sec)
                await asyncio.sleep(0.1)

            except Exception as e:
                failed += 1
                print(f"❌ Failed for {user_id}: {e}")

                # Mark inactive (user blocked bot / invalid)
                try:
                    set_user_inactive(user_id)
                except Exception:
                    pass

        print(f"✅ Done → Success: {success}, Failed: {failed}")

    finally:
        pass 

# -----------------------------
# MAIN ENTRY
# -----------------------------
async def main():
    print(f"\n📅 Running daily job: {datetime.now()}\n")

    # Step 1 → Update Nifty
    update_market_data()

    # Step 2 → Send updates
    await send_updates()


if __name__ == "__main__":
    asyncio.run(main())

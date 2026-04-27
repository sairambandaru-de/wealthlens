"""
Daily cron job:
  1. Fetch and store Nifty
  2. Build portfolio snapshot per user
  3. Send daily message
"""

import asyncio
import os
import traceback
from datetime import datetime

from dotenv import load_dotenv
from telegram import Bot

from app.database import (
    get_connection,
    get_user_id,
    get_assets,
    set_user_inactive,
    save_portfolio_snapshot,
)
from app.services.analytics import build_daily_message
from app.services.market_service import fetch_nifty, store_index
from app.services.price_service import fetch_stock_price, fetch_mf_nav

load_dotenv()

TEST_MODE    = False #True #False
TEST_USER_ID = 1302442231

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("❌ TELEGRAM_BOT_TOKEN not found in .env")


# ─── Helpers ──────────────────────────────────────────────────────────────────

def get_all_users_id() -> list[int]:
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT telegram_id FROM users WHERE is_active = 1"
        ).fetchall()
        return [r[0] for r in rows if r[0]]
    finally:
        conn.close()


# ─── Step 1: Nifty ────────────────────────────────────────────────────────────

def update_market_data() -> dict | None:
    """Fetch Nifty, store in market_index, return data dict."""
    try:
        data = fetch_nifty()
        if not data:
            print("⚠️  Nifty fetch returned None")
            return None
        store_index(data)
        print(f"✅ Nifty stored: {data['close_value']} ({data['change_percent']:+.2f}%)")
        return data
    except Exception as e:
        print(f"❌ Nifty update failed: {e}")
        traceback.print_exc()
        return None


# ─── Step 2: Snapshot per user ────────────────────────────────────────────────

async def capture_snapshot(user_id: int, nifty_data: dict | None) -> dict | None:
    """
    Fetch live prices, compute totals, save snapshot.
    Returns enriched dict for build_daily_message or None if empty.
    """
    #from app.database import get_snapshot_n_days_ago
    from app.database import get_last_trading_snapshot
    from app.services.price_service import fetch_daily_stock_changes
    
    assets = get_assets(user_id)
    if not assets:
        return None

    total_invested      = 0.0
    total_current_value = 0.0
    stock_value         = 0.0
    stock_invested      = 0.0
    mf_value            = 0.0
    processed           = 0

    for a in assets:
        try:
            qty = float(a.get("quantity", 0))
            avg = float(a.get("avg_price", 0))
            if qty <= 0 or avg <= 0:
                continue

            symbol     = a["symbol"]
            asset_type = a["asset_type"]

            if asset_type == "stock":
                price = await fetch_stock_price(symbol)
            elif asset_type == "mf":
                price = await fetch_mf_nav(symbol)
            else:
                continue

            if not price or price <= 0:
                price = avg  # fallback: count invested at least

            current  = qty * price
            invested = qty * avg

            total_invested      += invested
            total_current_value += current

            if asset_type == "stock":
                stock_value    += current
                stock_invested += invested
            elif asset_type == "mf":
                mf_value += current

            processed += 1

        except Exception as e:
            print(f"⚠️  Skipping {a.get('symbol')}: {e}")
            continue

    if processed == 0 or total_invested == 0:
        return None

    total_pnl     = total_current_value - total_invested
    total_pnl_pct = (total_pnl / total_invested) * 100

    # ── Daily equity return vs yesterday's snapshot ───────────────────────────
    # Uses ratio-based delta so add/remove stocks don't distort the figure
    daily_equity_pct = None
    is_first_day     = True

    if stock_value > 0 and stock_invested > 0:
        yesterday = get_last_trading_snapshot(user_id)
        if yesterday and yesterday.get("stock_value", 0) > 0:
            is_first_day    = False
            prev_stock_val  = yesterday["stock_value"]
            prev_total_inv  = yesterday["total_invested"] or 1
            prev_total_cur  = yesterday["total_current_value"] or 1
            prev_stock_inv  = prev_total_inv * (prev_stock_val / prev_total_cur)
            today_ratio     = stock_value    / max(stock_invested, 1)
            yesterday_ratio = prev_stock_val / max(prev_stock_inv, 1)
            daily_equity_pct = (today_ratio - yesterday_ratio) * 100
        else:
            # First day — show overall return as fallback
            is_first_day     = True
            daily_equity_pct = ((stock_value - stock_invested) / stock_invested) * 100

    # ── Daily stock changes for movers ────────────────────────────────────────
    daily_changes = await fetch_daily_stock_changes(assets)
    # ── Nifty ─────────────────────────────────────────────────────────────────
    nifty_close      = nifty_data["close_value"]    if nifty_data else None
    nifty_change_pct = nifty_data["change_percent"] if nifty_data else None

    # ── Save snapshot ─────────────────────────────────────────────────────────
    save_portfolio_snapshot(
        user_id             = user_id,
        total_invested      = total_invested,
        total_current_value = total_current_value,
        total_pnl           = total_pnl,
        total_pnl_pct       = total_pnl_pct,
        stock_value         = stock_value,
        mf_value            = mf_value,
        nifty_close         = nifty_close,
        nifty_change_pct    = nifty_change_pct,
        asset_count         = processed,
    )

    return {
        "total_invested":      total_invested,
        "total_current_value": total_current_value,
        "total_pnl":           total_pnl,
        "total_pnl_pct":       total_pnl_pct,
        "stock_value":         stock_value,
        "stock_invested":      stock_invested,
        "mf_value":            mf_value,
        "has_mf":              mf_value > 0,
        "has_stocks":          stock_value > 0,
        "asset_count":         processed,
        "daily_equity_pct":    daily_equity_pct,
        "is_first_day":        is_first_day,        # ← new
        "daily_changes":       daily_changes,        # ← new
    }


# ─── Step 3: Send messages ────────────────────────────────────────────────────

async def send_updates(nifty_data: dict | None):
    bot  = Bot(token=BOT_TOKEN)
    users = get_all_users_id()

    if TEST_MODE:
        users = [u for u in users if u == TEST_USER_ID]
        print(f"🧪 Test mode → {len(users)} user")

    print(f"🚀 Sending to {len(users)} users")
    success = failed = 0

    for telegram_id in users:
        try:
            user_id = get_user_id(telegram_id)
            if not user_id:
                print(f"⚠️  No internal ID for {telegram_id}")
                continue

            # Build snapshot and message
            snapshot = await capture_snapshot(user_id, nifty_data)
            msg      = await build_daily_message(user_id, snapshot, nifty_data)

            await bot.send_message(chat_id=telegram_id, text=msg)
            success += 1
            await asyncio.sleep(0.1)   # Telegram rate limit

        except Exception as e:
            failed += 1
            err = str(e).lower()
            # User blocked bot or chat not found → mark inactive
            if any(k in err for k in ["blocked", "not found", "deactivated", "forbidden"]):
                try:
                    set_user_inactive(telegram_id)
                    print(f"⚠️  Marked inactive: {telegram_id}")
                except Exception:
                    pass
            else:
                print(f"❌ Failed for {telegram_id}: {e}")

    print(f"✅ Done → Success: {success} | Failed: {failed}")


# ─── Main ─────────────────────────────────────────────────────────────────────

from datetime import datetime

async def main():
    print(f"\n📅 Daily job started: {datetime.now()}\n")

    # ── Skip weekends — markets closed ───────────────────────────────────────
    today = datetime.now().weekday()  # 0=Mon ... 4=Fri, 5=Sat, 6=Sun
    is_weekend = today >= 5

    if is_weekend and not TEST_MODE:
        print("📅 Weekend — skipping daily update. No market today.")
        return

    if is_weekend and TEST_MODE:
        print("🧪 Test mode — running on weekend for testing.")

    # Step 1 → Update Nifty
    nifty_data = update_market_data()

    # Step 2 → Send updates
    await send_updates(nifty_data)


if __name__ == "__main__":
    asyncio.run(main())

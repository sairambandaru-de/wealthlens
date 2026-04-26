"""
Command handlers — one async function per /command.
"""

import logging
from app import database as db
from app.services import analytics, formatter
from app.services.telegram import send_plain
from app.services.price_service import fetch_stock_price, fetch_mf_nav, search_mf_schemes, get_mf_nav
import re
logger = logging.getLogger(__name__)

# ─── State machine for multi-step inputs ──────────────────────────────────────
# Stores pending state: {chat_id: {"step": str, "data": dict}}
_state: dict[int, dict] = {}


def _set_state(chat_id: int, step: str, data: dict = {}):
    _state[chat_id] = {"step": step, "data": data}


def _get_state(chat_id: int) -> dict | None:
    return _state.get(chat_id)


def _clear_state(chat_id: int):
    _state.pop(chat_id, None)


# ─── /start ───────────────────────────────────────────────────────────────────

async def cmd_start(chat_id: int, user: dict):
    db.upsert_user(user["id"], user.get("username"), user.get("first_name"))
    db.set_user_active(chat_id)
    name = user.get("first_name") or "there"

    await send_plain(chat_id, (
        f"👋 Welcome, {name}!\n\n"
        "📊 WealthLens — Portfolio Analytics\n\n"
        "Track your investments:\n"
        "• 📈 Stocks\n"
        "• 🏦 Mutual Funds\n"
        "• 💰 Profit & Loss\n\n"
        "⚡ What you can do:\n"
        "📥 Add Stock → /add_stock\n"
        "🏦 Add Mutual Fund → /add_mf\n"
        "❌ Remove Asset → /remove_asset\n"
        "📊 View Portfolio → /portfolio\n"
        "📁 View Holdings → /assets\n\n"
        "🔒 We do NOT collect your phone number or personal data.\n\n"
        "ℹ️ Analytics only. Not investment advice."
    ))

# ─── /add_stock ───────────────────────────────────────────────────────────────

async def cmd_add_stock(chat_id: int, user: dict):
    db.upsert_user(user["id"], user.get("username"), user.get("first_name"))
    _set_state(chat_id, "add_stock_symbol")
    await send_plain(chat_id,
        "📈 Add Stock\n\nEnter the stock ticker symbol (e.g., RELIANCE, TCS, INFY):")


async def _handle_add_stock(chat_id: int, text: str, state: dict):
    step = state["step"]
    data = state["data"]

    if step == "add_stock_symbol":
        symbol = text.strip().upper().replace(" ", "")
        await send_plain(chat_id, f"Fetching price for {symbol}...")
        price = await fetch_stock_price(symbol)
        if not price:
            await send_plain(chat_id,
                f"❌ Could not find price for '{symbol}'.\n"
                "Please check the NSE/BSE ticker symbol and try again.")
            _clear_state(chat_id)
            return
        _set_state(chat_id, "add_stock_qty", {"symbol": symbol, "market_price": price})
        await send_plain(chat_id,
            f"✅ {symbol} — Current price: ₹{price:.2f}\n\nEnter quantity (number of shares):")

    elif step == "add_stock_qty":
        try:
            qty = float(text.strip())
            assert qty > 0
        except (ValueError, AssertionError):
            await send_plain(chat_id, "❌ Invalid quantity. Please enter a positive number:")
            return
        data["quantity"] = qty
        _set_state(chat_id, "add_stock_price", data)
        await send_plain(chat_id,
            f"Enter your average buy price per share (₹):\n"
            f"(Current market price: ₹{data['market_price']:.2f})")

    elif step == "add_stock_price":
        try:
            avg_price = float(text.strip().replace(",", ""))
            assert avg_price > 0
        except (ValueError, AssertionError):
            await send_plain(chat_id, "❌ Invalid price. Please enter a positive number:")
            return

        user_id = db.get_user_id(chat_id)
        symbol = data["symbol"]
        ok = db.add_asset(user_id, "stock", symbol, symbol, data["quantity"], avg_price)
        _clear_state(chat_id)
        if ok:
            invested = data["quantity"] * avg_price
            await send_plain(
                chat_id,
                f"✅ Added {symbol} @ ₹{avg_price:,.0f}\n\n"
                f"---\n\n"
                f"⚡ Next:\n"
                f"• /add_stock\n"
                f"• /add_mf\n"
                f"• /portfolio"
                )
        else:
            await send_plain(chat_id, "❌ Failed to save asset. Please try again.")


# ─── /add_mf ──────────────────────────────────────────────────────────────────

async def cmd_add_mf(chat_id: int, user: dict):
    db.upsert_user(user["id"], user.get("username"), user.get("first_name"))
    _set_state(chat_id, "add_mf_search")
    await send_plain(chat_id,
        "🏦 Add Mutual Fund\n\nEnter fund name or AMFI scheme code to search:")


async def _handle_add_mf(chat_id: int, text: str, state: dict):
    step = state["step"]
    data = state["data"]

    # STEP 1: User enters "Parag Parikh"
    if step == "add_mf_search":
        query = text.strip()
        await send_plain(chat_id, f"🔍 Searching for '{query}'...")
        results = search_mf_schemes(query)
        #results = await search_mf_schemes(query) # Now returns ~5-8 results
        
        if not results:
            await send_plain(chat_id, "❌ No funds found. Try a different name (e.g. 'SBI Bluechip').")
            return

        # Build a numbered list
        msg = "Found these variants. Reply with the Number (1, 2, 3...):\n\n"
        for i, r in enumerate(results, 1):
            name = r.get("name", "")
            display_name = name.replace("Mutual Fund", "").strip()

            msg += f"{i}. {display_name}\n"
        # Save results in state 👇 IMPORTANT
        _set_state(chat_id, "add_mf_selection", {
                      "mf_results": results
                })
        await send_plain(chat_id, msg)

    # STEP 2: User enters "1" or "2"
    elif step == "add_mf_selection":
        selection = text.strip()

        results = data.get("mf_results", [])

        if not results:
            await send_plain(chat_id, "⚠️ Session expired. Please search again.")
            _set_state(chat_id, "add_mf_search")
            return

        try:
            idx = int(selection) - 1

            if idx < 0 or idx >= len(results):
                raise ValueError

            selected_fund = results[idx]

        except (ValueError, IndexError):
            await send_plain(chat_id, f"❌ Invalid choice. Enter number 1 to {len(results)}")
            return

        # ✅ SAFE EXTRACTION
        code = selected_fund.get("code")
        name = selected_fund.get("name")

        if not code or not name:
            await send_plain(chat_id, "❌ Something went wrong. Try again.")
            return

        # ✅ GET NAV FROM CACHE
        nav = get_mf_nav(code)
        if nav is None:
            await send_plain(chat_id, "❌ NAV not available. Try again later.")
            return

        # 👉 Move to next step (units input)
        _set_state(chat_id, "add_mf_units", {
            "scheme_code": code,
            "name": name,
            "nav": nav
            })

        await send_plain(
            chat_id,
            f"✅ Selected: {name}\n"
            f"💰 NAV: ₹{nav:,.2f}\n\n"
            f"Enter units:"
        )
    # STEP 3: User enters Units
    elif step == "add_mf_units":
        try:
            units = float(text.strip())
            if units <= 0: raise ValueError
        except ValueError:
            await send_plain(chat_id, "❌ Please enter a valid number for units:")
            return
            
        data["units"] = units
        _set_state(chat_id, "add_mf_avg_nav", data)
        await send_plain(chat_id, f"Enter your average purchase NAV (₹):\n(Current: ₹{data['nav']:.4f})")

    # STEP 4: User enters Buy NAV
    elif step == "add_mf_avg_nav":
        try:
            avg_nav = float(text.strip().replace(",", ""))
            if avg_nav <= 0: raise ValueError
        except ValueError:
            await send_plain(chat_id, "❌ Please enter a valid purchase NAV:")
            return

        user_id = db.get_user_id(chat_id)
        ok = db.add_asset(user_id, "mf", data["scheme_code"], data["name"], data["units"], avg_nav)
        
        if ok:
            invested = data["units"] * avg_nav
            await send_plain(
                chat_id,
                f"✅ Added {data['name']} @ ₹{avg_nav:,.2f}\n\n"
                f"---\n\n"
                f"⚡ Next:\n"
                f"• /add_stock\n"
                f"• /add_mf\n"
                f"• /portfolio"
            )
        else:
            await send_plain(chat_id, "❌ Database error.")
        _clear_state(chat_id)

# ─── /remove_asset ────────────────────────────────────────────────────────────

async def cmd_remove_asset(update, context):
    chat_id = update.effective_chat.id
    user = update.effective_user

    # Save user
    db.upsert_user(
        user.id,
        user.username,
        user.first_name
    )

    assets = db.get_assets(user.id)

    if not assets:
        await send_plain(chat_id, "📭 No assets to remove.")
        return

    _set_state(chat_id, "remove_asset", {"assets": assets})

    msg = "Select asset to remove:\n\n"

    for i, a in enumerate(assets, 1):
        name = a.get("name") or a.get("symbol")
        msg += f"{i}. {name}\n"

    await send_plain(chat_id, msg)


async def _handle_remove_asset(chat_id: int, text: str):
    symbol = text.strip().upper()
    user_id = db.get_user_id(chat_id)
    removed = db.remove_asset(user_id, symbol)
    _clear_state(chat_id)
    if removed:
        await send_plain(chat_id, f"✅ Removed {symbol} from your portfolio.")
    else:
        await send_plain(chat_id, f"❌ '{symbol}' not found in your portfolio.")

async def cmd_remove_asset(update, context):
    chat_id = update.effective_chat.id
    user = update.effective_user

    # ✅ Correct user save
    db.upsert_user(
        user.id,
        user.username,
        user.first_name
    )

    # ✅ IMPORTANT: get internal DB user_id
    user_id = db.get_user_id(chat_id)

    assets = db.get_assets(user_id)

    if not assets:
        await send_plain(chat_id, "📭 No assets to remove.")
        return

    _set_state(chat_id, "remove_asset", {"assets": assets})

    msg = "Select asset to remove:\n\n"

    for i, a in enumerate(assets, 1):
        name = a.get("name") or a.get("symbol")
        msg += f"{i}. {name}\n"

    await send_plain(chat_id, msg)

# ─── /assets ──────────────────────────────────────────────────────────────────

async def cmd_assets(chat_id: int):
    user_id = db.get_user_id(chat_id)

    if not user_id:
        await send_plain(chat_id, "Please /start first.")
        return

    assets = db.get_assets(user_id)

    if not assets:
        await send_plain(
            chat_id,
            "📂 Your assets list is empty\n\n"
            "➕ Add assets:\n"
            "• /add_stock\n"
            "• /add_mf"
        )
        return

    msg_lines = ["📂 Your Assets\n"]

    # Separate asset types
    stocks = [a for a in assets if a.get("asset_type") == "stock"]
    mfs = [a for a in assets if a.get("asset_type") == "mf"]

    # 📈 Stocks
    if stocks:
        msg_lines.append("📈 Stocks:")
        for a in stocks:
            symbol = a.get("symbol")
            name = a.get("name")

            display_name = symbol if not name or name == symbol else f"{symbol} — {name[:30]}"
            msg_lines.append(
                f"• {display_name}\n"
                f"  Qty: {round(a['quantity'], 2)} | Avg: ₹{round(a['avg_price'], 2)}"
            )

    # 🏦 Mutual Funds
    if mfs:
        msg_lines.append("\n🏦 Mutual Funds:")

        for a in mfs:
            name = a.get("name") or a.get("symbol")

            # Clean name
            clean_name = name.lower()
            clean_name = re.sub(r"(direct plan|regular plan|growth|idcw)", "", clean_name)
            clean_name = re.sub(r"[-–]+", " ", clean_name)
            clean_name = re.sub(r"\s+", " ", clean_name).strip()
            clean_name = clean_name.title()

            msg_lines.append(
                f"• {clean_name[:35]}\n"
                f"  Units: {round(a['quantity'], 2)} | Avg NAV: ₹{round(a['avg_price'], 2)}"
            )

    # Total
    msg_lines.append(f"\n📊 Total assets: {len(assets)}")

    # 👉 Add footer (IMPORTANT)
    msg_lines.append("\n---\n")
    msg_lines.append(
        "⚡ Next:\n"
        "• /add_stock\n"
        "• /add_mf\n"
        "• /portfolio"
    )

    await send_plain(chat_id, "\n".join(msg_lines))


async def cmd_assets_bkp(chat_id: int):
    user_id = db.get_user_id(chat_id)

    if not user_id:
        await send_plain(chat_id, "Please /start first.")
        return

    assets = db.get_assets(user_id)

    if not assets:
        await send_plain(chat_id, "📭 Portfolio is empty. Use /add_stock or /add_mf.")
        return

    msg_lines = ["📂 Your Assets\n"]

    # Separate asset types
    stocks = [a for a in assets if a.get("asset_type") == "stock"]
    mfs = [a for a in assets if a.get("asset_type") == "mf"]

    # 📈 Stocks
    if stocks:
        msg_lines.append("📈 Stocks:")
        for a in stocks:
            symbol = a.get("symbol")
            name = a.get("name")

            display_name = symbol if not name or name == symbol else f"{symbol} — {name[:30]}"
            msg_lines.append(
                f"• {display_name}\n"
                f"  Qty: {round(a['quantity'], 2)} | Avg: ₹{round(a['avg_price'], 2)}"
            )
    # 🏦 Mutual Funds
    if mfs:
        msg_lines.append("\n🏦 Mutual Funds:")

        for a in mfs:
            name = a.get("name") or a.get("symbol")

            # ✅ Advanced clean
            clean_name = name.lower()

            # Remove keywords
            clean_name = re.sub(r"(direct plan|regular plan|growth|idcw)", "", clean_name)

            # Remove hyphens and extra symbols
            clean_name = re.sub(r"[-–]+", " ", clean_name)

            # Remove extra spaces
            clean_name = re.sub(r"\s+", " ", clean_name).strip()

            # Title case (clean UI)
            clean_name = clean_name.title()

            msg_lines.append(
                f"• {clean_name[:35]}\n"
                f"  Units: {round(a['quantity'], 2)} | Avg NAV: ₹{round(a['avg_price'], 2)}"
                )
    msg_lines.append(f"\nTotal assets: {len(assets)}")

    await send_plain(chat_id, "\n".join(msg_lines))

# ─── /portfolio ───────────────────────────────────────────────────────────────

async def cmd_portfolio(chat_id: int):
    user_id = db.get_user_id(chat_id)
    if not user_id:
        await send_plain(chat_id, "Please /start first.")
        return
    await send_plain(chat_id, "⏳ Fetching live prices...")
    portfolio = await analytics.build_portfolio(user_id)
    msg = formatter.build_portfolio_message(portfolio)
    await send_plain(chat_id, msg)


# ─── /allocation ──────────────────────────────────────────────────────────────

async def cmd_allocation(chat_id: int):
    user_id = db.get_user_id(chat_id)
    if not user_id:
        await send_plain(chat_id, "Please /start first.")
        return
    await send_plain(chat_id, "⏳ Calculating allocation...")
    portfolio = await analytics.build_portfolio(user_id)
    alloc = analytics.allocation_breakdown(portfolio)
    await send_message(chat_id, formatter.build_allocation_message(alloc))


# ─── /exposure ────────────────────────────────────────────────────────────────

async def cmd_exposure(chat_id: int):
    user_id = db.get_user_id(chat_id)
    if not user_id:
        await send_plain(chat_id, "Please /start first.")
        return
    portfolio = await analytics.build_portfolio(user_id)
    exposure = analytics.sector_exposure(portfolio)
    await send_message(chat_id, formatter.build_exposure_message(exposure))


# ─── /top ─────────────────────────────────────────────────────────────────────

async def cmd_top(chat_id: int):
    user_id = db.get_user_id(chat_id)
    if not user_id:
        await send_plain(chat_id, "Please /start first.")
        return
    await send_plain(chat_id, "⏳ Analysing...")
    portfolio = await analytics.build_portfolio(user_id)
    performers = analytics.top_performers(portfolio)
    await send_message(chat_id, formatter.build_performers_message(performers, "🏆 Top Performers"))


# ─── /bottom ──────────────────────────────────────────────────────────────────

async def cmd_bottom(chat_id: int):
    user_id = db.get_user_id(chat_id)
    if not user_id:
        await send_plain(chat_id, "Please /start first.")
        return
    await send_plain(chat_id, "⏳ Analysing...")
    portfolio = await analytics.build_portfolio(user_id)
    performers = analytics.bottom_performers(portfolio)
    await send_message(chat_id, formatter.build_performers_message(performers, "📉 Bottom Performers"))


# ─── /compare ─────────────────────────────────────────────────────────────────

async def cmd_compare(chat_id: int, args: str):
    """Usage: /compare RELIANCE TCS INFY"""
    user_id = db.get_user_id(chat_id)
    if not user_id:
        await send_plain(chat_id, "Please /start first.")
        return

    symbols = [s.upper() for s in args.split() if s]
    if not symbols:
        await send_plain(chat_id,
            "Usage: /compare SYMBOL1 SYMBOL2 ...\nExample: /compare RELIANCE TCS")
        return

    await send_plain(chat_id, "⏳ Fetching comparison data...")
    portfolio = await analytics.build_portfolio(user_id)
    matched = [a for a in portfolio["assets"] if a["symbol"] in symbols]
    await send_message(chat_id, formatter.build_compare_message(matched))


# ─── Message dispatcher ───────────────────────────────────────────────────────

async def handle_text(chat_id: int, text: str, user: dict):
    """Route free-text messages through the state machine."""
    state = _get_state(chat_id)
    if not state:
        await send_plain(chat_id, "Use /start to see available commands.")
        return

    step = state["step"]
    if step.startswith("add_stock"):
        await _handle_add_stock(chat_id, text, state)
    elif step.startswith("add_mf"):
        await _handle_add_mf(chat_id, text, state)
    elif step.startswith("remove_asset"):
        assets = state["data"]["assets"]

        if not text.isdigit():
            await send_plain(chat_id, "❌ Enter a valid number.")
            return

        idx = int(text) - 1

        if idx < 0 or idx >= len(assets):
            await send_plain(chat_id, "❌ Invalid selection.")
            return

        selected = assets[idx]
        user_id = db.get_user_id(chat_id)
        ok = db.remove_asset(
            user_id=user_id,
            symbol=selected["symbol"],
            asset_type=selected["asset_type"]
            )

        if ok:
            name = selected.get("name") or selected.get("symbol")
            await send_plain(chat_id, f"✅ Removed {name}")
        else:
            await send_plain(chat_id, "❌ Failed to remove asset.")

        _clear_state(chat_id)
        return
    else:
        _clear_state(chat_id)
        await send_plain(chat_id, "Something went wrong. Please start over.")

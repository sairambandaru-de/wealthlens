"""
Command handlers — one async function per /command.
"""

import logging
from app import database as db
from app.services import analytics, formatter
from app.services.telegram import send_message, send_plain
from app.services.price_service import fetch_stock_price, fetch_mf_nav, search_mf_schemes

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
    name = user.get("first_name") or "there"
    await send_message(chat_id, (
        f"👋 *Welcome, {formatter.esc(name)}\\!*\n\n"
        "I'm your personal *Portfolio Analytics Bot*\\. "
        "Track stocks and mutual funds, view P&L, allocation, and more\\.\n\n"
        "*Commands:*\n"
        "/add\\_stock — Add a stock holding\n"
        "/add\\_mf — Add a mutual fund holding\n"
        "/remove\\_asset — Remove an asset\n"
        "/assets — List all your assets\n"
        "/portfolio — Full portfolio with P&L\n"
        "/allocation — Allocation breakdown\n"
        "/exposure — Asset class exposure\n"
        "/top — Top 3 performers\n"
        "/bottom — Bottom 3 performers\n"
        "/compare — Compare specific assets\n\n"
        "_Note: This bot provides analytics only, not investment advice\\._"
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
        symbol = text.strip().upper()
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
            await send_plain(chat_id,
                f"✅ Added {data['quantity']} shares of {symbol} @ ₹{avg_price:.2f}\n"
                f"Total invested: ₹{invested:,.2f}")
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
        
        results = await search_mf_schemes(query) # Now returns ~5-8 results
        
        if not results:
            await send_plain(chat_id, "❌ No funds found. Try a different name (e.g. 'SBI Bluechip').")
            return

        # Build a numbered list
        msg = "Found these variants. Reply with the Number (1, 2, 3...):\n\n"

        for i, r in enumerate(results, 1):
            display_name = r['name'].replace("Mutual Fund", "").strip()
            msg += f"{i}. {display_name}\n   NAV: ₹{r['nav']:.2f}\n\n"

        # Save results in state 👇 IMPORTANT
        _set_state(chat_id, "add_mf_selection", {
        "search_results": results
        })

        await send_plain(chat_id, msg)

    # STEP 2: User enters "1" or "2"
    elif step == "add_mf_selection":
        selection = text.strip()
        search_results = data.get("search_results", [])
        if not search_results:
            await send_plain(chat_id, "⚠️ Session expired. Please search again.")
            _set_state(chat_id, "add_mf_search")
            return
        try:
            idx = int(selection) - 1
            if idx < 0 or idx >= len(search_results):
                raise ValueError
            selected_fund = search_results[idx]
        except (ValueError, IndexError):
            await send_plain(chat_id, f"❌ Invalid choice. Please enter a number between 1 and {len(search_results)}:")
            return

        # Map selection to actual AMFI data
        _set_state(chat_id, "add_mf_units", {
            "scheme_code": selected_fund["code"], 
            "name": selected_fund["name"], 
            "nav": selected_fund["nav"]
        })
        
        await send_plain(chat_id, 
            f"✅ Selected: {selected_fund['name']}\n"
            f"Current NAV: ₹{selected_fund['nav']:.4f}\n\n"
            f"How many units do you hold?")

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
            await send_plain(chat_id, f"✅ Successfully added to portfolio!")
        else:
            await send_plain(chat_id, "❌ Database error.")
        _clear_state(chat_id)

# ─── /remove_asset ────────────────────────────────────────────────────────────

async def cmd_remove_asset(chat_id: int, user: dict):
    user_id = db.get_user_id(chat_id)
    if not user_id:
        await send_plain(chat_id, "Please /start first.")
        return
    assets = db.get_assets(user_id)
    if not assets:
        await send_plain(chat_id, "📭 No assets to remove.")
        return
    msg = "Enter the symbol/code to remove:\n\n"
    for a in assets:
        tag = "📈" if a["asset_type"] == "stock" else "🏦"
        msg += f"{tag} {a['symbol']} — {a['name'][:35]}\n"
    _set_state(chat_id, "remove_asset")
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


# ─── /assets ──────────────────────────────────────────────────────────────────

async def cmd_assets(chat_id: int):
    user_id = db.get_user_id(chat_id)
    if not user_id:
        await send_plain(chat_id, "Please /start first.")
        return
    assets = db.get_assets(user_id)
    if not assets:
        await send_plain(chat_id, "📭 Portfolio is empty. Use /add_stock or /add_mf.")
        return

    lines = ["*📋 Your Assets*\n"]
    stocks = [a for a in assets if a["asset_type"] == "stock"]
    mfs = [a for a in assets if a["asset_type"] == "mf"]

    if stocks:
        lines.append("*📈 Stocks:*")
        for a in stocks:
            lines.append(
                f"  • {formatter.esc(a['symbol'])} — {formatter.esc(a['name'][:30])}\n"
                f"    Qty: {formatter.esc(str(a['quantity']))} \\| Avg: {formatter.esc(formatter.fmt_currency(a['avg_price']))}"
            )
    if mfs:
        lines.append("\n*🏦 Mutual Funds:*")
        for a in mfs:
            lines.append(
                f"  • {formatter.esc(a['symbol'])} — {formatter.esc(a['name'][:30])}\n"
                f"    Units: {formatter.esc(str(a['quantity']))} \\| Avg NAV: {formatter.esc(formatter.fmt_currency(a['avg_price']))}"
            )

    lines.append(f"\n_Total assets: {len(assets)}_")
    await send_message(chat_id, "\n".join(lines))


# ─── /portfolio ───────────────────────────────────────────────────────────────

async def cmd_portfolio(chat_id: int):
    user_id = db.get_user_id(chat_id)
    if not user_id:
        await send_plain(chat_id, "Please /start first.")
        return
    await send_plain(chat_id, "⏳ Fetching live prices...")
    portfolio = await analytics.build_portfolio(user_id)
    msg = formatter.build_portfolio_message(portfolio)
    await send_message(chat_id, msg)


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
    elif step == "remove_asset":
        await _handle_remove_asset(chat_id, text)
    else:
        _clear_state(chat_id)
        await send_plain(chat_id, "Something went wrong. Please start over.")

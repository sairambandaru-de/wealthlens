"""
Portfolio analytics: current value, P&L, allocation, exposure, top/bottom performers.
"""

import asyncio
import logging
from app.services.price_service import get_price, fetch_stock_price, fetch_mf_nav, fetch_nifty_price
from app.services.market_service import get_latest_nifty
from app.services.formatter import fmt_currency, fmt_pnl
from app.database import get_user_nifty_base, set_user_nifty_base,get_assets
import math

logger = logging.getLogger(__name__)


async def build_daily_message(
    user_id: int,
    snapshot: dict | None,
    nifty_data: dict | None,
) -> str:

    if not snapshot:
        return (
            "📭 No portfolio found\n\n"
            "Start tracking:\n"
            "• /add_stock\n"
            "• /add_mf"
        )

    total_current    = snapshot["total_current_value"]
    total_invested   = snapshot["total_invested"]
    total_pnl        = snapshot["total_pnl"]
    total_pnl_pct    = snapshot["total_pnl_pct"]
    stock_value      = snapshot.get("stock_value", 0.0)
    mf_value         = snapshot.get("mf_value", 0.0)
    has_mf           = snapshot.get("has_mf", False)
    has_stocks       = snapshot.get("has_stocks", False)
    equity_pct       = snapshot.get("daily_equity_pct")
    is_first_day     = snapshot.get("is_first_day", False)
    daily_changes    = snapshot.get("daily_changes", {})
    nifty_pct        = nifty_data["change_percent"] if nifty_data else None

    # ── Alpha ─────────────────────────────────────────────────────────────────
    alpha = None
    if equity_pct is not None and nifty_pct is not None and not is_first_day:
        alpha = equity_pct - nifty_pct
    
    def alpha_label(alpha: float, equity_pct: float) -> str:
        if alpha > 0.5:
            return "You beat the market 🎯" if equity_pct >= 0 else "You lost less than market"
        elif alpha >= -0.5:
            return "Matched the market"
        else:
            return "Market outperformed your equity"

    # ── Formatters ────────────────────────────────────────────────────────────
    def fmt_inr(x: float) -> str:
        if abs(x) >= 1_00_00_000:
            return f"₹{x / 1_00_00_000:.2f}Cr"
        elif abs(x) >= 1_00_000:
            return f"₹{x / 1_00_000:.2f}L"
        return f"₹{x:,.0f}"

    def fmt_pnl_line(pnl: float, pct: float) -> str:
        dot  = "🟢" if pnl >= 0 else "🔴"
        sign = "+" if pnl >= 0 else "-"
        return f"📈 {dot} {sign}{fmt_inr(abs(pnl))} ({sign}{abs(pct):.2f}%)"

    def fmt_pct_line(pct: float | None, label: str, icon: str) -> str:
        if pct is None:
            return f"{icon} {label}  ⚪ N/A"
        dot  = "🟢" if pct >= 0 else "🔴"
        sign = "+" if pct >= 0 else ""
        return f"{icon} {label}  {dot} {sign}{pct:.2f}%"

    def fmt_alpha_line(alpha: float) -> str:
        dot  = "🟢" if alpha >= 0 else "🔴"
        sign = "+" if alpha >= 0 else ""
        return f"🔥 Alpha  {dot} {sign}{alpha:.2f}%"

    def fmt_mover(symbol: str, pct: float) -> str:
        dot  = "🟢" if pct >= 0 else "🔴"
        sign = "+" if pct >= 0 else ""
        return f"  {symbol:<12} {dot} {sign}{pct:.2f}%"

    # ── Build message ─────────────────────────────────────────────────────────
    lines = [
        "📊 Daily Portfolio Update",
        "",
        f"💼 {fmt_inr(total_current)}",
        f"💰 {fmt_inr(total_invested)}",
        fmt_pnl_line(total_pnl, total_pnl_pct),
    ]

    # Breakdown
    breakdown = []
    if has_mf:
        breakdown.append(f"🏦 MF: {fmt_inr(mf_value)}")
    if has_stocks:
        breakdown.append(f"📈 Stocks: {fmt_inr(stock_value)}")
    if breakdown:
        lines.append("   ".join(breakdown))

    lines.append("")

    # Nifty
    from datetime import date
    is_weekend = date.today().weekday() >= 5
    nifty_label = "Nifty (Fri)" if is_weekend else "Nifty "
    lines.append(fmt_pct_line(nifty_pct, nifty_label, "📊"))

    # Equity
    if has_stocks:
        if is_first_day and equity_pct is not None:
            dot  = "🟢" if equity_pct >= 0 else "🔴"
            sign = "+" if equity_pct >= 0 else ""
            lines.append(f"📉 Equity  {dot} {sign}{equity_pct:.2f}% (since entry)")
            lines.append("   ⚡ Daily % available from tomorrow")
        else:
            lines.append(fmt_pct_line(equity_pct, "Equity", "📉"))
            
    # Alpha
    if alpha is not None:
        lines.append(fmt_alpha_line(alpha))
        lines.append(alpha_label(alpha, equity_pct))

    # ── Movers section ────────────────────────────────────────────────────────
    if has_stocks:
        movers = get_top_bottom_performers(daily_changes)

        lines.append("")
        lines.append("🏆 Today's Movers")

        if movers["no_stocks"] or movers["no_data"]:
            lines.append("  ⚠️ Price data unavailable")

        elif movers["all_zero"]:
            lines.append("  ⚪ No movement today (holiday?)")

        elif movers["single"]:
            # Only one stock — show it once
            entry = movers["top"][0]
            lines.append(fmt_mover(entry["symbol"], entry["pct"]))

        else:
            # Top performers
            lines.append("📈 Top")
            for e in movers["top"]:
                lines.append(fmt_mover(e["symbol"], e["pct"]))

            # Bottom performers — skip if same group as top (all tied)
            if movers["bottom"]:
                lines.append("📉 Bottom")
                for e in movers["bottom"]:
                    lines.append(fmt_mover(e["symbol"], e["pct"]))

        # Skipped note
        if movers.get("skipped", 0) > 0:
            lines.append(f"  ℹ️ {movers['skipped']} stock(s) price unavailable")

    # MF note
    if has_mf:
        lines.append("")
        lines.append("ℹ️ MF values based on latest NAV")

    lines += [
        "---",
        "⚡ /add_stock  ➕ /add_mf",
        "📊 /portfolio  📁 /assets",
    ]

    return "\n".join(lines)


async def build_daily_message_1(
    user_id: int,
    snapshot: dict | None,
    nifty_data: dict | None,
) -> str:
    """
    Builds the daily Telegram message from pre-computed snapshot.

    Cases handled:
      - Empty portfolio
      - MF only (no equity line, no alpha)
      - Stocks only
      - Mixed MF + Stocks
      - Nifty fetch failed
      - First day (no yesterday snapshot → equity daily pct = None)
      - All positive / all negative / mixed directions
    """

    # ── Case: empty portfolio ─────────────────────────────────────────────────
    if not snapshot:
        return (
            "📭 No portfolio found\n\n"
            "Start tracking:\n"
            "• /add_stock\n"
            "• /add_mf"
        )

    total_current  = snapshot["total_current_value"]
    total_invested = snapshot["total_invested"]
    total_pnl      = snapshot["total_pnl"]
    total_pnl_pct  = snapshot["total_pnl_pct"]
    stock_value    = snapshot.get("stock_value", 0.0)
    mf_value       = snapshot.get("mf_value", 0.0)
    has_mf         = snapshot.get("has_mf", False)
    has_stocks     = snapshot.get("has_stocks", False)

    # daily equity % — None on first day or MF-only
    equity_pct     = snapshot.get("daily_equity_pct")   # may be None

    # Nifty — may be None if fetch failed
    nifty_pct      = nifty_data["change_percent"] if nifty_data else None

    # ── Alpha: only when both equity and nifty are available ─────────────────
    alpha = None
    if equity_pct is not None and nifty_pct is not None:
        alpha = equity_pct - nifty_pct

    # ── Alpha message — covers all sign combinations ──────────────────────────
    def alpha_label(alpha: float, equity_pct: float, nifty_pct: float) -> str:
        if alpha > 0.5:
            if equity_pct >= 0:
                return "You beat the market 🎯"
            else:
                return "You lost less than market"   # both red, you better
        elif alpha >= -0.5:
            return "Matched the market"
        else:
            return "Market outperformed your equity"  # you lagged

    # ── Formatters ────────────────────────────────────────────────────────────
    def fmt_inr(x: float) -> str:
        if abs(x) >= 1_00_00_000:
            return f"₹{x / 1_00_00_000:.2f}Cr"
        elif abs(x) >= 1_00_000:
            return f"₹{x / 1_00_000:.2f}L"
        return f"₹{x:,.0f}"

    def fmt_pnl_line(pnl: float, pct: float) -> str:
        dot  = "🟢" if pnl >= 0 else "🔴"
        sign = "+" if pnl >= 0 else "-"
        return f"📈 {dot} {sign}{fmt_inr(abs(pnl))} ({sign}{abs(pct):.2f}%)"

    def fmt_pct_line(pct: float | None, label: str, icon: str) -> str:
        if pct is None:
            return f"{icon} {label}  ⚪ N/A"
        dot  = "🟢" if pct >= 0 else "🔴"
        sign = "+" if pct >= 0 else ""
        return f"{icon} {label}  {dot} {sign}{pct:.2f}%"

    def fmt_alpha_line(alpha: float) -> str:
        dot  = "🟢" if alpha >= 0 else "🔴"
        sign = "+" if alpha >= 0 else ""
        return f"🔥 Alpha  {dot} {sign}{alpha:.2f}%"

    # ── Build message ─────────────────────────────────────────────────────────
    lines = [
        "📊 Daily Portfolio Update",
        "",
        f"💼 {fmt_inr(total_current)}",
        f"💰 {fmt_inr(total_invested)}",
        fmt_pnl_line(total_pnl, total_pnl_pct),
    ]

    # Breakdown: MF + Stocks — only show what exists
    breakdown = []
    if has_mf:
        breakdown.append(f"🏦 MF: {fmt_inr(mf_value)}")
    if has_stocks:
        breakdown.append(f"📈 Stocks: {fmt_inr(stock_value)}")
    if breakdown:
        lines.append("   ".join(breakdown))

    lines.append("")

    # Nifty — always show (N/A if failed)
    lines.append(fmt_pct_line(nifty_pct, "Nifty ", "📊"))

    # Equity — only show if user has stocks
    # If first day (equity_pct None) still show N/A so user knows it's coming
    if has_stocks:
        lines.append(fmt_pct_line(equity_pct, "Equity", "📉"))

    # Alpha — only when both equity and nifty available
    if alpha is not None:
        lines.append(fmt_alpha_line(alpha))
        lines.append(alpha_label(alpha, equity_pct, nifty_pct))

    # MF note
    if has_mf:
        lines.append("")
        lines.append("ℹ️ MF values based on latest NAV")

    lines += [
        "---",
        "⚡ /add_stock  ➕ /add_mf",
        "📊 /portfolio  📁 /assets",
    ]

    return "\n".join(lines)



async def build_daily_message_bkp(user_id: int) -> str:

    assets = get_assets(user_id)

    # -----------------------------
    # 1. Empty portfolio
    # -----------------------------
    if not assets:
        return (
            "📭 No portfolio found\n\n"
            "Start by adding assets:\n"
            "• /add_stock\n"
            "• /add_mf"
        )

    total_current = 0.0
    total_invested = 0.0

    stock_value = 0.0
    stock_invested = 0.0

    processed_assets = 0

    # -----------------------------
    # 2. Process assets safely
    # -----------------------------
    for a in assets:
        try:
            qty = float(a.get("quantity", 0))
            avg = float(a.get("avg_price", 0))
            symbol = a.get("symbol")
            asset_type = a.get("asset_type")

            # Validation
            if qty <= 0 or avg <= 0 or not symbol:
                continue

            price = None

            # STOCK
            if asset_type == "stock":
                price = await fetch_stock_price(symbol)

            # MF
            elif asset_type == "mf":
                price = await fetch_mf_nav(symbol)

            # Skip if price invalid
            if price is None or price <= 0:
                continue

            current = qty * price
            invested = qty * avg

            total_current += current
            total_invested += invested
            processed_assets += 1

            if asset_type == "stock":
                stock_value += current
                stock_invested += invested

        except Exception:
            # Skip problematic asset (don’t break whole message)
            continue

    # -----------------------------
    # 3. If nothing processed
    # -----------------------------
    if processed_assets == 0:
        return (
            "⚠️ Unable to fetch latest prices\n\n"
            "Please try again later"
        )

    # -----------------------------
    # 4. Calculations
    # -----------------------------
    total_pnl = total_current - total_invested
    total_pnl_pct = (
        (total_pnl / total_invested) * 100 if total_invested > 0 else 0
    )

    # -----------------------------
    # 5. Fetch Nifty
    # -----------------------------
    nifty_change = get_latest_nifty()

    # -----------------------------
    # 6. Format helpers
    # -----------------------------
    def fmt_rupee(x):
        return f"₹{x:,.0f}"

    def fmt_pnl(pnl, pct):
        sign = "+" if pnl >= 0 else "-"
        return f"{sign}{fmt_rupee(abs(pnl))} ({sign}{abs(pct):.2f}%)"
    
    

    def fmt_nifty(nifty):
        # Handle None
        if nifty is None:
            return "📊 Nifty 50: NA"

        # Safe conversion to float
        try:
            nifty = float(nifty)
        except (TypeError, ValueError):
            return "📊 Nifty 50: NA"

        # Handle invalid numbers (NaN / infinity)
        if math.isnan(nifty) or math.isinf(nifty):
            return "📊 Nifty 50: NA"

        # Determine color
        if nifty > 0:
            color = "🟢"
            sign = "+"
        elif nifty < 0:
            color = "🔴"
            sign = ""
        else:
            color = "⚪"   # neutral case
            sign = ""

        return f"📊 Nifty 50: {color} {sign}{nifty:.2f}%"

    def fmt_pct(x):
        if x is None:
            return "NA"
        sign = "+" if x >= 0 else ""
        return f"{sign}{x:.2f}%"

    has_mf = any(a.get("asset_type") == "mf" for a in assets)

    # -----------------------------
    # 7. Build message
    # -----------------------------
    msg = (
        f"📊 Daily Portfolio Update\n\n"
        f"💼 {fmt_rupee(total_current)}\n"
        f"💰 Invested: {fmt_rupee(total_invested)}\n"
        f"📈 {fmt_pnl(total_pnl, total_pnl_pct)}"
    )

    # Add Nifty
    #msg += f"\n📊 Nifty 50: {fmt_pct(nifty_change)}"
    msg += f"\n{fmt_nifty(nifty_change)}"
    # MF note
    if has_mf:
        msg += "\n\nℹ️ MF values use latest NAV"

    # Footer (cleaner UX)
    msg += (
        "\n\n---\n"
        "➕ /add_stock  ➕ /add_mf\n"
        "📊 /portfolio"
    )

    return msg

async def build_daily_message_1(user_id: int) -> str:
    assets = get_assets(user_id)

    if not assets:
        return (
            "📭 No portfolio data.\n\n"
            "➕ Add assets:\n"
            "• /add_stock\n"
            "• /add_mf"
        )

    total_current = 0.0
    total_invested = 0.0

    stock_value = 0.0
    stock_invested = 0.0

    # 👉 Loop through assets
    for a in assets:
        qty = a["quantity"]
        avg = a["avg_price"]
        symbol = a["symbol"]

        price = None

        # STOCK
        if a["asset_type"] == "stock":
            price = await fetch_stock_price(symbol)

        # MF
        elif a["asset_type"] == "mf":
            price = await fetch_mf_nav(symbol)

        if price is None:
            continue

        current = qty * price
        invested = qty * avg

        total_current += current
        total_invested += invested

        if a["asset_type"] == "stock":
            stock_value += current
            stock_invested += invested

    # 👉 Totals
    total_pnl = total_current - total_invested
    total_pnl_pct = (total_pnl / total_invested * 100) if total_invested else 0

    # 👉 Format helpers
    def fmt_rupee(x):
        return f"₹{x:,.0f}"

    def fmt_pnl(pnl, pct):
        sign = "+" if pnl >= 0 else "-"
        return f"{sign}{fmt_rupee(abs(pnl))} ({sign}{abs(pct):.2f}%)"

    # 👉 MF presence check (UX improvement)
    has_mf = any(a["asset_type"] == "mf" for a in assets)

    # 👉 Build message
    msg = (
        f"📊 WealthLens Daily Update\n\n"
        f"💼 Portfolio Value: {fmt_rupee(total_current)}\n"
        f"💰 Invested: {fmt_rupee(total_invested)}\n"
        f"📈 Total P&L: {fmt_pnl(total_pnl, total_pnl_pct)}"
    )

    if has_mf:
        msg += "\n\nℹ️ MF values use latest NAV (updated once daily)"

    msg += (
        "\n\n---\n\n"
        "⚡ Next:\n"
        "• /add_stock\n"
        "• /add_mf\n"
        "• /portfolio"
    )

    return msg


async def build_daily_message_1(user_id: int) -> str:
    assets = get_assets(user_id)

    if not assets:
        return (
            "📭 No portfolio data.\n\n"
            "➕ Add assets:\n"
            "• /add_stock\n"
            "• /add_mf"
        )

    total_current = 0
    total_invested = 0

    stock_value = 0
    stock_invested = 0

    # 👉 Loop through assets
    for a in assets:
        qty = a["quantity"]
        avg = a["avg_price"]
        symbol = a["symbol"]

        # STOCK
        if a["asset_type"] == "stock":
            price = await fetch_stock_price(symbol)
            if price is None:
                continue

        # MF
        else:
            price = await fetch_mf_nav(symbol)
            if price is None:
                continue

        current = qty * price
        invested = qty * avg

        total_current += current
        total_invested += invested

        if a["asset_type"] == "stock":
            stock_value += current
            stock_invested += invested

    # 👉 Totals
    total_pnl = total_current - total_invested
    total_pnl_pct = (total_pnl / total_invested * 100) if total_invested else 0

    stock_return_pct = (
        (stock_value - stock_invested) / stock_invested * 100
        if stock_invested else 0
    )

    # 👉 Format helpers
    def fmt_rupee(x):
        return f"₹{x:,.0f}"

    def fmt_pct(x):
        sign = "+" if x >= 0 else ""
        return f"{sign}{x:.2f}%"

    def fmt_pnl(x, pct):
        sign = "+" if x >= 0 else "-"
        return f"{sign}{fmt_rupee(abs(x))} ({fmt_pct(abs(pct))})"

    # 👉 Build message (FINAL FORMAT)
    msg = (
        f"📊 WealthLens Daily Update\n\n"
        f"💼 Portfolio Value: {fmt_rupee(total_current)}\n"
        f"💰 Invested: {fmt_rupee(total_invested)}\n"
        f"📈 Total P&L: {fmt_pnl(total_pnl, total_pnl_pct)}\n\n"
        f"ℹ️ MF values based on latest available NAV\n\n"
        f"---\n\n"
        f"⚡ Next:\n"
        f"• /add_stock\n"
        f"• /add_mf\n"
        f"• /portfolio"
    )

    return msg

async def build_daily_message_bkp(user_id: int) -> str:
    assets = get_assets(user_id)

    if not assets:
        return "📭 No portfolio data."

    total_current = 0
    total_invested = 0

    stock_value = 0
    stock_invested = 0

    mf_lines = []

    for a in assets:
        qty = a["quantity"]
        avg = a["avg_price"]
        symbol = a["symbol"]

        # STOCK
        if a["asset_type"] == "stock":
            price = await fetch_stock_price(symbol)

            if not price:
                continue

            current = qty * price
            invested = qty * avg

            stock_value += current
            stock_invested += invested

        # MF
        else:
            price = await fetch_mf_nav(symbol)

            if not price:
                price = avg  # fallback safe

            name = a.get("name") or symbol
            mf_lines.append(f"{name} → {fmt_currency(price)}")

            current = qty * price
            invested = qty * avg

        total_current += current
        total_invested += invested

    pnl = total_current - total_invested
    pnl_pct = (pnl / total_invested * 100) if total_invested else 0

    # 🧾 MESSAGE BUILD
    msg = "📊 Daily Portfolio Update \n\n"

    msg += f"💼 Current Value: {fmt_currency(total_current)}\n"
    msg += f"💰 Invested: {fmt_currency(total_invested)}\n"
    msg += f"📈 Total P&L: {fmt_pnl(pnl, pnl_pct)}\n\n"

    # 📈 STOCK PERFORMANCE
    if stock_invested > 0:
        stock_return = ((stock_value - stock_invested) / stock_invested) * 100
        msg += "📈 Stocks Performance\n"
        msg += f"Return: {stock_return:.2f}%\n\n"

    # 📊 MF NAV
    if mf_lines:
        msg += "📊 Mutual Funds (Latest NAV - T+1)\n"
        msg += "\n".join(mf_lines[:5]) + "\n"

    return msg

async def build_portfolio(user_id: int) -> dict:
    """
    Returns enriched portfolio data:
    {
        assets: [{ ...db fields, current_price, current_value, invested, pnl, pnl_pct }],
        total_invested: float,
        total_current:  float,
        total_pnl:      float,
        total_pnl_pct:  float,
    }
    """
    assets = get_assets(user_id)
    if not assets:
        return {"assets": [], "total_invested": 0, "total_current": 0,
                "total_pnl": 0, "total_pnl_pct": 0}

    # Fetch all prices concurrently
    prices = await asyncio.gather(
        *[get_price(a["symbol"], a["asset_type"]) for a in assets]
    )

    enriched = []
    total_invested = 0.0
    total_current = 0.0

    for asset, price in zip(assets, prices):
        invested = asset["quantity"] * asset["avg_price"]
        current_value = asset["quantity"] * price if price else None
        pnl = (current_value - invested) if current_value is not None else None
        pnl_pct = (pnl / invested * 100) if pnl is not None and invested else None

        enriched.append({
            **asset,
            "current_price": price,
            "current_value": current_value,
            "invested": invested,
            "pnl": pnl,
            "pnl_pct": pnl_pct,
        })

        total_invested += invested
        if current_value is not None:
            total_current += current_value

    total_pnl = total_current - total_invested
    total_pnl_pct = (total_pnl / total_invested * 100) if total_invested else 0

    return {
        "assets": enriched,
        "total_invested": total_invested,
        "total_current": total_current,
        "total_pnl": total_pnl,
        "total_pnl_pct": total_pnl_pct,
    }


def allocation_breakdown(portfolio: dict) -> dict:
    """Asset-type and individual allocation percentages."""
    total = portfolio["total_current"] or portfolio["total_invested"]
    if not total:
        return {}

    by_type: dict[str, float] = {}
    by_asset: list[dict] = []

    for a in portfolio["assets"]:
        val = a["current_value"] or a["invested"]
        atype = a["asset_type"]
        by_type[atype] = by_type.get(atype, 0) + val
        by_asset.append({
            "symbol": a["symbol"],
            "name": a["name"],
            "asset_type": atype,
            "value": val,
            "pct": val / total * 100,
        })

    return {
        "by_type": {k: {"value": v, "pct": v / total * 100} for k, v in by_type.items()},
        "by_asset": sorted(by_asset, key=lambda x: x["pct"], reverse=True),
        "total": total,
    }


def sector_exposure(portfolio: dict) -> dict:
    """
    Simplified exposure split: stocks vs mutual funds.
    (Real sector data would require a paid data provider.)
    """
    stocks_val = sum(
        (a["current_value"] or a["invested"])
        for a in portfolio["assets"] if a["asset_type"] == "stock"
    )
    mf_val = sum(
        (a["current_value"] or a["invested"])
        for a in portfolio["assets"] if a["asset_type"] == "mf"
    )
    total = stocks_val + mf_val or 1

    return {
        "Equities (Direct)": {"value": stocks_val, "pct": stocks_val / total * 100},
        "Mutual Funds": {"value": mf_val, "pct": mf_val / total * 100},
    }


def top_performers(portfolio: dict, n: int = 3) -> list[dict]:
    ranked = [a for a in portfolio["assets"] if a.get("pnl_pct") is not None]
    return sorted(ranked, key=lambda x: x["pnl_pct"], reverse=True)[:n]


def bottom_performers(portfolio: dict, n: int = 3) -> list[dict]:
    ranked = [a for a in portfolio["assets"] if a.get("pnl_pct") is not None]
    return sorted(ranked, key=lambda x: x["pnl_pct"])[:n]

def get_top_bottom_performers(
    daily_changes: dict[str, float | None]
) -> dict:
    """
    Pure function — no API calls.
    Handles all scenarios:
      - All positive / all negative / mixed
      - Ties at top or bottom (show all tied)
      - Single stock
      - All zero (holiday/no movement)
      - All None (fetch failed)
      - Empty (no stocks)

    Returns:
    {
        top:        [{"symbol": str, "pct": float}, ...],
        bottom:     [{"symbol": str, "pct": float}, ...],
        all_zero:   bool,
        no_data:    bool,
        no_stocks:  bool,
        single:     bool,   # only one stock in portfolio
        skipped:    int,    # count of symbols where price fetch failed
    }
    """

    # ── No stocks at all ──────────────────────────────────────────────────────
    if not daily_changes:
        return {
            "top": [], "bottom": [], "all_zero": False,
            "no_data": False, "no_stocks": True,
            "single": False, "skipped": 0,
        }

    total   = len(daily_changes)
    valid   = {s: p for s, p in daily_changes.items() if p is not None}
    skipped = total - len(valid)

    # ── All prices failed ─────────────────────────────────────────────────────
    if not valid:
        return {
            "top": [], "bottom": [], "all_zero": False,
            "no_data": True, "no_stocks": False,
            "single": False, "skipped": skipped,
        }

    # ── All zero — holiday or no movement ─────────────────────────────────────
    if all(abs(p) < 0.001 for p in valid.values()):
        return {
            "top": [], "bottom": [], "all_zero": True,
            "no_data": False, "no_stocks": False,
            "single": len(valid) == 1, "skipped": skipped,
        }

    # ── Single stock ──────────────────────────────────────────────────────────
    if len(valid) == 1:
        symbol, pct = next(iter(valid.items()))
        entry = [{"symbol": symbol, "pct": round(pct, 2)}]
        return {
            "top": entry, "bottom": entry, "all_zero": False,
            "no_data": False, "no_stocks": False,
            "single": True, "skipped": skipped,
        }

    # ── Sort: highest % first ─────────────────────────────────────────────────
    ranked = sorted(valid.items(), key=lambda x: x[1], reverse=True)

    # ── Top: best performer + all ties at that level ──────────────────────────
    best_pct = ranked[0][1]
    top = [
        {"symbol": s, "pct": round(p, 2)}
        for s, p in ranked
        if abs(p - best_pct) < 0.001
    ]

    # ── Bottom: worst performer + all ties at that level ─────────────────────
    worst_pct = ranked[-1][1]
    bottom = [
        {"symbol": s, "pct": round(p, 2)}
        for s, p in ranked
        if abs(p - worst_pct) < 0.001
    ]

    # ── Edge: top and bottom are same group (all tied) ────────────────────────
    # e.g. 3 stocks all at +1.00% — top == bottom, show once
    if best_pct == worst_pct:
        bottom = []

    return {
        "top": top, "bottom": bottom, "all_zero": False,
        "no_data": False, "no_stocks": False,
        "single": False, "skipped": skipped,
    }

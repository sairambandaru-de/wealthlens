"""
Message formatting utilities for Telegram (MarkdownV2).
"""

def esc(text: str) -> str:
    """Escape special chars for Telegram MarkdownV2."""
    special = r"\_*[]()~`>#+-=|{}.!"
    return "".join(f"\\{c}" if c in special else c for c in str(text))


def fmt_currency(amount: float | None, symbol: str = "₹") -> str:
    if amount is None:
        return "N/A"
    if abs(amount) >= 1_00_00_000:
        return f"{symbol}{amount/1_00_00_000:.2f}Cr"
    elif abs(amount) >= 1_00_000:
        return f"{symbol}{amount/1_00_000:.2f}L"
    elif abs(amount) >= 1_000:
        return f"{symbol}{amount:,.2f}"
    return f"{symbol}{amount:.2f}"


def fmt_pnl(pnl: float | None, pct: float | None) -> str:
    if pnl is None:
        return "N/A"
    arrow = "🟢" if pnl >= 0 else "🔴"
    sign = "+" if pnl >= 0 else ""
    pct_str = f" ({sign}{pct:.2f}%)" if pct is not None else ""
    return f"{arrow} {sign}{fmt_currency(pnl)}{pct_str}"


def fmt_asset_row(a: dict) -> str:
    price_str = fmt_currency(a.get("current_price"))
    pnl_str = fmt_pnl(a.get("pnl"), a.get("pnl_pct"))
    tag = "📈" if a["asset_type"] == "stock" else "🏦"
    return (
        f"{tag} *{esc(a['symbol'])}* — {esc(a['name'][:28])}\n"
        f"   Qty: {esc(str(a['quantity']))} | Avg: {esc(fmt_currency(a['avg_price']))} | "
        f"LTP: {esc(price_str)}\n"
        f"   P&L: {esc(pnl_str)}\n"
    )


def build_portfolio_message(portfolio: dict) -> str:
    if not portfolio["assets"]:
        return "📭 Your portfolio is empty\\. Use /add\\_stock or /add\\_mf to get started\\."

    lines = ["*📊 Portfolio Summary*\n"]
    for a in portfolio["assets"]:
        lines.append(fmt_asset_row(a))

    lines.append("─" * 28)
    lines.append(
        f"*Invested:* {esc(fmt_currency(portfolio['total_invested']))}\n"
        f"*Current:*  {esc(fmt_currency(portfolio['total_current']))}\n"
        f"*Total P&L:* {esc(fmt_pnl(portfolio['total_pnl'], portfolio['total_pnl_pct']))}"
    )
    return "\n".join(lines)


def build_allocation_message(alloc: dict) -> str:
    if not alloc:
        return "No allocation data available\\."

    lines = ["*📐 Portfolio Allocation*\n"]
    lines.append("*By Type:*")
    for atype, data in alloc["by_type"].items():
        label = "Stocks" if atype == "stock" else "Mutual Funds"
        bar = "█" * int(data["pct"] / 5)
        pct_str = f"{data['pct']:.1f}%"
        lines.append(f"  {esc(label)}: {esc(bar)} {esc(pct_str)} \\({esc(fmt_currency(data['value']))}\\)")

    lines.append("\n*By Asset:*")
    for a in alloc["by_asset"]:
        bar = "█" * max(1, int(a["pct"] / 4))
        pct_str = f"{a['pct']:.1f}%"
        lines.append(f"  {esc(a['symbol'])}: {esc(bar)} {esc(pct_str)}")

    lines.append(f"\n*Total Portfolio Value:* {esc(fmt_currency(alloc['total']))}")
    return "\n".join(lines)


def build_exposure_message(exposure: dict) -> str:
    lines = ["*🔍 Portfolio Exposure*\n"]
    for category, data in exposure.items():
        bar = "█" * int(data["pct"] / 5)
        pct_str = f"{data['pct']:.1f}%"
        lines.append(
            f"*{esc(category)}*\n"
            f"  {esc(bar)} {esc(pct_str)} — {esc(fmt_currency(data['value']))}"
        )
    return "\n".join(lines)


def build_performers_message(performers: list[dict], label: str) -> str:
    if not performers:
        return f"No {label} data available\\."
    lines = [f"*{esc(label)}*\n"]
    for i, a in enumerate(performers, 1):
        lines.append(
            f"{i}\\. *{esc(a['symbol'])}* — {esc(a['name'][:25])}\n"
            f"   {esc(fmt_pnl(a.get('pnl'), a.get('pnl_pct')))}"
        )
    return "\n".join(lines)


def build_compare_message(assets: list[dict]) -> str:
    if not assets:
        return "No matching assets found\\."
    lines = ["*⚖️ Compare Assets*\n"]
    headers = ["Symbol", "Type", "Invested", "Current", "P&L%"]
    lines.append(" | ".join(f"*{esc(h)}*" for h in headers))
    lines.append("─" * 40)
    for a in assets:
        pct = f"{a['pnl_pct']:+.2f}%" if a.get("pnl_pct") is not None else "N/A"
        lines.append(
            f"{esc(a['symbol'])} | {esc(a['asset_type'])} | "
            f"{esc(fmt_currency(a['invested']))} | "
            f"{esc(fmt_currency(a.get('current_value')))} | "
            f"{esc(pct)}"
        )
    return "\n".join(lines)

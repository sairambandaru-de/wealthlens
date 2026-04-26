# services/daily_update.py

def calculate_portfolio_metrics(assets, price_data):
    total_value = 0
    total_invested = 0
    asset_returns = []

    for asset in assets:
        symbol = asset["symbol"]
        qty = asset["quantity"]
        buy_price = asset.get("buy_price", 0)

        current_price = price_data.get(symbol, 0)

        invested = qty * buy_price
        value = qty * current_price

        total_invested += invested
        total_value += value

        if buy_price > 0:
            returns = ((current_price - buy_price) / buy_price) * 100
            asset_returns.append((symbol, returns))

    pnl = total_value - total_invested
    pnl_percent = (pnl / total_invested * 100) if total_invested else 0

    top = max(asset_returns, key=lambda x: x[1], default=("N/A", 0))
    bottom = min(asset_returns, key=lambda x: x[1], default=("N/A", 0))

    return {
        "total_value": total_value,
        "pnl": pnl,
        "pnl_percent": pnl_percent,
        "top": top,
        "bottom": bottom
    }


def format_daily_message(metrics, mf_value):
    return f"""
📊 Daily Portfolio Update

💰 Total: ₹{metrics['total_value']/100000:.2f}L
🟢 P&L: ₹{metrics['pnl']:.0f} ({metrics['pnl_percent']:.2f}%)

🔥 Movers
Top: {metrics['top'][0]} ({metrics['top'][1]:.2f}%)
Low: {metrics['bottom'][0]} ({metrics['bottom'][1]:.2f}%)

🏦 Mutual Funds: ₹{mf_value:,.0f}
ℹ️ NAV updates end-of-day

━━━━━━━━━━━━━━
🔒 Analytics only. Not investment advice.
"""


# ✅ ADD YOUR FUNCTION HERE
def format_nifty_section(portfolio_return, nifty_return):

    if nifty_return is None:
        return (
            "📊 Market Comparison (Daily)\n"
            "NIFTY: Data building…"
        )

    diff = portfolio_return - nifty_return
    symbol = "↑" if diff > 0 else "↓"

    return (
        "📊 Market Comparison (Daily)\n"
        f"Your Portfolio: {portfolio_return:.2f}%\n"
        f"NIFTY: {nifty_return:.2f}%\n"
        f"{symbol} {'Ahead' if diff > 0 else 'Behind'} by {abs(diff):.2f}%"
    )

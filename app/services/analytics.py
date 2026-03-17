"""
Portfolio analytics: current value, P&L, allocation, exposure, top/bottom performers.
"""

import asyncio
import logging
from app.database import get_assets
from app.services.price_service import get_price

logger = logging.getLogger(__name__)


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

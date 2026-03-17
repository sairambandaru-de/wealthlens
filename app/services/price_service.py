"""
Price service
- Stocks  : Yahoo Finance (yfinance)
- MF NAVs : AMFI India open data API
"""

import httpx
import logging
import asyncio
from app.database import get_cached_price, set_cached_price

logger = logging.getLogger(__name__)

AMFI_NAV_URL = "https://www.amfiindia.com/spages/NAVAll.txt"

# In-memory AMFI scheme cache (scheme_code -> nav)
_amfi_cache: dict[str, float] = {}
_amfi_loaded = False


# ─── Stock prices via yfinance ────────────────────────────────────────────────

async def fetch_stock_price(symbol: str) -> float | None:
    """Fetch current stock price from Yahoo Finance. Appends .NS for NSE if needed."""
    cached = get_cached_price(symbol, "stock")
    if cached:
        return cached

    # Try NSE first, then BSE, then plain symbol
    candidates = [symbol]
    if not symbol.endswith((".NS", ".BO")):
        candidates = [f"{symbol}.NS", f"{symbol}.BO", symbol]

    try:
        import yfinance as yf

        def _fetch():
            for ticker_sym in candidates:
                t = yf.Ticker(ticker_sym)
                info = t.fast_info
                price = getattr(info, "last_price", None)
                if price and price > 0:
                    return price
            return None

        price = await asyncio.to_thread(_fetch)
        if price:
            set_cached_price(symbol, "stock", price)
        return price
    except Exception as e:
        logger.error(f"yfinance error for {symbol}: {e}")
        return None


# ─── Mutual Fund NAV via AMFI ─────────────────────────────────────────────────

async def _load_amfi_data():
    global _amfi_cache, _amfi_loaded
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(AMFI_NAV_URL)
            resp.raise_for_status()
        lines = resp.text.splitlines()
        for line in lines:
            parts = line.split(";")
            if len(parts) >= 5:
                scheme_code = parts[0].strip()
                nav_str = parts[4].strip()
                try:
                    _amfi_cache[scheme_code] = float(nav_str)
                except ValueError:
                    pass
        _amfi_loaded = True
        logger.info(f"AMFI data loaded: {len(_amfi_cache)} schemes")
    except Exception as e:
        logger.error(f"Failed to load AMFI data: {e}")


async def fetch_mf_nav(scheme_code: str) -> float | None:
    """Fetch NAV for a mutual fund scheme from AMFI."""
    cached = get_cached_price(scheme_code, "mf")
    if cached:
        return cached

    global _amfi_loaded
    if not _amfi_loaded:
        await _load_amfi_data()

    nav = _amfi_cache.get(scheme_code)
    if nav:
        set_cached_price(scheme_code, "mf", nav)
    return nav


async def search_mf_schemes(query: str) -> list[dict]:
    """Search for mutual fund schemes by name. Returns list of {code, name, nav}."""
    global _amfi_loaded
    if not _amfi_loaded:
        await _load_amfi_data()

    query_lower = query.lower()
    results = []
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get(AMFI_NAV_URL)
            resp.raise_for_status()
        for line in resp.text.splitlines():
            parts = line.split(";")
            if len(parts) >= 5:
                scheme_code = parts[0].strip()
                name = parts[3].strip()
                nav_str = parts[4].strip()
                if query_lower in name.lower():
                    try:
                        results.append({
                            "code": scheme_code,
                            "name": name,
                            "nav": float(nav_str),
                        })
                    except ValueError:
                        pass
            if len(results) >= 5:
                break
    except Exception as e:
        logger.error(f"MF search error: {e}")
    return results


async def get_price(symbol: str, asset_type: str) -> float | None:
    if asset_type == "stock":
        return await fetch_stock_price(symbol)
    elif asset_type == "mf":
        return await fetch_mf_nav(symbol)
    return None

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
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/plain",
    "Connection": "keep-alive"
}

# In-memory AMFI scheme cache (scheme_code -> nav)
_amfi_nav_cache: dict[str, float] = {}
_amfi_name_cache: dict[str, str] = {}
_amfi_loaded = False

# ─── Stock prices via yfinance ────────────────────────────────────────────────

async def fetch_stock_price(symbol: str) -> float | None:
    symbol = symbol.upper().strip()

    cached = get_cached_price(symbol, "stock")
    if cached:
        return cached

    import yfinance as yf

    # Build candidates
    if symbol.endswith((".NS", ".BO")):
        candidates = [symbol]
    else:
        candidates = [f"{symbol}.NS", f"{symbol}.BO"]

    def _fetch():
        for ticker_sym in candidates:
            try:
                t = yf.Ticker(ticker_sym)

                # 🔥 ALWAYS use history (most reliable)
                hist = t.history(period="1d")

                if not hist.empty:
                    price = float(hist["Close"].iloc[-1])
                    if price > 0:
                        return price

            except Exception:
                continue

        return None

    price = await asyncio.to_thread(_fetch)

    if price:
        set_cached_price(symbol, "stock", price)

    return price

async def fetch_stock_price_1(symbol: str) -> float | None:
    """Fetch current stock price from Yahoo Finance. Appends .NS for NSE if needed."""
    symbol = symbol.upper().strip()
    cached = get_cached_price(symbol, "stock")
    if cached:
        return cached

    # Try NSE first, then BSE, then plain symbol
    candidates = []

    if symbol.endswith(".NS") or symbol.endswith(".BO"):
        candidates = [symbol]
    else:
        candidates = [
            f"{symbol}.NS",   # NSE first
            f"{symbol}.BO",   # then BSE
        ]
    try:
        import yfinance as yf
        def _fetch():
            for ticker_sym in candidates:
                try:
                    t = yf.Ticker(ticker_sym)

                    # Try fast_info first
                    info = getattr(t, "fast_info", None)
                    price = getattr(info, "last_price", None) if info else None

                    # 🔥 Fallback to history (important for BSE)
                    if not price:
                        hist = t.history(period="1d")
                        if not hist.empty:
                            price = float(hist["Close"].iloc[-1])

                            if price and price > 0:
                                return price

                except Exception:
                    continue

            return None

        price = await asyncio.to_thread(_fetch)
        if price:
            set_cached_price(symbol, "stock", price)
        return price
    except Exception as e:
        logger.error(f"yfinance error for {symbol}: {e}")
        return None


async def fetch_nifty_price():
    import yfinance as yf

    try:
        t = yf.Ticker("^NSEI")
        hist = t.history(period="1d")

        if hist.empty:
            return 0.0

        return float(hist["Close"].iloc[-1])

    except:
        return 0.0

# ─── Mutual Fund NAV via AMFI ─────────────────────────────────────────────────

async def _load_amfi_data():
    global _amfi_loaded, _amfi_nav_cache, _amfi_name_cache

    if _amfi_loaded:
        return

    try:
        logger.info("🚀 Loading AMFI data...")
        async with httpx.AsyncClient(
    				timeout=30,
    				headers=HEADERS,
    				follow_redirects=True  # ✅ IMPORTANT
				) as client:
            resp = await client.get(AMFI_NAV_URL)
            resp.raise_for_status()
            text = resp.text

        #lines = resp.text.splitlines()
        lines = text.splitlines()
        count = 0

        for line in lines:
            parts = line.split(";")

            if len(parts) < 5:
                continue

            code = parts[0].strip()
            name = parts[3].strip()
            nav_str = parts[4].strip()

            # Skip headers / invalid
            if not code.isdigit():
                continue

            try:
                nav = float(nav_str)
            except:
                continue

            if nav <= 0:
                continue

            _amfi_nav_cache[code] = nav
            _amfi_name_cache[code] = name
            count += 1

        _amfi_loaded = True
        logger.info(f"✅ AMFI loaded: {count} schemes")

    except Exception as e:
        logger.error(f"❌ AMFI load failed: {e}", exc_info=True)


async def fetch_mf_nav(scheme_code: str) -> float | None:
    if not _amfi_loaded:
        await _load_amfi_data()

    return _amfi_nav_cache.get(scheme_code)


def search_mf_schemes(query: str, limit: int = 5):
    query = query.lower()

    # normalize words
    query = query.replace("flexicap", "flexi cap")
    query = query.replace("smallcap", "small cap")
    query = query.replace("midcap", "mid cap")
    query = query.replace("largecap", "large cap")

    query_words = query.split()

    results = []

    for code, name in _amfi_name_cache.items():
        name_lower = name.lower()

        score = 0

        # exact match
        if query in name_lower:
            score += 10

        # word match
        for w in query_words:
            if w in name_lower:
                score += 2

        # all words match bonus
        if all(w in name_lower for w in query_words):
            score += 5

        if score > 0:
            results.append({
                "score": score,
                "code": code,
                "name": name
            })

    # sort by score
    results.sort(key=lambda x: x["score"], reverse=True)

    return results[:limit]

async def search_mf_schemes_bkp(query: str) -> list[dict]:
    if not _amfi_loaded:
        await _load_amfi_data()

    query = query.lower().strip()

    results = []

    for code, name in _amfi_name_cache.items():
        if query in name.lower():
            nav = _amfi_nav_cache.get(code)

            if not nav:
                continue

            results.append({
                "code": code,
                "name": name,
                "nav": nav
            })

        if len(results) >= 10:
            break

    return results[:6]

async def get_price(symbol: str, asset_type: str) -> float | None:
    if asset_type == "stock":
        return await fetch_stock_price(symbol)
    elif asset_type == "mf":
        return await fetch_mf_nav(symbol)
    return None

def get_mf_nav(code: str):
    return _amfi_nav_cache.get(code)

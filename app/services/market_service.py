import yfinance as yf
import sqlite3
from datetime import datetime

DB_PATH = "data/portfolio.db"

def fetch_nifty():
    ticker = yf.Ticker("^NSEI")
    hist = ticker.history(period="2d")

    if len(hist) < 2:
        return None

    prev_close = hist['Close'].iloc[-2]
    current_close = hist['Close'].iloc[-1]

    change_pct = ((current_close - prev_close) / prev_close) * 100

    return {
        "name": "NIFTY50",
        "symbol": "^NSEI",
        "close_value": round(current_close, 2),
        "change_percent": round(change_pct, 2),
        "date": datetime.now().strftime("%Y-%m-%d")
    }


def store_index(data):
    if not data:
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("""
        INSERT OR REPLACE INTO market_index
        (name, symbol, close_value, change_percent, date)
        VALUES (?, ?, ?, ?, ?)
    """, (
        data["name"],
        data["symbol"],
        data["close_value"],
        data["change_percent"],
        data["date"]
    ))

    conn.commit()
    conn.close()


def get_latest_nifty():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT change_percent
        FROM market_index
        WHERE symbol='^NSEI'
        ORDER BY date DESC
        LIMIT 1
    """)

    row = cursor.fetchone()
    conn.close()

    return row[0] if row else None

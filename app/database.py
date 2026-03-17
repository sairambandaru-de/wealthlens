import sqlite3
import os
from datetime import datetime

DB_PATH = os.getenv("DB_PATH", "data/portfolio.db")


def get_connection() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    conn = get_connection()
    cursor = conn.cursor()

    # Users table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id          INTEGER PRIMARY KEY,
            telegram_id INTEGER UNIQUE NOT NULL,
            username    TEXT,
            first_name  TEXT,
            created_at  TEXT DEFAULT (datetime('now'))
        )
    """)

    # Assets table — stocks and mutual funds
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS assets (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            asset_type  TEXT NOT NULL CHECK(asset_type IN ('stock', 'mf')),
            symbol      TEXT NOT NULL,          -- ticker for stocks, scheme_code for MF
            name        TEXT NOT NULL,
            quantity    REAL NOT NULL CHECK(quantity > 0),
            avg_price   REAL NOT NULL CHECK(avg_price > 0),
            currency    TEXT DEFAULT 'INR',
            added_at    TEXT DEFAULT (datetime('now')),
            UNIQUE(user_id, symbol, asset_type)
        )
    """)

    # Price cache to reduce API hammering
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS price_cache (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol      TEXT NOT NULL,
            asset_type  TEXT NOT NULL,
            price       REAL NOT NULL,
            fetched_at  TEXT DEFAULT (datetime('now')),
            UNIQUE(symbol, asset_type)
        )
    """)

    conn.commit()
    conn.close()


# ─── User helpers ────────────────────────────────────────────────────────────

def upsert_user(telegram_id: int, username: str | None, first_name: str | None) -> int:
    conn = get_connection()
    try:
        conn.execute("""
            INSERT INTO users (telegram_id, username, first_name)
            VALUES (?, ?, ?)
            ON CONFLICT(telegram_id) DO UPDATE SET
                username   = excluded.username,
                first_name = excluded.first_name
        """, (telegram_id, username, first_name))
        conn.commit()
        row = conn.execute("SELECT id FROM users WHERE telegram_id = ?", (telegram_id,)).fetchone()
        return row["id"]
    finally:
        conn.close()


def get_user_id(telegram_id: int) -> int | None:
    conn = get_connection()
    try:
        row = conn.execute("SELECT id FROM users WHERE telegram_id = ?", (telegram_id,)).fetchone()
        return row["id"] if row else None
    finally:
        conn.close()


# ─── Asset helpers ────────────────────────────────────────────────────────────

def add_asset(user_id: int, asset_type: str, symbol: str, name: str,
               quantity: float, avg_price: float) -> bool:
    """Insert or update an asset. Returns True on success."""
    conn = get_connection()
    try:
        conn.execute("""
            INSERT INTO assets (user_id, asset_type, symbol, name, quantity, avg_price)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id, symbol, asset_type) DO UPDATE SET
                quantity  = quantity + excluded.quantity,
                avg_price = ((avg_price * quantity) + (excluded.avg_price * excluded.quantity))
                            / (quantity + excluded.quantity),
                name      = excluded.name
        """, (user_id, asset_type, symbol.upper(), name, quantity, avg_price))
        conn.commit()
        return True
    except Exception:
        return False
    finally:
        conn.close()


def remove_asset(user_id: int, symbol: str) -> bool:
    conn = get_connection()
    try:
        cur = conn.execute(
            "DELETE FROM assets WHERE user_id = ? AND symbol = ?",
            (user_id, symbol.upper())
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def get_assets(user_id: int) -> list[dict]:
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM assets WHERE user_id = ? ORDER BY asset_type, symbol",
            (user_id,)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ─── Price cache helpers ──────────────────────────────────────────────────────

def get_cached_price(symbol: str, asset_type: str, max_age_seconds: int = 300) -> float | None:
    conn = get_connection()
    try:
        row = conn.execute("""
            SELECT price FROM price_cache
            WHERE symbol = ? AND asset_type = ?
              AND (julianday('now') - julianday(fetched_at)) * 86400 < ?
        """, (symbol, asset_type, max_age_seconds)).fetchone()
        return row["price"] if row else None
    finally:
        conn.close()


def set_cached_price(symbol: str, asset_type: str, price: float):
    conn = get_connection()
    try:
        conn.execute("""
            INSERT INTO price_cache (symbol, asset_type, price)
            VALUES (?, ?, ?)
            ON CONFLICT(symbol, asset_type) DO UPDATE SET
                price      = excluded.price,
                fetched_at = datetime('now')
        """, (symbol, asset_type, price))
        conn.commit()
    finally:
        conn.close()

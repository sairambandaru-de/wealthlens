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
    # Store Nifty daily
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS market_index (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,              -- NIFTY50, BANKNIFTY
            symbol TEXT,            -- ^NSEI, ^NSEBANK
            close_value REAL,
            change_percent REAL,
            date TEXT
        )
    """)
    # Prevent duplicates
    cursor.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_market_unique 
        ON market_index(symbol, date)
    """)
    
    add_nifty_base_column()
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


def remove_asset(user_id, symbol, asset_type):
    conn = get_connection()
    try:
        conn.execute(
            """
            DELETE FROM assets
            WHERE user_id = ?
            AND symbol = ?
            AND asset_type = ?
            """,
            (user_id, symbol, asset_type),
        )
        conn.commit()
        return True
    except Exception as e:
        print("Remove error:", e)
        return False
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

def get_cached_price(symbol: str, asset_type: str, max_age_seconds: int = 900) -> float | None:
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

def get_all_users():
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT telegram_id FROM users"
        ).fetchall()

        return [dict(r) for r in rows]
    finally:
        conn.close()

def get_user_nifty_base(user_id):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT nifty_base FROM users WHERE id = ?",
        (user_id,)
    )
    row = cursor.fetchone()
    conn.close()

    return row[0] if row and row[0] else None


def set_user_nifty_base(user_id, price):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        "UPDATE users SET nifty_base = ? WHERE id = ?",
        (price, user_id)
    )

    conn.commit()
    conn.close()

def add_nifty_base_column():
    conn = get_connection()
    cursor = conn.cursor()

    # Check if column exists
    cursor.execute("PRAGMA table_info(users)")
    columns = [col[1] for col in cursor.fetchall()]
    if "nifty_base" not in columns:
        cursor.execute("ALTER TABLE users ADD COLUMN nifty_base REAL")
        conn.commit()
    if "is_active" not in columns:
        cursor.execute("ALTER TABLE users ADD COLUMN is_active INTEGER DEFAULT 1")
        conn.commit()

    conn.close()

def set_user_active(telegram_id: int):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        "UPDATE users SET is_active = 1 WHERE telegram_id = ?",
        (telegram_id,)
    )

    conn.commit()
    conn.close()

def set_user_inactive(telegram_id: int):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        "UPDATE users SET is_active = 0 WHERE telegram_id = ?",
        (telegram_id,)
    )

    conn.commit()
    conn.close()

def get_active_users():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT telegram_id FROM users WHERE is_active = 1"
    )

    rows = cursor.fetchall()
    #cursor.execute(
    #"SELECT id, username, telegram_id  FROM users;"
    #)
    #rows_1 = cursor.fetchall()
    #print(rows_1,"Users****************")
    #for r in rows_1:
    #    print(r[0],"--",r[1],"--",r[2])
    conn.close()

    return [row[0] for row in rows]

def get_user_status(telegram_id: int):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT is_active FROM users WHERE telegram_id = ?",
        (telegram_id,)
    )

    row = cursor.fetchone()
    conn.close()

    return row[0] if row else None

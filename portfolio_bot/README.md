# 📊 Telegram Portfolio Analytics Bot

A self-hosted Telegram bot for tracking and analysing your Indian stock & mutual fund portfolio — built with **FastAPI**, **SQLite**, and **Python**.

> ⚠️ This bot provides **portfolio analytics only**. It does not offer investment advice.

---

## Features

| Command | Description |
|---|---|
| `/start` | Register & view command list |
| `/add_stock` | Add a stock holding (NSE/BSE ticker) |
| `/add_mf` | Add a mutual fund holding (AMFI) |
| `/remove_asset` | Remove an asset |
| `/assets` | List all holdings |
| `/portfolio` | Full portfolio with live P&L |
| `/allocation` | Allocation by asset & type |
| `/exposure` | Equity vs MF exposure |
| `/top` | Top 3 performers |
| `/bottom` | Bottom 3 performers |
| `/compare RELIANCE TCS` | Side-by-side comparison |

---

## Tech Stack

- **FastAPI** — async webhook server
- **SQLite** — lightweight persistent storage
- **yfinance** — live NSE/BSE stock prices
- **AMFI India API** — live mutual fund NAVs
- **Telegram Bot API** — webhook-based messaging

---

## Project Structure

```
portfolio_bot/
├── app/
│   ├── main.py              # FastAPI app & lifespan
│   ├── database.py          # SQLite models & helpers
│   ├── models/
│   │   └── schemas.py       # Pydantic schemas
│   ├── routers/
│   │   └── webhook.py       # POST /webhook endpoint
│   └── services/
│       ├── analytics.py     # P&L, allocation, exposure
│       ├── formatter.py     # Telegram MarkdownV2 formatting
│       ├── price_service.py # yfinance + AMFI price fetching
│       └── telegram.py      # Send message helpers
├── data/                    # SQLite DB (auto-created)
├── .env.example
├── Dockerfile
├── requirements.txt
└── README.md
```

---

## Quick Start

### 1. Clone & install

```bash
git clone <repo>
cd portfolio_bot
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env — add your TELEGRAM_BOT_TOKEN and WEBHOOK_URL
```

### 3. Get a bot token

1. Open Telegram → search **@BotFather**
2. `/newbot` → follow prompts
3. Copy the token into `.env`

### 4. Expose your local server (dev)

```bash
# Install ngrok: https://ngrok.com
ngrok http 8000
# Copy the https URL into WEBHOOK_URL in .env
```

### 5. Run

```bash
uvicorn app.main:app --reload
```

---

## Docker

```bash
docker build -t portfolio-bot .
docker run -p 8000:8000 --env-file .env portfolio-bot
```

---

## Database Schema

### `users`
| Column | Type | Notes |
|---|---|---|
| id | INTEGER PK | Internal user ID |
| telegram_id | INTEGER UNIQUE | Telegram user ID |
| username | TEXT | Optional @handle |
| first_name | TEXT | |
| created_at | TEXT | ISO datetime |

### `assets`
| Column | Type | Notes |
|---|---|---|
| id | INTEGER PK | |
| user_id | INTEGER FK | → users.id |
| asset_type | TEXT | `stock` or `mf` |
| symbol | TEXT | NSE ticker or AMFI code |
| name | TEXT | Display name |
| quantity | REAL | Shares or units |
| avg_price | REAL | Average buy price/NAV |
| currency | TEXT | Default INR |
| added_at | TEXT | |

### `price_cache`
| Column | Type | Notes |
|---|---|---|
| symbol | TEXT | |
| asset_type | TEXT | |
| price | REAL | |
| fetched_at | TEXT | Cache TTL: 5 min |

---

## Data Sources

| Data | Source | Notes |
|---|---|---|
| Stock prices | [Yahoo Finance](https://finance.yahoo.com) via `yfinance` | NSE `.NS`, BSE `.BO` |
| Mutual fund NAVs | [AMFI India](https://www.amfiindia.com/spages/NAVAll.txt) | Free public API |

---

## Notes

- Prices are cached for **5 minutes** to avoid rate-limiting.
- Duplicate assets are handled by **averaging** the buy price.
- The bot uses a **state machine** for multi-step inputs (add stock/MF flows).
- Sector-level exposure requires a paid data provider; the bot currently shows Equity vs MF split.

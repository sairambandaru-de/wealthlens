import os
import httpx
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

load_dotenv()  # loads .env before anything else reads os.getenv()

from app.database import init_db
from app.routers import webhook

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "")  # e.g. https://yourdomain.com


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Initializing database...")
    init_db()

    if TELEGRAM_BOT_TOKEN and WEBHOOK_URL:
        async with httpx.AsyncClient() as client:
            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/setWebhook"
            resp = await client.post(url, json={"url": f"{WEBHOOK_URL}/webhook"})
            logger.info(f"Webhook registration: {resp.json()}")

    yield

    # Shutdown
    logger.info("Shutting down...")


app = FastAPI(
    title="Portfolio Analytics Bot",
    description="Telegram bot for portfolio analytics",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(webhook.router)


@app.get("/health")
async def health():
    return {"status": "ok"}

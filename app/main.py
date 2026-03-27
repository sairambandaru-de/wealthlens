import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
import threading

from app.database import init_db
from app.bot import run_bot

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🚀 Starting WealthLens...")

    init_db()
    logger.info("✅ Database initialized")

    # Start bot in background
    def start_bot():
        try:
            run_bot()
        except Exception as e:
            logger.error(f"❌ Bot crashed: {e}", exc_info=True)

    threading.Thread(target=start_bot, daemon=True).start()

    yield

    logger.info("🛑 Shutting down...")


app = FastAPI(lifespan=lifespan)


@app.get("/health")
async def health():
    return {"status": "ok"}
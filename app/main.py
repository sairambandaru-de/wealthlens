import logging
from dotenv import load_dotenv

from app.database import init_db
from app.bot import run_bot
from app.services.price_service import _load_amfi_data
from app.services.scheduler import run_scheduler
# Load environment variables
load_dotenv()

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def main():
    print("🔥 Starting WealthLens...")

    # Init DB
    init_db()
    print("✅ Database initialized")

    import asyncio
    import threading

    # ✅ Load AMFI once
    asyncio.run(_load_amfi_data())

    # ✅ Start scheduler in background thread
    #def start_scheduler():
    #    asyncio.run(run_scheduler())

    #threading.Thread(target=start_scheduler, daemon=True).start()
    #print("⏰ Scheduler started")

    # ✅ IMPORTANT: Run bot in MAIN thread
    run_bot()

if __name__ == "__main__":
    main()

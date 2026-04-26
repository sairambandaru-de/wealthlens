import os
from dotenv import load_dotenv
load_dotenv()
import logging
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

from app.handlers import (
    cmd_start,
    cmd_add_stock,
    cmd_add_mf,
    cmd_assets,
    cmd_portfolio,
    cmd_allocation,
    cmd_exposure,
    cmd_top,
    cmd_bottom,
    cmd_compare,
    handle_text,
    cmd_remove_asset,
)

from app.services.telegram import set_bot,BOT_LOOP
import asyncio
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await cmd_start(update.effective_chat.id, update.effective_user.to_dict())


async def add_stock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await cmd_add_stock(update.effective_chat.id, update.effective_user.to_dict())


async def add_mf(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await cmd_add_mf(update.effective_chat.id, update.effective_user.to_dict())


async def assets(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await cmd_assets(update.effective_chat.id)


async def portfolio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await cmd_portfolio(update.effective_chat.id)


async def allocation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await cmd_allocation(update.effective_chat.id)


async def exposure(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await cmd_exposure(update.effective_chat.id)


async def top(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await cmd_top(update.effective_chat.id)


async def bottom(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await cmd_bottom(update.effective_chat.id)


async def compare(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = " ".join(context.args)
    await cmd_compare(update.effective_chat.id, args)


async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    await handle_text(
        update.effective_chat.id,
        update.message.text,
        update.effective_user.to_dict(),
    )


def run_bot():
    if not TOKEN:
        raise ValueError("❌ TELEGRAM_BOT_TOKEN not set")

    app = ApplicationBuilder().token(TOKEN).build()
    
    # Commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("add_stock", add_stock))
    app.add_handler(CommandHandler("add_mf", add_mf))
    app.add_handler(CommandHandler("assets", assets))
    app.add_handler(CommandHandler("portfolio", portfolio))
    app.add_handler(CommandHandler("allocation", allocation))
    app.add_handler(CommandHandler("exposure", exposure))
    app.add_handler(CommandHandler("top", top))
    app.add_handler(CommandHandler("bottom", bottom))
    app.add_handler(CommandHandler("compare", compare))
    app.add_handler(CommandHandler("remove_asset", cmd_remove_asset))
    # Text handler
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))

    # ✅ FIX: set bot AFTER loop starts
    async def on_startup(app):
        from app.services import telegram as tg

        loop = asyncio.get_running_loop()
        tg.BOT_LOOP = loop        # ✅ correct way
        set_bot(app.bot)
        logger.info("✅ Bot initialized with event loop")        

    app.post_init = on_startup

    logger.info("🚀 Bot started (polling)...")
    app.run_polling()

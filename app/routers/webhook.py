import logging
from fastapi import APIRouter, Request, Response
from app.routers import handlers

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/webhook")
async def telegram_webhook(request: Request):
    """
    Telegram sends all updates here.
    We parse the update and dispatch to the appropriate handler.
    """
    try:
        update = await request.json()
    except Exception:
        return Response(status_code=400)

    message = update.get("message") or update.get("edited_message")
    if not message:
        return Response(status_code=200)

    chat_id: int = message["chat"]["id"]
    user: dict = message.get("from", {})
    text: str = message.get("text", "").strip()

    if not text:
        return Response(status_code=200)

    # Parse command and optional args
    command = None
    args = ""
    if text.startswith("/"):
        parts = text.split(maxsplit=1)
        # Strip bot username suffix (e.g., /start@MyBot)
        command = parts[0].split("@")[0].lower()
        args = parts[1] if len(parts) > 1 else ""

    try:
        if command == "/start":
            await handlers.cmd_start(chat_id, user)
        elif command == "/add_stock":
            await handlers.cmd_add_stock(chat_id, user)
        elif command == "/add_mf":
            await handlers.cmd_add_mf(chat_id, user)
        elif command == "/remove_asset":
            await handlers.cmd_remove_asset(chat_id, user)
        elif command == "/assets":
            await handlers.cmd_assets(chat_id)
        elif command == "/portfolio":
            await handlers.cmd_portfolio(chat_id)
        elif command == "/allocation":
            await handlers.cmd_allocation(chat_id)
        elif command == "/exposure":
            await handlers.cmd_exposure(chat_id)
        elif command == "/top":
            await handlers.cmd_top(chat_id)
        elif command == "/bottom":
            await handlers.cmd_bottom(chat_id)
        elif command == "/compare":
            await handlers.cmd_compare(chat_id, args)
        else:
            # Free-text — route through state machine
            await handlers.handle_text(chat_id, text, user)
    except Exception as e:
        logger.exception(f"Error handling update: {e}")

    return Response(status_code=200)

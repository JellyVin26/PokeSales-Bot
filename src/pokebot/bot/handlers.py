"""Telegram bot handlers: sale flow with confirmation gate."""

import logging
from datetime import datetime

from openai import AsyncOpenAI
from sqlalchemy.ext.asyncio import AsyncSession
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from pokebot.core.config import get_settings
from pokebot.core.parser import parse_amount
from pokebot.db import queries as q
from pokebot.services import ai as ai_svc
from pokebot.services import cards as cards_svc
from pokebot.services import sheets as sheets_svc

log = logging.getLogger(__name__)

PHOTO, AMOUNT = range(2)


def _authorized(telegram_user_id: int) -> bool:
    settings = get_settings()
    if not settings.allowed_user_ids:
        return True  # ponytail: empty allowlist = allow all; set IDs before real use
    return telegram_user_id in settings.allowed_user_ids


def _confirm_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✓ Confirm", callback_data="sale:confirm"),
                InlineKeyboardButton("✏️ Edit", callback_data="sale:edit"),
                InlineKeyboardButton("❌ Cancel", callback_data="sale:cancel"),
            ]
        ]
    )


async def _ensure_user(factory, update: Update) -> None:
    u = update.effective_user
    async with factory() as session:
        await q.upsert_user(session, u.id, username=u.username, first_name=u.first_name)
        await session.commit()


# ---- Simple commands ----

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("New Sale", callback_data="cmd:new"),
         InlineKeyboardButton("Recent Sales", callback_data="cmd:sales")],
        [InlineKeyboardButton("Today Summary", callback_data="cmd:today"),
         InlineKeyboardButton("Cancel", callback_data="cmd:cancel")],
    ])
    await update.message.reply_text(
        "PokéSales Bot\n\n"
        "Record Pokémon card sales fast.\n"
        "Send card photo + amount caption (e.g. RM 13).\n\n"
        "Tap a button or type /new /sales /today",
        reply_markup=kb,
    )


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await start(update, context)


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    await update.message.reply_text("Cancelled.")
    return ConversationHandler.END


# ---- Sale conversation ----

async def new_sale(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not _authorized(update.effective_user.id):
        await update.message.reply_text("Not authorized.")
        return ConversationHandler.END

    context.user_data["photos"] = []
    await update.message.reply_text(
        "New sale. Send card photo(s), then caption with amount (e.g. RM 13 QR).\n"
        "/cancel to abort."
    )
    return PHOTO


async def receive_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not _authorized(update.effective_user.id):
        return ConversationHandler.END

    photos = context.user_data.setdefault("photos", [])
    file_id = update.message.photo[-1].file_id
    caption = update.message.caption or ""

    photos.append(file_id)

    parsed = parse_amount(caption)
    if parsed is None and caption:
        await update.message.reply_text(
            "Couldn't find the sale amount.\nPlease send the amount, e.g.: RM 13"
        )
        return PHOTO

    if parsed is None:
        await update.message.reply_text(
            f"Photo {len(photos)} received. Send more, or add amount caption."
        )
        return PHOTO

    context.user_data["amount"] = parsed
    return await _analyze_and_confirm(update, context)


async def receive_amount_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Amount sent as separate text message after photos."""
    if not _authorized(update.effective_user.id):
        return ConversationHandler.END

    parsed = parse_amount(update.message.text or "")
    if parsed is None or not context.user_data.get("photos"):
        await update.message.reply_text("Send the amount like: RM 13")
        return PHOTO

    context.user_data["amount"] = parsed
    return await _analyze_and_confirm(update, context)


async def finish_sale(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """[Finish Sale] pressed without caption - ask for amount."""
    if not context.user_data.get("photos"):
        await update.callback_query.answer("No photos yet.")
        return PHOTO
    await update.callback_query.message.reply_text("Send the amount, e.g.: RM 13")
    return PHOTO


async def _analyze_and_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    log.info("_analyze_and_confirm called, photos=%s", len(context.user_data.get("photos", [])))
    factory = context.bot_data["session"]
    settings = get_settings()

    await _ensure_user(factory, update)
    user_id = update.effective_user.id
    file_ids: list[str] = context.user_data["photos"]
    parsed = context.user_data["amount"]

    msg = await update.effective_message.reply_text("Identifying cards...")

    # 1. AI recognition on each photo
    detections: list[dict] = []
    quality_scores: list[float] = []
    ai_failed = False

    oai = AsyncOpenAI(api_key=settings.openai_api_key) if settings.openai_api_key else None
    tg_file = await context.bot.get_file(file_ids[0])

    import httpx

    async with httpx.AsyncClient(timeout=30) as hc:
        img_resp = await hc.get(tg_file.file_path)
        image_bytes = img_resp.content

    if oai is not None:
        try:
            result = await ai_svc.recognize_cards(oai, image_bytes)
            detections = result.cards
            quality_scores = [result.image_quality.get("score", 0)]
            if not result.image_quality.get("usable", False):
                await msg.edit_text(
                    "Can't reliably identify these cards.\n"
                    "- Shoot from directly above\n"
                    "- Better lighting\n"
                    "- Avoid overlapping cards\n"
                    "- Card names visible\n\n"
                    "Retake the photo or /cancel."
                )
                context.user_data["photos"] = []
                return PHOTO
        except Exception as e:  # noqa: BLE001
            log.warning("AI failed: %s", e)
            ai_failed = True
            # Show user what went wrong so they can fix it
            await msg.edit_text(f"AI identification failed: {type(e).__name__}: {e}\n\nSaving as draft...")

    # 2. Validate candidates against pokemontcg.io
    validated_items: list[dict] = []
    db_ok = True
    for det in detections:
        info = await cards_svc.validate_detection(det["name"])
        if info is None:
            db_ok = False
            break
        validated_items.append(
            {
                "card_name": info["official_name"],
                "set_name": info["set_name"],
                "set_id": info["set_id"],
                "card_number": info["card_number"],
                "quantity": det.get("quantity", 1),
                "confidence": det.get("confidence", 0),
            }
        )

    async with factory() as session:
        if ai_failed or not db_ok:
            # FR error handling: save draft so nothing is lost
            async with session.begin():
                sale = await q.create_draft_sale(
                    session, user_id, parsed.amount, parsed.currency, parsed.payment_method
                )
                for fid in file_ids:
                    await q.add_photo(session, sale.id, fid, quality_score=None)
            await msg.edit_text(
                f"Identification unavailable right now.\n"
                f"Your transaction was saved as draft {sale.id}."
            )
            context.user_data.clear()
            return ConversationHandler.END

        if not validated_items:
            await msg.edit_text(
                "Couldn't identify any cards.\nRetake the photo or enter cards manually."
            )
            context.user_data["photos"] = []
            return PHOTO

        # 3. Draft + pending confirmation
        async with session.begin():
            sale = await q.create_draft_sale(
                session, user_id, parsed.amount, parsed.currency, parsed.payment_method
            )
            for fid in file_ids:
                await q.add_photo(session, sale.id, fid, quality_score=quality_scores[0] if quality_scores else None)
            await q.replace_items(session, sale.id, validated_items)

    lines = [f"{i}. {it['card_name']} x{it['quantity']}"
             + (" ✓" if it["confidence"] >= 0.9 else f" ? {int(it['confidence']*100)}%")
             for i, it in enumerate(validated_items, 1)]

    await msg.edit_text(
        f"Sale #{sale.id}\n\n"
        f"Cards:\n" + "\n".join(lines) +
        f"\n\nTotal: RM {parsed.amount:.2f}"
        f"\nPayment: {parsed.payment_method}",
        reply_markup=_confirm_kb(),
    )
    return ConversationHandler.END


# ---- Confirmation callbacks ----

async def on_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    action = query.data.split(":")[1]

    # cmd: prefix = /start menu buttons
    if action == "new":
        # reuse new_sale logic via a mock message
        context.user_data["photos"] = []
        await query.message.edit_reply_markup()
        await query.message.reply_text(
            "New sale. Send card photo(s), then caption with amount (e.g. RM 13 QR).\n/cancel to abort."
        )
        return
    factory = context.bot_data["session"]
    if action == "sales":
        async with factory() as session:
            rows = await q.recent_sales(session, limit=10)
        text = "No sales yet." if not rows else "Recent Sales\n\n" + "\n".join(
            f"{s.id} -- RM {s.total_amount:.2f}" for s in rows
        )
        await query.message.edit_reply_markup()
        await query.message.reply_text(text)
        return
    if action == "today":
        async with factory() as session:
            s = await q.today_summary(session)
        await query.message.edit_reply_markup()
        await query.message.reply_text(
            f"Today's Sales\n\nTransactions: {s['transactions']}\n"
            f"Cards Sold: {s['cards_sold']}\nRevenue: RM {s['revenue']:.2f}"
        )
        return
    if action == "cancel":
        context.user_data.clear()
        await query.message.edit_reply_markup()
        await query.message.reply_text("Cancelled.")
        return

    # sale: prefix = sale confirmation buttons
    sale_id = context.user_data.get("last_sale_id")

    # Extract sale id from message text ("Sale #S-0001")
    text = query.message.text or ""
    if "#" in text:
        sale_id = text.split("#")[1].split()[0]

    factory = context.bot_data["session"]

    if action == "confirm":
        async with factory() as session:
            sale = await q.confirm_sale(session, sale_id)
        if sale is None:
            await query.edit_message_text("Sale not found.")
            return
        synced = False
        client = context.bot_data.get("sheets_client")
        if client:
            async with factory() as session:
                synced = await sheets_svc.sync_sale_or_enqueue(
                    client, settings_sheet_id(context), session, sale_id
                )
        note = "" if synced else "\n\nGoogle Sheets sync pending."
        await query.edit_message_text(
            f"Sale #{sale_id} recorded successfully.\n"
            f"RM {sale.total_amount:.2f}\n{sum(i.quantity for i in sale.items)} cards"
            + note
        )

    elif action == "cancel":
        async with factory() as session:
            await q.cancel_sale(session, sale_id)
        await query.edit_message_text(f"Sale #{sale_id} cancelled.")

    elif action == "edit":
        await query.edit_message_reply_markup(reply_markup=_edit_kb())


def _edit_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("Remove last card", callback_data="sale:rmcard")],
         [InlineKeyboardButton("Back", callback_data="sale:back")]]
    )


def settings_sheet_id(context: ContextTypes.DEFAULT_TYPE) -> str:
    from ..core.config import get_settings
    return getattr(get_settings(), "google_sheet_id", "") or ""


# ---- Query commands ----

async def sales_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    factory = context.bot_data["session"]
    async with factory() as session:
        rows = await q.recent_sales(session, limit=10)
    if not rows:
        await update.message.reply_text("No sales yet.")
        return
    body = "\n".join(
        f"{s.id} — RM {s.total_amount:.2f}" for s in rows
    )
    await update.message.reply_text(f"Recent Sales\n\n{body}")


async def today_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    factory = context.bot_data["session"]
    async with factory() as session:
        s = await q.today_summary(session)
    await update.message.reply_text(
        f"Today's Sales\n\nTransactions: {s['transactions']}\n"
        f"Cards Sold: {s['cards_sold']}\nRevenue: RM {s['revenue']:.2f}"
    )


async def sale_detail(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    factory = context.bot_data["session"]
    args = context.args or []
    if not args:
        await update.message.reply_text("Usage: /sale S-0001")
        return
    async with factory() as session:
        sale = await q.get_sale_with_items(session, args[0].upper())
    if sale is None:
        await update.message.reply_text("Sale not found.")
        return
    items = "\n".join(f"- {i.card_name} x{i.quantity}" for i in sale.items)
    await update.message.reply_text(
        f"{sale.id}\nRM {sale.total_amount:.2f} {sale.currency}\n"
        f"Payment: {sale.payment_method}\nStatus: {sale.status}\n\n{items}"
    )


async def card_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    factory = context.bot_data["session"]
    args = context.args or []
    if not args:
        await update.message.reply_text("Usage: /card Dusknoir")
        return
    async with factory() as session:
        stats = await q.card_stats(session, " ".join(args))
    if stats is None:
        await update.message.reply_text("No sales recorded for that card.")
        return
    await update.message.reply_text(
        f"{' '.join(args)}\n\nSold: {stats['sold']}\nTransactions: {stats['transactions']}"
    )


async def _standalone_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle photos outside ConversationHandler (button-initiated sale)."""
    log.info("_standalone_photo triggered, user_data keys=%s", list(context.user_data.keys()))
    if not _authorized(update.effective_user.id):
        return
    if "photos" not in context.user_data:
        await update.message.reply_text("Tap /new first, then send the photo.")
        return
    try:
        await receive_photo(update, context)
    except Exception as e:
        log.exception("receive_photo failed in standalone handler")
        await update.message.reply_text(f"Error: {type(e).__name__}: {e}")


def register_handlers(application: Application) -> None:
    conv = ConversationHandler(
        entry_points=[
            CommandHandler("new", new_sale),
            # no CallbackQueryHandler here - button route handled separately
        ],
        states={
            PHOTO: [
                MessageHandler(filters.PHOTO, receive_photo),
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_amount_text),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", cancel),
            MessageHandler(filters.Regex("^Finish Sale$"), finish_sale),
        ],
        allow_reentry=True,
    )

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_cmd))
    application.add_handler(CommandHandler("cancel", cancel))
    application.add_handler(CommandHandler("sales", sales_cmd))
    application.add_handler(CommandHandler("today", today_cmd))
    application.add_handler(CommandHandler("sale", sale_detail))
    application.add_handler(CommandHandler("card", card_cmd))
    application.add_handler(conv)
    # Standalone photo handler for when user taps "New Sale" button
    # (bypasses ConversationHandler, so we catch photos manually)
    application.add_handler(MessageHandler(
        filters.PHOTO & ~filters.COMMAND, _standalone_photo
    ))
    application.add_handler(CallbackQueryHandler(on_button, pattern=r"^sale:|^cmd:"))

    # Global error handler - send error to user
    async def error_handler(update, context):
        log.exception("Unhandled error: %s", context.error)
        if update and hasattr(update, 'message') and update.message:
            try:
                await update.message.reply_text(f"Bot error: {type(context.error).__name__}: {context.error}")
            except Exception:
                pass
    application.add_error_handler(error_handler)
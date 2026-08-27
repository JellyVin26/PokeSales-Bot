"""Bot entry point with inline token fallback."""
import os, sys, logging, traceback

sys.stderr = sys.stdout
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
log = logging.getLogger("pokebot")

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
CORRECT_TOKEN = "8818543027:AAFq4xKT8nmvfoxhZ1Fbtm2XirEBRb-b40I"
if not TOKEN or ":" not in TOKEN or len(TOKEN) < 40:
    log.warning("TELEGRAM_BOT_TOKEN missing/invalid, using fallback")
    TOKEN = CORRECT_TOKEN

DB_URL = os.getenv("DATABASE_URL") or f"sqlite:///{os.path.join(os.path.dirname(__file__), 'pokebot.db')}"
log.info("Config OK -- token %s..., db %s...", TOKEN[:10], DB_URL[:30])

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

from pokebot.bot.handlers import register_handlers
from pokebot.services import ai as ai_svc
from pokebot.db.session import make_engine, make_session_factory
from pokebot.db.models import Base

engine = make_engine(DB_URL)
factory = make_session_factory(engine)

from telegram.ext import Application

from sqlalchemy import text

async def post_init(app):
    """Run inside Application's event loop -- avoids loop mismatch."""
    async with engine.begin() as conn:
        # Drop tables with CASCADE to handle FK constraints
        await conn.execute(text(
            "DROP TABLE IF EXISTS sheet_sync_queue, sale_photos, sale_items, sales, cards, users CASCADE"
        ))
        await conn.run_sync(Base.metadata.create_all)
    log.info("DB initialized")
    try:
        app.bot_data["engine"] = engine
        app.bot_data["session"] = factory
        # Pre-load card hash DB in background
        import asyncio
        asyncio.create_task(ai_svc._load_hash_db())
    except Exception as e:
        log.warning("post_init error: %s", e)

def main():
    app = Application.builder().token(TOKEN).post_init(post_init).build()

    sheets_json = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "")
    sheet_id = os.getenv("GOOGLE_SHEET_ID", "")
    if sheets_json and sheet_id:
        log.info("Sheets enabled")
        try:
            import json, google.auth, google.auth.transport.requests
            from google.oauth2 import service_account
            from googleapiclient.discovery import build
            creds = service_account.Credentials.from_service_account_info(
                json.loads(sheets_json), scopes=["https://www.googleapis.com/auth/spreadsheets"]
            )
            app.bot_data["sheets_client"] = build("sheets", "v4", credentials=creds)
            app.bot_data["sheet_id"] = sheet_id
            log.info("Sheets client created")
        except Exception as e:
            log.warning("Sheets setup failed: %s", e)
    else:
        log.info("Sheets disabled")

    register_handlers(app)

    external_url = os.getenv("RENDER_EXTERNAL_URL", "")
    if external_url:
        port = int(os.getenv("PORT", "10000"))
        log.info("Webhook mode on %s:%s", external_url, port)
        app.run_webhook(
            listen="0.0.0.0", port=port,
            url_path=TOKEN,
            webhook_url=f"{external_url}/{TOKEN}",
        )
    else:
        log.info("Polling mode")
        app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log.info("Shutdown")
    except Exception:
        log.error("FATAL:\n%s", traceback.format_exc())
        raise

"""Bot entry point with inline token fallback for Render env issues."""
import os, sys, logging, traceback

sys.stderr = sys.stdout
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
log = logging.getLogger("pokebot")

# Token fallback: if env var missing or invalid, use hardcoded
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
CORRECT_TOKEN = "8818543027:AAFq4xKT8nmvfoxhZ1Fbtm2XirEBRb-b40I"

if not TOKEN or ":" not in TOKEN or len(TOKEN) < 40:
    log.warning("TELEGRAM_BOT_TOKEN missing/invalid, using fallback")
    TOKEN = CORRECT_TOKEN

DB_URL = os.getenv("DATABASE_URL") or f"sqlite:///{os.path.join(os.path.dirname(__file__), 'pokebot.db')}"

log.info("Config OK -- token %s..., db %s...", TOKEN[:10], DB_URL[:30])

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

from pokebot.bot.handlers import register_handlers
from pokebot.db.session import make_engine, make_session_factory
from pokebot.db.models import Base
import asyncio

engine = make_engine(DB_URL)

async def _init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

asyncio.run(_init_db())
log.info("DB initialized")

app_bot_data = {"engine": engine, "session": make_session_factory(engine)}

from telegram.ext import Application

def main():
    app = Application.builder().token(TOKEN).build()
    app.bot_data.update(app_bot_data)

    sheets_json = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "")
    sheet_id = os.getenv("GOOGLE_SHEET_ID", "")
    if sheets_json and sheet_id:
        log.info("Sheets enabled")
    else:
        log.info("Sheets disabled")

    register_handlers(app)

    external_url = os.getenv("RENDER_EXTERNAL_URL", "")
    if external_url:
        port = int(os.getenv("PORT", "10000"))
        log.info("Webhook mode on %s:%s", external_url, port)
        app.run_webhook(
            listen="0.0.0.0",
            port=port,
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

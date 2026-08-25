"""PokéSales Bot entry point — local dev and Render.

Render web service needs a bound port, so on Render we use webhook mode.
Locally falls back to polling.

Usage: python3 run_bot.py  (env: TELEGRAM_BOT_TOKEN, DATABASE_URL required)
"""

import os
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("pokebot")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
DATABASE_URL = os.getenv("DATABASE_URL", "")

missing = [k for k, v in [("TELEGRAM_BOT_TOKEN", TELEGRAM_BOT_TOKEN), ("DATABASE_URL", DATABASE_URL)] if not v]
if missing:
    log.error("Missing required env vars: %s", ", ".join(missing))
    sys.exit(1)

log.info("Config OK — token %s…, db %s…", TELEGRAM_BOT_TOKEN[:10], DATABASE_URL[:30])


async def _post_init(app) -> None:
    """Init DB session factory + sheets client into bot_data, register handlers."""
    from pokebot.bot.handlers import register_handlers
    from pokebot.db.session import make_engine, make_session_factory

    engine = make_engine(DATABASE_URL)
    async with engine.begin() as conn:
        from pokebot.db.models import Base
        await conn.run_sync(Base.metadata.create_all)
    log.info("DB initialized")

    app.bot_data["engine"] = engine
    app.bot_data["session"] = make_session_factory(engine)

    sheets_json = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "")
    sheet_id = os.getenv("GOOGLE_SHEET_ID", "")
    if sheets_json and sheet_id:
        try:
            import json as _json
            import tempfile
            from pokebot.services.sheets import make_client
            # ponytail: temp-file dance so gspread keeps its file-based loader; swap to from_service_account_info when touched next
            with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
                f.write(sheets_json)
                tmp = f.name
            app.bot_data["sheets_client"] = make_client(tmp).open_by_key(sheet_id)
            os.unlink(tmp)
            log.info("Sheets sync enabled")
        except Exception as e:  # noqa: BLE001
            log.warning("Sheets disabled (%s)", e)
    else:
        log.info("Sheets sync disabled")

    register_handlers(app)  # sync function


def main() -> None:
    from telegram.ext import Application

    application = (
        Application.builder()
        .token(TELEGRAM_BOT_TOKEN)
        .post_init(_post_init)
        .build()
    )

    external_url = os.getenv("RENDER_EXTERNAL_URL", "")
    if external_url:
        # Render web service: webhook mode binds $PORT, survives spin-down policy
        port = int(os.getenv("PORT", "10000"))
        log.info("Webhook mode on %s:%s", external_url, port)
        application.run_webhook(
            listen="0.0.0.0",
            port=port,
            url_path=TELEGRAM_BOT_TOKEN,
            webhook_url=f"{external_url}/{TELEGRAM_BOT_TOKEN}",
        )
    else:
        log.info("Polling mode (local dev)")
        application.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log.info("Shutdown")

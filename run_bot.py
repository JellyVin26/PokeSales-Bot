"""PokéSales Bot entry point — local dev and Render.

Usage: python run_bot.py  (env: TELEGRAM_BOT_TOKEN, DATABASE_URL required)
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
    from pokebot.core.config import get_settings

    settings = get_settings()
    engine = make_engine(DATABASE_URL)
    async with engine.begin() as conn:
        from pokebot.db.models import Base
        await conn.run_sync(Base.metadata.create_all)
    log.info("DB initialized")

    app.bot_data["engine"] = engine
    app.bot_data["session"] = make_session_factory(engine)

    if settings.google_service_account and settings.google_sheet_id:
        try:
            from pokebot.services.sheets import make_client
            app.bot_data["sheets_client"] = make_client(settings.google_service_account).open_by_key(
                settings.google_sheet_id
            )
            log.info("Sheets sync enabled")
        except Exception as e:  # noqa: BLE001
            log.warning("Sheets disabled (%s)", e)
    else:
        log.info("Sheets sync disabled")

    register_handlers(app)  # sync function — do NOT await


def main() -> None:
    from telegram.ext import Application

    application = (
        Application.builder()
        .token(TELEGRAM_BOT_TOKEN)
        .post_init(_post_init)
        .build()
    )

    log.info("Starting polling…")
    application.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log.info("Shutdown")

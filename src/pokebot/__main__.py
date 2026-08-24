"""pokebot entry point: python -m pokebot"""

import asyncio
import logging
import os

from dotenv import load_dotenv
from openai import AsyncOpenAI
from telegram.ext import Application, CallbackQueryHandler

from .bot.handlers import register_handlers, on_button
from .core.config import get_settings
from .db.session import init_db, make_engine, make_session_factory

logging.basicConfig(
    format="%(asctime)s %(name)s %(levelname)s %(message)s", level=logging.INFO
)
log = logging.getLogger("pokebot")


def main() -> None:
    load_dotenv()
    settings = get_settings()

    if not settings.telegram_bot_token:
        raise SystemExit("TELEGRAM_BOT_TOKEN not set")
    if not settings.database_url:
        raise SystemExit("DATABASE_URL not set")

    async def post_init(app: Application) -> None:
        await init_db(settings.database_url)
        engine = make_engine(settings.database_url)
        app.bot_data["session_factory"] = make_session_factory(engine)
        app.bot_data["session"] = app.bot_data["session_factory"]()

        sheets_client = None
        sa_file = settings.google_service_account
        if sa_file and os.path.exists(sa_file):
            from .services.sheets import make_client

            sheets_client = make_client(sa_file)
        app.bot_data["sheets_client"] = sheets_client
        log.info("Init complete. Sheets sync %s.",
                 "enabled" if sheets_client else "disabled (no service account)")

    app = (
        Application.builder()
        .token(settings.telegram_bot_token)
        .post_init(post_init)
        .build()
    )

    register_handlers(app)

    log.info("Starting polling...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
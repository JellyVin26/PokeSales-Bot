"""Wrapper to capture all output on Render."""
import sys, traceback, os

# Redirect stderr to stdout so Render captures it
sys.stderr = sys.stdout

print(f"Python {sys.version}", flush=True)
print(f"TOKEN present: {bool(os.getenv('TELEGRAM_BOT_TOKEN'))}", flush=True)
print(f"DATABASE_URL present: {bool(os.getenv('DATABASE_URL'))}", flush=True)
print(f"PORT: {os.getenv('PORT', 'NOT SET')}", flush=True)

try:
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))
    print("sys.path OK", flush=True)

    from pokebot.bot.handlers import register_handlers
    print("handlers import OK", flush=True)

    from pokebot.db.session import make_engine, make_session_factory
    print("db import OK", flush=True)

    from telegram.ext import Application
    print("telegram import OK", flush=True)

    TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
    DB_URL = os.getenv("DATABASE_URL", "")

    print(f"Building application...", flush=True)
    app = Application.builder().token(TOKEN).build()
    print("Application built", flush=True)

    engine = make_engine(DB_URL)
    print(f"Engine created: {engine.url}", flush=True)

    from pokebot.db.models import Base
    import asyncio
    async def init():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    asyncio.run(init())
    print("DB initialized", flush=True)

    app.bot_data["engine"] = engine
    app.bot_data["session"] = make_session_factory(engine)
    register_handlers(app)
    print("Handlers registered", flush=True)

    external_url = os.getenv("RENDER_EXTERNAL_URL", "")
    if external_url:
        port = int(os.getenv("PORT", "10000"))
        print(f"Webhook mode: {external_url}:{port}", flush=True)
        app.run_webhook(
            listen="0.0.0.0",
            port=port,
            url_path=TOKEN,
            webhook_url=f"{external_url}/{TOKEN}",
        )
    else:
        print("Polling mode", flush=True)
        app.run_polling(drop_pending_updates=True)

except Exception:
    print(f"FATAL:\n{traceback.format_exc()}", flush=True)
    sys.exit(1)

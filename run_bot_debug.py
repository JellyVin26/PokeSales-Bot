"""Wrapper that sends crash reports to Telegram."""
import sys, traceback, os, json
import urllib.request

sys.stderr = sys.stdout
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.getenv("ALLOWED_USER_IDS", "").split(",")[0].strip()

def send_telegram(text):
    """Send a message to Telegram via Bot API."""
    if not TOKEN or not CHAT_ID:
        return
    try:
        url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
        data = json.dumps({"chat_id": int(CHAT_ID), "text": text[:4000]}).encode()
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=10)
    except Exception:
        pass

send_telegram(f"Bot starting...\nPython {sys.version[:30]}\nPORT={os.getenv('PORT','?')}")

try:
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

    from pokebot.bot.handlers import register_handlers
    send_telegram("handlers import OK")
    print("handlers OK", flush=True)

    from pokebot.db.session import make_engine, make_session_factory
    send_telegram("db import OK")
    print("db OK", flush=True)

    from telegram.ext import Application
    send_telegram("telegram import OK")
    print("telegram OK", flush=True)

    DB_URL = os.getenv("DATABASE_URL", "")
    external_url = os.getenv("RENDER_EXTERNAL_URL", "")

    app = Application.builder().token(TOKEN).build()
    send_telegram("app built")
    print("app built", flush=True)

    engine = make_engine(DB_URL)

    import asyncio
    async def init():
        async with engine.begin() as conn:
            from pokebot.db.models import Base
            await conn.run_sync(Base.metadata.create_all)
    asyncio.run(init())
    send_telegram("DB initialized")
    print("DB init OK", flush=True)

    app.bot_data["engine"] = engine
    app.bot_data["session"] = make_session_factory(engine)

    sheets_json = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "")
    sheet_id = os.getenv("GOOGLE_SHEET_ID", "")
    if sheets_json and sheet_id:
        send_telegram("sheets enabled")
    else:
        print("Sheets disabled", flush=True)

    register_handlers(app)
    send_telegram("handlers registered, starting webhook...")
    print("handlers registered", flush=True)

    if external_url:
        port = int(os.getenv("PORT", "10000"))
        send_telegram(f"webhook {external_url}:{port}")
        print(f"Webhook: {external_url}:{port}", flush=True)
        app.run_webhook(
            listen="0.0.0.0",
            port=port,
            url_path=TOKEN,
            webhook_url=f"{external_url}/{TOKEN}",
        )
    else:
        send_telegram("polling mode")
        print("Polling", flush=True)
        app.run_polling(drop_pending_updates=True)

except Exception:
    tb = traceback.format_exc()
    send_telegram(f"CRASH:\n{tb[:3500]}")
    print(f"FATAL:\n{tb}", flush=True)
    sys.exit(1)

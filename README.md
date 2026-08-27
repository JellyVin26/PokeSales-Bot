# PokéSales Bot

Telegram bot for recording Pokémon TCG card sales. Sends card photo + amount caption → bot identifies cards, confirms the sale, saves to Postgres, and syncs to Google Sheets.

Live at [@pokesales_bot](https://t.me/pokesales_bot), deployed on Render.

## How it works

1. `/start` → inline buttons (**New Sale**, **Recent Sales**, **Today Summary**, **Cancel**)
2. **New Sale** → send photo of cards + caption with amount (e.g. `RM 13 QR`)
3. Bot identifies cards via **OpenAI** → **Gemini** → **local perceptual-hash** fallback
4. Validates card names against [pokemontcg.io](https://pokemontcg.io)
5. Shows confirmation buttons (**✓ Confirm**, **✏️ Edit**, **❌ Cancel**)
6. Confirm → saves sale to Postgres + syncs to Google Sheets

If AI recognition fails, the sale is saved as a **draft** (S-XXXX) so nothing is lost.

## Commands

| Command | Description |
|---------|-------------|
| `/start` | Show menu |
| `/new` | New sale |
| `/sales` | Recent sales |
| `/today` | Today's summary |
| `/cancel` | Abort current sale |

## Card recognition fallbacks

Tried in order until one succeeds:

1. **OpenAI** (`gpt-4o-mini`) — needs paid `OPENAI_API_KEY`
2. **Gemini** (direct HTTP, `gemini-3.5-flash`) — needs `GEMINI_API_KEY` (Google Cloud key, starts `AQ.Ab8...`; free tier OK)
3. **Local perceptual hash** — matches photo against card images from pokemontcg.io, no key needed (slow on first use while DB loads)

## Environment variables

Set on Render (Dashboard → Environment; Render API cannot create env vars after service creation).

| Variable | Required | Purpose |
|----------|----------|---------|
| `TELEGRAM_BOT_TOKEN` | ✅ | Bot token from @BotFather |
| `DATABASE_URL` | ✅ | Postgres URL (`postgresql://...`) |
| `ALLOWED_USER_IDS` | ✅ | Telegram user IDs allowed to use the bot |
| `OPENAI_API_KEY` | ⭕ | OpenAI vision (must have credits) |
| `GEMINI_API_KEY` | ⭕ | Gemini fallback (Google Cloud `AQ.Ab8...` key) |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | ⭕ | Full service-account JSON (for Sheets sync) |
| `GOOGLE_SHEET_ID` | ⭕ | Google Sheet ID (not the URL) |

**Sheets access**: add the service-account email as Editor on the target Google Sheet (e.g. `pokebot@<project>.iam.gserviceaccount.com`).

## Running

### Local

```bash
python -m pip install -r requirements.txt
# create .env with the vars above
python -m pokebot.core  # or run_bot_debug.py
```

### Render (current)

- **Start command**: `python3 run_bot_debug.py`
- **Build command**: `python3 -m pip install -r requirements.txt`
- **Deploy**: `git push origin main` → auto-deploys
- **Webhook mode**: service must bind a port (`PORT`) for Render health check to pass. Webhook URL: `https://<service>.onrender.com/<TELEGRAM_BOT_TOKEN>`

## Gotchas

- Render free tier = 512MB RAM → **no torch/MobileNetV2** (OOM). Use OpenAI/Gemini instead.
- Render API **cannot create/update env vars post-service** → manage via Dashboard.
- `bot_data["session"]` is an `async_sessionmaker` *factory*, not a session — handlers must use `async with factory() as session:`.
- Telegram IDs exceed int32 → model uses `BigInteger` for `telegram_user_id`.
- `run_bot_debug.py` has an inline token fallback (security risk) — remove once env var confirmed working.

## Database

Modeled with SQLAlchemy async (asyncpg). Tables: `users`, `cards`, `sales`, `sale_items`, `sale_photos`, `sheet_sync_queue`. Recreated on startup (`create_all`), with FK constraints on `sale_items`/`sale_photos`.

## License

MIT

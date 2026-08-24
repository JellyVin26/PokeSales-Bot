# pokebot - Pokémon TCG Sales Recorder Bot

## Overview

A Telegram bot for recording Pokémon card sales with AI-powered card recognition,
amount extraction, validation against Pokémon TCG database, and Google Sheets
synchronization.

## Quick Start

```bash
# Install dependencies
cd pokebot
python -m pip install -e ".[dev]"

# Create .env file
cp .env.example .env
# Fill in your values

# Run the bot
python -m pokebot.bot
```

## Project Structure

```
pokebot/
├── pyproject.toml          # Project config + dependencies
├── .env.example            # Environment variables template
├── src/pokebot/            # Source package
│   ├── __init__.py
│   ├── __main__.py         # Entry point
│   ├── core/               # Core logic
│   │   ├── __init__.py
│   │   ├── config.py       # Configuration
│   │   ├── parser.py       # Amount/payment extraction
│   │   └── validator.py    # Validation logic
│   ├── db/                 # Database layer
│   │   ├── __init__.py
│   │   ├── models.py       # SQLAlchemy models
│   │   ├── migrations/     # Alembic migrations
│   │   └── queries.py      # DB queries
│   ├── services/           # Service integrations
│   │   ├── __init__.py
│   │   ├── ai.py           # Vision model integration
│   │   ├── cards.py        # Card database API
│   │   └── sheets.py       # Google Sheets sync
│   └── bot/                # Telegram bot
│       ├── __init__.py
│       ├── handlers.py     # Update handlers
│       ├── commands.py     # Bot commands
│       └── states.py       # Conversation states
├── tests/                  # Test suite
│   ├── __init__.py
│   ├── test_parser.py
│   ├── test_db.py
│   └── test_ai.py
└── docs/                   # Documentation
```

## Configuration

Set these environment variables in `.env`:

```
DATABASE_URL="postgresql://user:password@localhost:5432/nos"
TELEGRAM_BOT_TOKEN="your_telegram_bot_token"
OPENAI_API_KEY="your_openai_api_key"
GOOGLE_SERVICE_ACCOUNT="path/to/service_account.json"
ALLOWED_USER_IDS="123456789,987654321"
```

## License

MIT
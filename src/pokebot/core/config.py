"""Config from env vars."""

import os
from dataclasses import dataclass, field


def _ids(raw: str) -> list[int]:
    return [int(x) for x in raw.split(",") if x.strip()]


@dataclass
class Settings:
    telegram_bot_token: str = field(default_factory=lambda: os.getenv("TELEGRAM_BOT_TOKEN", ""))
    database_url: str = field(default_factory=lambda: os.getenv("DATABASE_URL", ""))
    openai_api_key: str = field(default_factory=lambda: os.getenv("OPENAI_API_KEY", ""))
    google_service_account: str = field(
        default_factory=lambda: os.getenv("GOOGLE_SERVICE_ACCOUNT", "")
    )
    google_sheet_id: str = field(default_factory=lambda: os.getenv("GOOGLE_SHEET_ID", ""))
    allowed_user_ids: list[int] = field(
        default_factory=lambda: _ids(os.getenv("ALLOWED_USER_IDS", ""))
    )


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
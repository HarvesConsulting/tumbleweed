"""Конфігурація TumbleWeed."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")


@dataclass(frozen=True)
class Settings:
    bot_token: str
    webhook_url: str
    turso_url: str
    turso_token: str
    rentalert_bot_url: str
    env: str
    log_level: str
    parser_timeout: int
    parser_delay_min: float
    parser_delay_max: float

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            bot_token=os.getenv("TUMBLEWEED_BOT_TOKEN", ""),
            webhook_url=os.getenv("TUMBLEWEED_WEBHOOK_URL", ""),
            turso_url=os.getenv("TURSO_DATABASE_URL", ""),
            turso_token=os.getenv("TURSO_AUTH_TOKEN", ""),
            rentalert_bot_url=os.getenv("RENTALERT_BOT_URL", "https://t.me/RentAlertBot"),
            env=os.getenv("ENV", "dev"),
            log_level=os.getenv("LOG_LEVEL", "INFO"),
            parser_timeout=int(os.getenv("PARSER_TIMEOUT", "20")),
            parser_delay_min=float(os.getenv("PARSER_DELAY_MIN", "1.5")),
            parser_delay_max=float(os.getenv("PARSER_DELAY_MAX", "3.5")),
        )


settings = Settings.from_env()
PROJECT_ROOT_PATH = PROJECT_ROOT
DATA_DIR = PROJECT_ROOT / "data"

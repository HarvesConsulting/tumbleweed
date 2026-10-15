"""Ініціалізація Telegram-бота TumbleWeed (sync, без PTB Application).

Замінює build_application() на build_context().
PTB Application більше НЕ використовується — усе через dispatcher.
"""
from __future__ import annotations

import logging

from tumbleweed.config import settings
from tumbleweed.db.client import TursoClient
from tumbleweed.services.dispatcher import BotContext
from tumbleweed.services.telegram_client import TelegramClient

log = logging.getLogger(__name__)


def build_context() -> BotContext:
    """Створює BotContext з TursoClient + TelegramClient.

    Викликається один раз у webhook.py (lazy startup).

    Raises:
        RuntimeError: якщо bot_token не задано.
    """
    if not settings.bot_token:
        raise RuntimeError(
            "TUMBLEWEED_BOT_TOKEN не задано. Перевір .env"
        )

    if not settings.turso_url or not settings.turso_token:
        raise RuntimeError(
            "TURSO_DATABASE_URL або TURSO_AUTH_TOKEN не задано"
        )

    client = TursoClient(settings.turso_url, settings.turso_token)
    log.info("✅ Turso client створено")

    notifier = TelegramClient(settings.bot_token)
    log.info("✅ TelegramClient створено")

    ctx = BotContext(
        client=client,
        notifier=notifier,
        rentalert_url=getattr(settings, "rentalert_bot_url", ""),
    )
    log.info("✅ BotContext готовий")
    return ctx

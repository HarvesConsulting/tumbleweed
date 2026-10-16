"""Ініціалізація Telegram-бота TumbleWeed (sync, без PTB Application).

Замінює build_application() на build_context().
PTB Application більше НЕ використовується — усе через dispatcher.
"""
from __future__ import annotations

import asyncio
import logging

import httpx

from tumbleweed.config import settings
from tumbleweed.db.client import TursoClient
from tumbleweed.services.dispatcher import BotContext, handle_update
from tumbleweed.services.telegram_client import TelegramClient

log = logging.getLogger(__name__)


def build_context() -> BotContext:
    """Створює BotContext з TursoClient + TelegramClient.

    Викликається один раз у webhook.py (lazy startup).

    Raises:
        RuntimeError: якщо bot_token не задано.
    """
    if not settings.bot_token:
        raise RuntimeError("TUMBLEWEED_BOT_TOKEN не задано. Перевір .env")

    if not settings.turso_url or not settings.turso_token:
        raise RuntimeError("TURSO_DATABASE_URL або TURSO_AUTH_TOKEN не задано")

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


async def run_polling() -> None:
    """Простий long-polling без PTB Application.

    Використовується для локальної розробки (scripts/run_bot.py).
    У проді бот працює через webhook (webhook.py).
    """
    ctx = build_context()
    bot_token = settings.bot_token
    api_url = f"https://api.telegram.org/bot{bot_token}"

    # Telegram не дозволяє одночасно webhook і getUpdates.
    # Тому перед polling-ом — прибираємо webhook.
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(f"{api_url}/deleteWebhook")
        resp = r.json()
        log.info("deleteWebhook: %s", resp.get("description", "OK"))

    offset = 0
    log.info("🎧 Polling started. Ctrl+C to stop.")

    async with httpx.AsyncClient(timeout=60) as client:
        while True:
            try:
                r = await client.get(
                    f"{api_url}/getUpdates",
                    params={"offset": offset, "timeout": 30},
                )
                data = r.json()
                if not data.get("ok"):
                    log.error("getUpdates failed: %s", data)
                    await asyncio.sleep(5)
                    continue

                for update in data.get("result", []):
                    update_id = update["update_id"]
                    offset = update_id + 1
                    try:
                        handle_update(update, ctx)
                    except Exception as e:
                        log.exception("handle_update: %s", e)

            except asyncio.CancelledError:
                log.info("👋 Polling stopped")
                break
            except Exception as e:
                log.exception("polling loop: %s", e)
                await asyncio.sleep(5)

"""Диспетчер Telegram update'ів (sync, без PTB Application).

Приймає update (dict від Telegram), викликає потрібний обробник.
Замінює PTB Application + ConversationHandler.

Точка входу: handle_update(update_dict, ctx).

Логіка:
  1. callback_query → callbacks.handle_callback
  2. message:
     a. Якщо це reply-кнопка → скинути стан і обробити
     b. Якщо FSM-стан очікування тексту → обробити текст
     c. Якщо команда (/start, ...) → handlers.handle_command
     d. Невідомий текст → handlers.send_main_menu
"""
from __future__ import annotations

import logging
from typing import Any

from tumbleweed.bot import callbacks
from tumbleweed.bot import handlers
from tumbleweed.bot import states
from tumbleweed.db.client import TursoClient
from tumbleweed.services.telegram_client import TelegramClient

log = logging.getLogger(__name__)


# ───────────────────────────────────────────────────────
# BotContext
# ───────────────────────────────────────────────────────

class BotContext:
    """Залежності, які потрібні обробникам."""

    def __init__(
        self,
        client: TursoClient,
        notifier: TelegramClient,
        rentalert_url: str = "",
    ) -> None:
        self.client = client
        self.notifier = notifier
        self.rentalert_url = rentalert_url

    def __repr__(self) -> str:
        return f"BotContext(client={id(self.client)}, notifier={id(self.notifier)})"


# ───────────────────────────────────────────────────────
# Головна точка входу
# ───────────────────────────────────────────────────────

def handle_update(update_dict: dict[str, Any], ctx: BotContext) -> None:
    """Обробляє один Telegram update."""

    # 1. Callback query (inline кнопки)
    if "callback_query" in update_dict:
        callbacks.handle_callback(update_dict["callback_query"], ctx)
        return

    # 2. Message
    message = update_dict.get("message")
    if not message:
        return

    chat_id = str(message["chat"]["id"])
    text = (message.get("text") or "").strip()

    if not text:
        # Немає тексту (фото, стікер, тощо) — ігноруємо
        return

        # 2a. Reply-кнопка — найвищий пріоритет (перебиває FSM)
    if handlers.is_reply_button(text):
        states.clear_state(chat_id)
        states.clear_user_data(chat_id)
        handlers.handle_reply_button(chat_id, text, ctx)
        return

    # 2b. Команда — ПЕРЕД FSM (щоб /start працював з будь-якого стану)
    if text.startswith("/"):
        states.clear_state(chat_id)
        states.clear_user_data(chat_id)
        handlers.handle_command(chat_id, text, ctx)
        return

    # 2c. FSM: чи користувач у стані очікування тексту?
    state = states.get_state(chat_id)
    if state is not None:
        if state == states.STATE_WAITING_CITY_QUERY:
            callbacks.handle_city_text(chat_id, text, ctx)
            return
        if state == states.STATE_WAITING_SUBCATEGORY_QUERY:
            callbacks.handle_subcategory_text(chat_id, text, ctx)
            return
        if state == states.STATE_WAITING_FEEDBACK:
            handlers.handle_feedback(chat_id, text, ctx)
            return

    # 2d. Невідомий текст → головне меню
    handlers.send_main_menu(chat_id, ctx)

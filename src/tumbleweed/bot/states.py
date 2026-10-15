"""FSM-стани для TumbleWeed-бота.

Дві частини:
1. ConversationHandler State (IntEnum) — для діалогу налаштування профілю.
2. Простий рядковий FSM — для очікування текстового вводу (feedback, пошук).

При перезапуску застосунку стан скидається.
"""
from __future__ import annotations

import threading
from enum import IntEnum, auto


# ───────────────────────────────────────────────────────
# ConversationHandler (для налаштування профілю)
# ───────────────────────────────────────────────────────

class State(IntEnum):
    """Стани діалогу налаштування профілю користувача."""

    CHOOSING_COUNTRY = auto()
    CHOOSING_CITY = auto()
    CHOOSING_CITY_QUERY = auto()
    CHOOSING_CITY_PICK = auto()
    CHOOSING_CATEGORY = auto()
    CHOOSING_SUBCATEGORY_QUERY = auto()
    CHOOSING_SUBCATEGORY_PICK = auto()
    CHOOSING_JOB_TYPE = auto()
    CHOOSING_EXPERIENCE = auto()
    DONE = auto()


# ───────────────────────────────────────────────────────
# Простий FSM (для очікування тексту)
# ───────────────────────────────────────────────────────

# Стани очікування
STATE_WAITING_FEEDBACK = "waiting_feedback"
STATE_WAITING_CITY_QUERY = "waiting_city_query"

_states: dict[str, str] = {}
_lock = threading.Lock()


def set_state(chat_id: str | int, state: str) -> None:
    """Встановити стан очікування."""
    with _lock:
        _states[str(chat_id)] = state


def get_state(chat_id: str | int) -> str | None:
    """Отримати стан (або None)."""
    with _lock:
        return _states.get(str(chat_id))


def clear_state(chat_id: str | int) -> None:
    """Скинути стан."""
    with _lock:
        _states.pop(str(chat_id), None)


def clear_all() -> None:
    """Очистити всі стани (для тестів)."""
    with _lock:
        _states.clear()

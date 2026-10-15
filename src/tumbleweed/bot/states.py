"""FSM-стани для TumbleWeed-бота (sync, без ConversationHandler).

Простий рядковий FSM:
    set_state(chat_id, "waiting_city")
    state = get_state(chat_id)
    clear_state(chat_id)

При перезапуску застосунку стан скидається.
Це нормально — очікування недовге (хвилина).
"""
from __future__ import annotations

import threading

# ───────────────────────────────────────────────────────
# Стани (рядкові константи)
# ───────────────────────────────────────────────────────

# Очікування текстового вводу
STATE_WAITING_CITY = "waiting_city"
STATE_WAITING_CITY_QUERY = "waiting_city_query"
STATE_WAITING_FEEDBACK = "waiting_feedback"
STATE_WAITING_SUBCATEGORY_QUERY = "waiting_subcategory_query"

# Очікування натискання inline-кнопки (для вибору)
STATE_CHOOSING_COUNTRY = "choosing_country"
STATE_CHOOSING_CITY = "choosing_city"
STATE_CHOOSING_CATEGORY = "choosing_category"
STATE_CHOOSING_SUBCATEGORY = "choosing_subcategory"
STATE_CHOOSING_JOB_TYPE = "choosing_job_type"
STATE_CHOOSING_EXPERIENCE = "choosing_experience"

# ───────────────────────────────────────────────────────
# Сховище (in-memory)
# ───────────────────────────────────────────────────────

_states: dict[str, str] = {}
_lock = threading.Lock()


def set_state(chat_id: str | int, state: str) -> None:
    """Встановити стан."""
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

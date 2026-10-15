"""FSM-стани + тимчасове сховище даних для TumbleWeed-бота.

Простий рядковий FSM + user_data (dict на чат):
    set_state(chat_id, "waiting_city")
    state = get_state(chat_id)
    clear_state(chat_id)

    set_user_data(chat_id, {"country": "ua", "category": "it"})
    data = get_user_data(chat_id)   # {"country": "ua", "category": "it"}
    clear_user_data(chat_id)

При перезапуску застосунку все скидається.
Це нормально — очікування недовге (хвилина).
"""
from __future__ import annotations

import threading
from typing import Any

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
# Сховище: стан (FSM)
# ───────────────────────────────────────────────────────

_states: dict[str, str] = {}
_states_lock = threading.Lock()


def set_state(chat_id: str | int, state: str) -> None:
    """Встановити стан."""
    with _states_lock:
        _states[str(chat_id)] = state


def get_state(chat_id: str | int) -> str | None:
    """Отримати стан (або None)."""
    with _states_lock:
        return _states.get(str(chat_id))


def clear_state(chat_id: str | int) -> None:
    """Скинути стан."""
    with _states_lock:
        _states.pop(str(chat_id), None)


# ───────────────────────────────────────────────────────
# Сховище: тимчасові дані (user_data)
# ───────────────────────────────────────────────────────

_user_data: dict[str, dict[str, Any]] = {}
_user_data_lock = threading.Lock()


def set_user_data(chat_id: str | int, data: dict[str, Any]) -> None:
    """Замінити весь user_data."""
    with _user_data_lock:
        _user_data[str(chat_id)] = dict(data)


def get_user_data(chat_id: str | int) -> dict[str, Any]:
    """Отримати user_data (або порожній dict)."""
    with _user_data_lock:
        return dict(_user_data.get(str(chat_id), {}))


def update_user_data(chat_id: str | int, **kwargs: Any) -> None:
    """Оновити user_data (merge)."""
    with _user_data_lock:
        key = str(chat_id)
        current = _user_data.get(key, {})
        current.update(kwargs)
        _user_data[key] = current


def clear_user_data(chat_id: str | int) -> None:
    """Скинути user_data."""
    with _user_data_lock:
        _user_data.pop(str(chat_id), None)


# ───────────────────────────────────────────────────────
# Повне очищення
# ───────────────────────────────────────────────────────

def clear_all(chat_id: str | int | None = None) -> None:
    """Очистити все (для тестів або для одного чату)."""
    if chat_id is None:
        with _states_lock:
            _states.clear()
        with _user_data_lock:
            _user_data.clear()
    else:
        clear_state(chat_id)
        clear_user_data(chat_id)

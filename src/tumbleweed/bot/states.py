"""Стани ConversationHandler для TumbleWeed-бота.

Використовуються у bot/handlers.py для покрокового діалогу:
  /start → COUNTRY → CITY → PROFESSION → JOB_TYPE → EXPERIENCE → DONE
"""
from enum import IntEnum, auto


class State(IntEnum):
    """Стани діалогу налаштування профілю користувача."""

    CHOOSING_COUNTRY = auto()
    CHOOSING_CITY = auto()
    CHOOSING_PROFESSION = auto()
    CHOOSING_JOB_TYPE = auto()
    CHOOSING_EXPERIENCE = auto()
    DONE = auto()
"""Стани ConversationHandler для TumbleWeed-бота.

Флоу:
  CHOOSING_COUNTRY → CHOOSING_CITY → CHOOSING_CITY_QUERY
  → CHOOSING_CATEGORY → CHOOSING_SUBCATEGORY_QUERY
  → CHOOSING_SUBCATEGORY_PICK
  → CHOOSING_JOB_TYPE → CHOOSING_EXPERIENCE → DONE
"""
from enum import IntEnum, auto


class State(IntEnum):
    """Стани діалогу налаштування профілю користувача."""

    CHOOSING_COUNTRY = auto()
    CHOOSING_CITY = auto()                 # показ популярних + кнопка "Ввести"
    CHOOSING_CITY_QUERY = auto()           # користувач вводить назву міста
    CHOOSING_CITY_PICK = auto()            # вибирає з результатів пошуку
    CHOOSING_CATEGORY = auto()
    CHOOSING_SUBCATEGORY_QUERY = auto()
    CHOOSING_SUBCATEGORY_PICK = auto()
    CHOOSING_JOB_TYPE = auto()
    CHOOSING_EXPERIENCE = auto()
    DONE = auto()

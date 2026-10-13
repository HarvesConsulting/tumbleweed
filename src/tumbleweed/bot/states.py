"""Стани ConversationHandler для TumbleWeed-бота.

Флоу:
  CHOOSING_COUNTRY → CHOOSING_CITY → CHOOSING_CATEGORY
  → CHOOSING_SUBCATEGORY_QUERY → CHOOSING_SUBCATEGORY_PICK
  → CHOOSING_JOB_TYPE → CHOOSING_EXPERIENCE → DONE
"""
from enum import IntEnum, auto


class State(IntEnum):
    """Стани діалогу налаштування профілю користувача."""

    CHOOSING_COUNTRY = auto()
    CHOOSING_CITY = auto()
    CHOOSING_CATEGORY = auto()               # сфера (agro, IT, bud)
    CHOOSING_SUBCATEGORY_QUERY = auto()      # користувач вводить слово
    CHOOSING_SUBCATEGORY_PICK = auto()       # вибирає з результатів (toggle)
    CHOOSING_JOB_TYPE = auto()
    CHOOSING_EXPERIENCE = auto()
    DONE = auto()

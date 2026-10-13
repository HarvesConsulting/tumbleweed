"""Inline-клавіатури для TumbleWeed-бота.

Callback_data формат: "<action>:<value>"
  country:ua        — обрана країна
  city:kyiv         — обране місто
  prof:it           — обрана професія
  jobtype:full      — тип зайнятості
  exp:any           — досвід
  skip:<step>       — пропустити крок
  action:<cmd>      — службові команди (settings, stop, ...)
"""
from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup


# ───────────────────────────────────────────────────────
# Крок 1. Вибір країни
# ───────────────────────────────────────────────────────

COUNTRY_FLAGS = {
    "ua": "🇺🇦 Україна",
    "pl": "🇵🇱 Польща",
    "ro": "🇷🇴 Румунія",
    # Резерв — коли додамо парсери:
    # "de": "🇩🇪 Німеччина",
    # "pt": "🇵🇹 Португалія",
    # "bg": "🇧🇬 Болгарія",
}


def country_keyboard() -> InlineKeyboardMarkup:
    """Клавіатура вибору країни — 2 колонки."""
    items = list(COUNTRY_FLAGS.items())
    rows = []
    for i in range(0, len(items), 2):
        row = [
            InlineKeyboardButton(label, callback_data=f"country:{code}")
            for code, label in items[i : i + 2]
        ]
        rows.append(row)
    return InlineKeyboardMarkup(rows)


# ───────────────────────────────────────────────────────
# Крок 2. Вибір міста
# ───────────────────────────────────────────────────────

# Мапа міст для бота (поки — не з каталогу; простіше для MVP)
CITIES: dict[str, list[tuple[str, str]]] = {
    # (slug, label)
    "ua": [
        ("kyiv", "Київ"),
        ("lviv", "Львів"),
        ("odesa", "Одеса"),
        ("kharkiv", "Харків"),
        ("dnipro", "Дніпро"),
    ],
    "pl": [
        ("warszawa", "Варшава"),
        ("krakow", "Краків"),
        ("wroclaw", "Вроцлав"),
        ("gdansk", "Гданськ"),
        ("poznan", "Познань"),
    ],
    "ro": [
        ("bucuresti", "Бухарест"),
    ],
}


def city_keyboard(country: str) -> InlineKeyboardMarkup:
    """Клавіатура вибору міста + кнопка «Будь-яке місто»."""
    cities = CITIES.get(country, [])
    rows: list[list[InlineKeyboardButton]] = []

    for i in range(0, len(cities), 2):
        row = [
            InlineKeyboardButton(label, callback_data=f"city:{slug}")
            for slug, label in cities[i : i + 2]
        ]
        rows.append(row)

    rows.append([
        InlineKeyboardButton("🌍 Будь-яке місто", callback_data="skip:city"),
    ])
    rows.append([
        InlineKeyboardButton("⬅️ Назад", callback_data="action:back_country"),
    ])
    return InlineKeyboardMarkup(rows)


# ───────────────────────────────────────────────────────
# Крок 3. Вибір професії (категорії)
# ───────────────────────────────────────────────────────

# Ключі мають відповідати data/jobs/professions_ua.json
PROFESSION_CATEGORIES = [
    ("it", "💻 IT / Програмування"),
    ("bud", "🏗 Будівництво"),
    ("med", "🏥 Медицина"),
    ("edu", "🎓 Освіта"),
    ("driver", "🚗 Водій / Кур'єр"),
    ("clean", "🧹 Прибирання"),
    ("sales", "🛒 Продажі"),
    ("food", "🍳 Ресторан"),
    ("factory", "🏭 Виробництво"),
    ("agro", "🌾 Сільське господарство"),
]


def profession_keyboard() -> InlineKeyboardMarkup:
    """Клавіатура вибору категорії професій — 1 колонка."""
    rows: list[list[InlineKeyboardButton]] = []

    for key, label in PROFESSION_CATEGORIES:
        rows.append([
            InlineKeyboardButton(label, callback_data=f"prof:{key}"),
        ])

    rows.append([
        InlineKeyboardButton("✏️ Ввести своє", callback_data="action:custom_prof"),
    ])
    rows.append([
        InlineKeyboardButton("🌍 Будь-яка", callback_data="skip:prof"),
    ])
    rows.append([
        InlineKeyboardButton("⬅️ Назад", callback_data="action:back_city"),
    ])
    return InlineKeyboardMarkup(rows)


# ───────────────────────────────────────────────────────
# Крок 4. Тип зайнятості
# ───────────────────────────────────────────────────────

JOB_TYPES = [
    ("full", "🕐 Повна"),
    ("part", "⏱ Часткова"),
    ("remote", "🏠 Віддалена"),
]


def job_type_keyboard() -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(label, callback_data=f"jobtype:{key}")]
        for key, label in JOB_TYPES
    ]
    rows.append([
        InlineKeyboardButton("🌍 Будь-який", callback_data="skip:jobtype"),
    ])
    return InlineKeyboardMarkup(rows)


# ───────────────────────────────────────────────────────
# Крок 5. Досвід
# ───────────────────────────────────────────────────────

EXPERIENCE = [
    ("no", "🌱 Без досвіду"),
    ("1-3", "🌿 1-3 роки"),
    ("3+", "🌳 3+ роки"),
]


def experience_keyboard() -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(label, callback_data=f"exp:{key}")]
        for key, label in EXPERIENCE
    ]
    rows.append([
        InlineKeyboardButton("🌍 Будь-який", callback_data="skip:exp"),
    ])
    return InlineKeyboardMarkup(rows)


# ───────────────────────────────────────────────────────
# Головне меню (після налаштування)
# ───────────────────────────────────────────────────────

def main_menu_keyboard(rentalert_url: str) -> InlineKeyboardMarkup:
    """Кнопки головного меню після завершення налаштування."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("⚙️ Налаштування", callback_data="action:settings"),
        ],
        [
            InlineKeyboardButton("⏸ Пауза", callback_data="action:pause"),
            InlineKeyboardButton("▶️ Увімкнути", callback_data="action:resume"),
        ],
        [
            InlineKeyboardButton("🏠 Хочу житло", url=rentalert_url),
        ],
    ])


# ───────────────────────────────────────────────────────
# Кнопка "Житло тут" на кожній вакансії
# ───────────────────────────────────────────────────────

def vacancy_keyboard(link: str, rentalert_url: str) -> InlineKeyboardMarkup:
    """Кнопки під вакансією: Відкрити / Житло тут / Ігнор."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔗 Відкрити", url=link),
        ],
        [
            InlineKeyboardButton("🏠 Житло тут", url=rentalert_url),
            InlineKeyboardButton("🚫 Ігнор", callback_data="action:ignore_vacancy"),
        ],
    ])
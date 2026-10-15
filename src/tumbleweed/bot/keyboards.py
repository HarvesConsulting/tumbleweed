"""Inline-клавіатури для TumbleWeed-бота.

Callback_data формат: "<action>:<value>"
  country:ua        — обрана країна
  city:kyiv         — обране місто
  prof:it           — обрана професія
  jobtype:full      — тип зайнятості
  exp:any           — досвід
  skip:<step>       — пропустити крок
  action:<cmd>      — службові команди (menu, change, my_job, toggle_notify)
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
}


def country_keyboard() -> InlineKeyboardMarkup:
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

def city_keyboard(country: str) -> InlineKeyboardMarkup:
    """Клавіатура вибору міста: топ-6 + «Ввести місто»."""
    from tumbleweed.services.city_search import popular_cities

    cities = popular_cities(country, limit=6)
    rows: list[list[InlineKeyboardButton]] = []

    # Топ-6 у 2 колонки
    for i in range(0, len(cities), 2):
        row = []
        for c in cities[i : i + 2]:
            row.append(InlineKeyboardButton(c.name, callback_data=f"city:{c.slug}"))
        rows.append(row)

    # Кнопка «Ввести місто текстом»
    rows.append([
        InlineKeyboardButton("✏️ Ввести місто", callback_data="action:enter_city"),
    ])
    rows.append([
        InlineKeyboardButton("🌍 Будь-яке місто", callback_data="skip:city"),
    ])
    rows.append([
        InlineKeyboardButton("⬅️ Назад", callback_data="action:back_country"),
    ])
    return InlineKeyboardMarkup(rows)


def city_results_keyboard(
    results: list,                       # list[City]
    query: str,
) -> InlineKeyboardMarkup:
    """Результати пошуку міста."""
    rows: list[list[InlineKeyboardButton]] = []

    for city in results:
        label = city.name
        if city.region:
            label += f" ({city.region})"
        rows.append([
            InlineKeyboardButton(label, callback_data=f"city:{city.slug}"),
        ])

    rows.append([
        InlineKeyboardButton("🔍 Спробувати ще", callback_data="action:enter_city"),
    ])
    rows.append([
        InlineKeyboardButton("🌍 Будь-яке місто", callback_data="skip:city"),
    ])
    rows.append([
        InlineKeyboardButton("⬅️ Назад", callback_data="action:back_country"),
    ])
    return InlineKeyboardMarkup(rows)


def city_empty_keyboard(query: str) -> InlineKeyboardMarkup:
    """Коли нічого не знайдено."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔍 Спробувати ще", callback_data="action:enter_city")],
        [InlineKeyboardButton("🌍 Будь-яке місто", callback_data="skip:city")],
        [InlineKeyboardButton("⬅️ Назад до країн", callback_data="action:back_country")],
    ])


# ───────────────────────────────────────────────────────
# Крок 3. Вибір сфери
# ───────────────────────────────────────────────────────

CATEGORIES = [
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


def category_keyboard() -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for key, label in CATEGORIES:
        rows.append([InlineKeyboardButton(label, callback_data=f"cat:{key}")])
    rows.append([
        InlineKeyboardButton("🌍 Будь-яка сфера", callback_data="skip:cat"),
    ])
    rows.append([
        InlineKeyboardButton("⬅️ Назад", callback_data="action:back_city"),
    ])
    return InlineKeyboardMarkup(rows)


# ───────────────────────────────────────────────────────
# Крок 3.1. Результати пошуку підкатегорій (toggle)
# ───────────────────────────────────────────────────────

def subcategory_results_keyboard(
    results: list,                # list[Subcategory]
    selected: set[str],
    category_key: str,
    category_label: str,
) -> InlineKeyboardMarkup:
    """Результати пошуку + toggle ✅/⬜ + кнопки внизу."""
    rows: list[list[InlineKeyboardButton]] = []

    for sub in results:
        mark = "✅" if sub.key in selected else "⬜"
        rows.append([InlineKeyboardButton(
            f"{mark} {sub.label}",
            callback_data=f"sub:{sub.key}",
        )])

    # Лічильник обраного
    if selected:
        rows.append([InlineKeyboardButton(
            f"— Обрано: {len(selected)} —",
            callback_data="noop",
        )])

    # ─── Кнопки внизу ───
    # 1) Головна дія — «Завершити вибір» (тільки якщо щось обрано)
    if selected:
        rows.append([InlineKeyboardButton(
            f"✅ Завершити вибір ({len(selected)})  →",
            callback_data="action:sub_done",
        )])
    else:
        # Якщо нічого не обрано — це «Пропустити»
        rows.append([InlineKeyboardButton(
            "⏭ Пропустити (будь-яка)",
            callback_data="action:sub_done",
        )])

    # 2) Другорядні дії
    rows.append([InlineKeyboardButton(
        "🔍 Додати ще підкатегорію",
        callback_data="action:search_again",
    )])
    rows.append([InlineKeyboardButton(
        f"🌍 Будь-яка в {category_label.split(' ', 1)[-1]}",
        callback_data="skip:sub",
    )])
    rows.append([InlineKeyboardButton(
        "⬅️ Назад до сфер",
        callback_data="action:back_category",
    )])
    return InlineKeyboardMarkup(rows)


def subcategory_empty_keyboard(category_label: str) -> InlineKeyboardMarkup:
    """Коли пошук нічого не знайшов."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔍 Спробувати ще", callback_data="action:search_again")],
        [InlineKeyboardButton(
            f"🌍 Будь-яка в {category_label.split(' ', 1)[-1]}",
            callback_data="skip:sub",
        )],
        [InlineKeyboardButton("⬅️ Назад до сфер", callback_data="action:back_category")],
    ])

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
# Головне меню (для профілю, що вже налаштований)
# ───────────────────────────────────────────────────────

def main_menu_keyboard(enabled: bool, rentalert_url: str) -> InlineKeyboardMarkup:
    """Головне меню з toggle-кнопкою сповіщень + дії."""
    toggle_label = "🔔 Сповіщення: УВІМК" if enabled else "🔕 Сповіщення: ВИМК"

    return InlineKeyboardMarkup([
        [InlineKeyboardButton(toggle_label, callback_data="action:toggle_notify")],
        [InlineKeyboardButton("✏️ Змінити сферу та підкатегорії", callback_data="action:change_filters")],
        [InlineKeyboardButton("📊 Моя робота", callback_data="action:my_job")],
        [InlineKeyboardButton("🏠 Знайти житло", url=rentalert_url)],
    ])


# ───────────────────────────────────────────────────────
# Кнопка "Знайти житло" під вакансією
# ───────────────────────────────────────────────────────

def vacancy_keyboard(link: str, rentalert_url: str) -> InlineKeyboardMarkup:
    """Кнопки під вакансією."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔗 Відкрити вакансію", url=link)],
        [
            InlineKeyboardButton("🏠 Знайти житло", url=rentalert_url),
            InlineKeyboardButton("🚫 Ігнор", callback_data="action:ignore_vacancy"),
        ],
    ])

# ───────────────────────────────────────────────────────
# Постійна Reply-клавіатура (як у RentAlert)
# ───────────────────────────────────────────────────────

from telegram import ReplyKeyboardMarkup, KeyboardButton


# Текстові мітки Reply-кнопок
BTN_MY_VACANCIES = "📊 Мої вакансії"
BTN_MY_PROFILE = "👤 Мій профіль"
BTN_CHANGE = "✏️ Фільтри"
BTN_RENT = "🏠 Житло"
BTN_TOGGLE_ON = "🔔 Сповіщення: УВІМК"
BTN_TOGGLE_OFF = "🔕 Сповіщення: ВИМК"
BTN_HELP = "❓ Допомога"


def main_reply_keyboard(enabled: bool) -> ReplyKeyboardMarkup:
    """Головне меню — 6 кнопок у 3 ряди (як у RentAlert)."""
    toggle_label = BTN_TOGGLE_ON if enabled else BTN_TOGGLE_OFF
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton(BTN_MY_VACANCIES), KeyboardButton(BTN_MY_PROFILE)],
            [KeyboardButton(BTN_CHANGE), KeyboardButton(BTN_RENT)],
            [KeyboardButton(toggle_label), KeyboardButton(BTN_HELP)],
        ],
        resize_keyboard=True,
        is_persistent=True,
    )

"""Клавіатури для TumbleWeed-бота.

Усі функції повертають dict у форматі Telegram API:
  - inline: {"inline_keyboard": [[{"text": ..., "callback_data": ...}, ...], ...]}
  - reply:  {"keyboard": [[{"text": ...}, ...]], "resize_keyboard": True, ...}

НЕ залежать від python-telegram-bot.

Callback_data формат: "<action>:<value>"
  country:ua        — обрана країна
  city:kyiv         — обране місто
  cat:it            — обрана сфера
  sub:it_backend    — обрана підкатегорія (фінальний вибір)
  jobtype:full      — тип зайнятості
  exp:no            — досвід
  skip:<step>       — пропустити крок
  action:<cmd>      — службові команди
  sub_del:<id>      — видалити підписку
  sub_toggle:<id>   — увімкнути/вимкнути підписку
"""
from __future__ import annotations

from typing import Any

# ───────────────────────────────────────────────────────
# Reply-клавіатура (знизу екрана) — ГОЛОВНЕ МЕНЮ
# ───────────────────────────────────────────────────────

BTN_MY_VACANCIES = "📄 Моє резюме"
BTN_FIND_JOB = "🔍 Знайти роботу"          # NEW: почати новий пошук (підписку)
BTN_MY_SUBS = "📋 Мої пошуки"              # NEW: список підписок
BTN_RENT = "🏠 Житло"
BTN_TOGGLE_ON = "🔔 Сповіщення: УВІМК"
BTN_TOGGLE_OFF = "🔕 Сповіщення: ВИМК"
BTN_HELP = "❓ Допомога"


def main_reply_keyboard(enabled: bool) -> dict[str, Any]:
    """Головне меню — 6 кнопок у 3 ряди."""
    toggle_label = BTN_TOGGLE_ON if enabled else BTN_TOGGLE_OFF
    return {
        "keyboard": [
            [{"text": BTN_MY_VACANCIES}, {"text": BTN_MY_SUBS}],
            [{"text": BTN_FIND_JOB}, {"text": BTN_RENT}],
            [{"text": toggle_label}, {"text": BTN_HELP}],
        ],
        "resize_keyboard": True,
        "is_persistent": True,
    }


def remove_reply_keyboard() -> dict[str, Any]:
    """Прибирає reply-клавіатуру (для команд /stop, /cancel)."""
    return {"remove_keyboard": True}


# ───────────────────────────────────────────────────────
# Inline: Вибір країни
# ───────────────────────────────────────────────────────

COUNTRY_FLAGS = {
    "ua": "🇺🇦 Україна",
    "pl": "🇵🇱 Польща",
    "ro": "🇷🇴 Румунія",
}


def country_keyboard() -> dict[str, Any]:
    """Inline: вибір країни (2 у ряд)."""
    items = list(COUNTRY_FLAGS.items())
    rows: list[list[dict[str, str]]] = []
    for i in range(0, len(items), 2):
        row = [
            {"text": label, "callback_data": f"country:{code}"}
            for code, label in items[i : i + 2]
        ]
        rows.append(row)
    return {"inline_keyboard": rows}


# ───────────────────────────────────────────────────────
# Inline: Вибір міста
# ───────────────────────────────────────────────────────

def city_keyboard(country: str) -> dict[str, Any]:
    """Inline: топ-6 міст + «Ввести місто» + «Будь-яке» + «Назад»."""
    from tumbleweed.services.city_search import popular_cities

    cities = popular_cities(country, limit=6)
    rows: list[list[dict[str, str]]] = []

    for i in range(0, len(cities), 2):
        row = [
            {"text": c.name, "callback_data": f"city:{c.slug}"}
            for c in cities[i : i + 2]
        ]
        rows.append(row)

    rows.append([{"text": "✏️ Ввести місто", "callback_data": "action:enter_city"}])
    rows.append([{"text": "🌍 Будь-яке місто", "callback_data": "skip:city"}])
    rows.append([{"text": "⬅️ Назад", "callback_data": "action:back_country"}])
    return {"inline_keyboard": rows}


def city_results_keyboard(results: list, query: str) -> dict[str, Any]:
    """Inline: результати пошуку міста."""
    rows: list[list[dict[str, str]]] = []
    for city in results:
        label = city.name
        if city.region:
            label += f" ({city.region})"
        rows.append([{"text": label, "callback_data": f"city:{city.slug}"}])

    rows.append([{"text": "🔍 Спробувати ще", "callback_data": "action:enter_city"}])
    rows.append([{"text": "🌍 Будь-яке місто", "callback_data": "skip:city"}])
    rows.append([{"text": "⬅️ Назад", "callback_data": "action:back_country"}])
    return {"inline_keyboard": rows}


def city_empty_keyboard(query: str) -> dict[str, Any]:
    """Inline: нічого не знайдено."""
    return {
        "inline_keyboard": [
            [{"text": "🔍 Спробувати ще", "callback_data": "action:enter_city"}],
            [{"text": "🌍 Будь-яке місто", "callback_data": "skip:city"}],
            [{"text": "⬅️ Назад до країн", "callback_data": "action:back_country"}],
        ]
    }


# ───────────────────────────────────────────────────────
# Inline: Вибір сфери
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


def category_keyboard() -> dict[str, Any]:
    """Inline: вибір сфери."""
    rows: list[list[dict[str, str]]] = [
        [{"text": label, "callback_data": f"cat:{key}"}]
        for key, label in CATEGORIES
    ]
    rows.append([{"text": "🌍 Будь-яка сфера", "callback_data": "skip:cat"}])
    rows.append([{"text": "⬅️ Назад", "callback_data": "action:back_city"}])
    return {"inline_keyboard": rows}


def subcategory_results_keyboard(
    results: list,
    category_key: str,
    category_label: str,
    selected: str = "",
) -> dict[str, Any]:
    """Inline: результати пошуку підкатегорій — ОДНА підкатегорія.

    Args:
        results: список Subcategory
        category_key: ключ сфери
        category_label: людська назва сфери
        selected: ключ обраної підкатегорії (для візуального ✅)
    """
    rows: list[list[dict[str, str]]] = []

    for sub in results:
        mark = "✅" if sub.key == selected else "◻️"
        rows.append([
            {"text": f"{mark} {sub.label}", "callback_data": f"sub:{sub.key}"},
        ])

    cat_short = category_label.split(" ", 1)[-1]
    rows.append([
        {"text": f"🌍 Будь-яка в {cat_short}",
         "callback_data": "skip:sub"},
    ])
    rows.append([
        {"text": "🔍 Новий пошук",
         "callback_data": "action:search_again"},
    ])
    rows.append([
        {"text": "⬅️ Назад до сфер",
         "callback_data": "action:back_category"},
    ])
    return {"inline_keyboard": rows}


def subcategory_empty_keyboard(category_label: str) -> dict[str, Any]:
    """Inline: підкатегорій не знайдено."""
    cat_short = category_label.split(" ", 1)[-1]
    return {
        "inline_keyboard": [
            [{"text": "🔍 Спробувати ще", "callback_data": "action:search_again"}],
            [{"text": f"🌍 Будь-яка в {cat_short}", "callback_data": "skip:sub"}],
            [{"text": "⬅️ Назад до сфер", "callback_data": "action:back_category"}],
        ]
    }


# ───────────────────────────────────────────────────────
# Inline: Тип зайнятості / Досвід
# ───────────────────────────────────────────────────────

JOB_TYPES = [
    ("full", "🕐 Повна"),
    ("part", "⏱ Часткова"),
    ("remote", "🏠 Віддалена"),
]


def job_type_keyboard(selected: list[str] | None = None) -> dict[str, Any]:
    """Inline: тип зайнятості (мультивибір ✅/⬜ + Далі)."""
    selected = selected or []
    rows: list[list[dict[str, str]]] = []
    for key, label in JOB_TYPES:
        mark = "✅" if key in selected else "⬜"
        rows.append([{"text": f"{mark} {label}", "callback_data": f"jobtype:{key}"}])
    rows.append([{"text": "➡️ Далі", "callback_data": "action:jobtype_done"}])
    rows.append([{"text": "🌍 Будь-який", "callback_data": "skip:jobtype"}])
    return {"inline_keyboard": rows}


EXPERIENCE = [
    ("all", "🌍 Будь-який"),
    ("no", "🌱 Без досвіду"),
    ("1-3", "🌿 1-3 роки"),
    ("3+", "🌳 3+ роки"),
]


def experience_keyboard() -> dict[str, Any]:
    """Inline: досвід (один вибір)."""
    rows = [
        [{"text": label, "callback_data": f"exp:{key}"}]
        for key, label in EXPERIENCE
    ]
    return {"inline_keyboard": rows}


# ───────────────────────────────────────────────────────
# Inline: Список підписок ("Мої пошуки")
# ───────────────────────────────────────────────────────

def subscriptions_list_keyboard(subs: list) -> dict[str, Any]:
    """Inline: список підписок з діями.

    Args:
        subs: список Subscription

    Returns:
        Inline-клавіатура. Для кожної підписки:
          - рядок [🗑 Видалити N] [⏸/▶️ N]
        В кінці — [➕ Додати ще] (він же початок flow).
    """
    rows: list[list[dict[str, str]]] = []

    for i, sub in enumerate(subs, start=1):
        toggle_label = "⏸ Пауза" if sub.enabled else "▶️ Увімкнути"
        rows.append([
            {"text": f"🗑 Видалити {i}", "callback_data": f"sub_del:{sub.id}"},
            {"text": f"{toggle_label} {i}", "callback_data": f"sub_toggle:{sub.id}"},
        ])

    rows.append([
        {"text": "➕ Додати ще", "callback_data": "action:add_sub"},
    ])
    return {"inline_keyboard": rows}


def subscription_created_keyboard(sub_id: int) -> dict[str, Any]:
    """Inline: після створення підписки."""
    return {
        "inline_keyboard": [
            [
                {"text": "📋 Мої пошуки", "callback_data": "action:show_subs"},
                {"text": "➕ Ще один", "callback_data": "action:add_sub"},
            ],
        ]
    }


# ───────────────────────────────────────────────────────
# Inline: Кнопки під вакансією
# ───────────────────────────────────────────────────────

def vacancy_keyboard(link: str, rentalert_url: str) -> dict[str, Any]:
    """Inline: кнопки під вакансією."""
    return {
        "inline_keyboard": [
            [{"text": "🔗 Відкрити вакансію", "url": link}],
            [
                {"text": "🏠 Знайти житло", "url": rentalert_url},
                {"text": "🚫 Ігнор", "callback_data": "action:ignore_vacancy"},
            ],
        ]
    }

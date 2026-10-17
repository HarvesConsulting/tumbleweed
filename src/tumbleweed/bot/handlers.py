"""Обробники TumbleWeed-бота (sync, без PTB Application).

Нова архітектура (v2):
  - handlers.py — текстові повідомлення, команди, reply-кнопки, FSM
  - callbacks.py — inline callback'и
  - dispatcher.py — точка входу, розподіляє update'и

FSM через states.py (простий рядковий):
  set_state(chat_id, STATE_...)
  get_state(chat_id)
  clear_state(chat_id)

Відправка через ctx.notifier — TelegramClient.

Модель даних: user_subscriptions (багато підписок на chat_id).
  Кнопка "📋 Мої пошуки" — показує список.
  Кнопка "🔍 Знайти роботу" — починає flow додавання нової підписки.
"""
from __future__ import annotations

import logging

from tumbleweed.config import settings
from tumbleweed.db.queries_jobs import (
    Subscription,
    any_subscription_enabled,
    count_subscriptions,
    list_subscriptions,
    set_all_subscriptions_enabled,
)
from tumbleweed.services.subcategory_search import get_category_label, get_subcategory

from . import states
from .keyboards import (
    BTN_FIND_JOB,
    BTN_HELP,
    BTN_MY_SUBS,
    BTN_MY_VACANCIES,
    BTN_RENT,
    BTN_TOGGLE_OFF,
    BTN_TOGGLE_ON,
    category_keyboard,
    city_empty_keyboard,
    city_keyboard,
    city_results_keyboard,
    country_keyboard,
    experience_keyboard,
    job_type_keyboard,
    main_reply_keyboard,
    subscriptions_list_keyboard,
)

log = logging.getLogger(__name__)


# ───────────────────────────────────────────────────────
# Утиліти
# ───────────────────────────────────────────────────────

def _rentalert_url(chat_id: str | int, city_slug: str = "") -> str:
    """URL на RentAlert з переданим chat_id і (опційно) містом."""
    base = settings.rentalert_bot_url
    parts = ["from_tumbleweed", str(chat_id)]
    if city_slug:
        parts.append(city_slug)
    return f"{base}?start={'_'.join(parts)}"


def _profession_label(profession_key: str, country: str) -> str:
    """Перетворює ключ підписки у людську назву."""
    if not profession_key:
        return "🌍 Будь-яка професія"
    if profession_key.startswith("custom:"):
        return profession_key[len("custom:"):].strip()
    cat_key, _, _ = profession_key.partition("_")
    sub = get_subcategory(cat_key, profession_key, country=country)
    return sub.label if sub else profession_key


def _city_label(country: str, city_slug: str) -> str:
    """Slug міста → людська назва."""
    if not city_slug:
        return "🌍 Будь-яке місто"
    from tumbleweed.services.city_search import get_city
    c = get_city(country, city_slug)
    return c.name if c else city_slug


def _job_types_label(job_types: list[str]) -> str:
    """Людський опис типу зайнятості."""
    if not job_types:
        return "🌍 Будь-яка"
    labels = {"full": "Повна", "part": "Часткова", "remote": "Віддалена"}
    return ", ".join(labels.get(j, j) for j in job_types)


def _experience_label(experience: str) -> str:
    """Людський опис досвіду."""
    labels = {
        "all": "🌍 Будь-який",
        "no": "🌱 Без досвіду",
        "1-3": "🌿 1-3 роки",
        "3+": "🌳 3+ роки",
    }
    return labels.get(experience or "all", experience or "all")


def _subscription_line(idx: int, sub: Subscription) -> str:
    """Один рядок для списку підписок (без inline-кнопок)."""
    city = _city_label(sub.country, sub.city_slug)
    prof = _profession_label(sub.profession_key, sub.country)
    status = "✅" if sub.enabled else "⏸"
    return f"{status} *{idx}.* {city} · {prof}"


def _subscriptions_summary_text(subs: list[Subscription]) -> str:
    """Красивий текст списку підписок."""
    if not subs:
        return (
            "📭 *У тебе поки немає пошуків*\n\n"
            "Натисни «🔍 Знайти роботу», щоб додати перший."
        )

    lines = [
        f"📋 *Твої пошуки* ({len(subs)}):",
        "",
    ]
    for i, sub in enumerate(subs, start=1):
        lines.append(_subscription_line(i, sub))
        # Другий рядок з деталями (job_types / experience), якщо не дефолт
        details = []
        if sub.job_types:
            details.append(f"⏰ {_job_types_label(sub.job_types)}")
        if sub.experience and sub.experience != "all":
            details.append(f"🎓 {_experience_label(sub.experience)}")
        if details:
            lines.append(f"     {' · '.join(details)}")

    return "\n".join(lines)


# ───────────────────────────────────────────────────────
# Команди
# ───────────────────────────────────────────────────────

def handle_start(chat_id: str, ctx) -> None:
    """Обробка /start."""
    states.clear_state(chat_id)

    try:
        subs = list_subscriptions(ctx.client, chat_id, only_enabled=False)
    except Exception as e:
        log.warning("Не вдалось прочитати підписки: %s", e)
        subs = []

    if subs:
        enabled = any(s.enabled for s in subs)
        text = (
            "🌾 *TumbleWeed*\n\n"
            f"{_subscriptions_summary_text(subs)}\n\n"
            "📍 Обери дію нижче 👇"
        )
        # Reply-клавіатура
        ctx.notifier.send_message(
            chat_id,
            "⌨️ Меню — знизу 👇",
            keyboard=main_reply_keyboard(enabled),
        )
        # Список підписок + inline-кнопки
        ctx.notifier.send_message(
            chat_id,
            text,
            keyboard=subscriptions_list_keyboard(subs) if subs else None,
        )
        return

    # Новий користувач — почати flow "Знайти роботу"
    ctx.notifier.send_message(
        chat_id,
        "🌾 *Вітаю у TumbleWeed!*\n\n"
        "Я шукатиму вакансії за твоїми фільтрами і надсилатиму "
        "тільки нові — щоб ти не сидів на сайтах.\n\n"
        "🌍 *Обери країну для пошуку:*",
        keyboard=country_keyboard(),
    )
    states.set_state(chat_id, states.STATE_CHOOSING_COUNTRY)


def handle_help(chat_id: str, ctx) -> None:
    """Обробка /help."""
    ctx.notifier.send_message(
        chat_id,
        "❓ *TumbleWeed — довідка*\n\n"

        "🌾 *TumbleWeed* — бот для пошуку роботи "
        "та житла для переселенців.\n\n"

        "*━━━ 📋 Меню (знизу екрана) ━━━*\n\n"

        "📄 *Моє резюме*\n"
        "  Відкриває онлайн-конструктор резюме.\n\n"

        "📋 *Мої пошуки*\n"
        "  Список твоїх збережених пошуків. Можна видалити "
        "або призупинити кожен.\n\n"

        "🔍 *Знайти роботу*\n"
        "  Налаштувати новий пошук: країна, місто, професія, "
        "тип зайнятості, досвід.\n\n"

        "🏠 *Житло*\n"
        "  Перейти у RentAlert — окремий бот для оренди "
        "житла. Місто передається автоматично.\n\n"

        "🔔 *Сповіщення*\n"
        "  Увімкнути або вимкнути всі сповіщення одразу.\n\n"

        "*━━━ ⚙️ Команди ━━━*\n\n"
        "/start — почати налаштування або переглянути пошуки\n"
        "/settings — те саме, що «📋 Мої пошуки»\n"
        "/stop — вимкнути всі сповіщення\n"
        "/resume — увімкнути всі сповіщення\n"
        "/help — ця довідка\n\n"

        "💡 *Порада:* просто чекай — я надішлю нові вакансії "
        "автоматично, як тільки знайду.",
    )


def handle_settings(chat_id: str, ctx) -> None:
    """Обробка /settings — alias для «📋 Мої пошуки»."""
    on_btn_my_subs(chat_id, ctx)


def handle_stop(chat_id: str, ctx) -> None:
    """Обробка /stop — вимкнути всі сповіщення."""
    try:
        n = set_all_subscriptions_enabled(ctx.client, chat_id, False)
        msg = "🔕 Всі сповіщення вимкнено." if n else "👋 У тебе ще немає пошуків."
        ctx.notifier.send_message(
            chat_id, msg,
            keyboard=main_reply_keyboard(enabled=False),
        )
    except Exception as e:
        ctx.notifier.send_message(chat_id, f"❌ {e}")


def handle_resume(chat_id: str, ctx) -> None:
    """Обробка /resume — увімкнути всі сповіщення."""
    try:
        n = set_all_subscriptions_enabled(ctx.client, chat_id, True)
        msg = "🔔 Всі сповіщення увімкнено." if n else "👋 У тебе ще немає пошуків."
        ctx.notifier.send_message(
            chat_id, msg,
            keyboard=main_reply_keyboard(enabled=True),
        )
    except Exception as e:
        ctx.notifier.send_message(chat_id, f"❌ {e}")


def handle_cancel(chat_id: str, ctx) -> None:
    """Обробка /cancel — скинути діалог."""
    states.clear_state(chat_id)
    ctx.notifier.send_message(chat_id, "❌ Скасовано. /start — почати заново.")


# ───────────────────────────────────────────────────────
# Reply-кнопки
# ───────────────────────────────────────────────────────

def on_btn_my_vacancies(chat_id: str, ctx) -> None:
    """📄 Моє резюме — посилання на конструктор."""
    url = "https://resume-fawn-zeta-12.vercel.app/"
    ctx.notifier.send_message(
        chat_id,
        "📄 *Моє резюме*\n\n"
        "Створи професійне резюме за 5 хвилин — з готовими шаблонами "
        "та підказками.\n\n"
        "✅ Безкоштовно\n"
        "✅ Експорт у PDF\n"
        "✅ Готове для відправки роботодавцям\n\n"
        f"👉 [Створити резюме]({url})",
        keyboard={
            "inline_keyboard": [
                [{"text": "📄 Відкрити конструктор", "url": url}],
            ]
        },
    )


def on_btn_my_subs(chat_id: str, ctx) -> None:
    """📋 Мої пошуки."""
    try:
        subs = list_subscriptions(ctx.client, chat_id, only_enabled=False)
    except Exception as e:
        ctx.notifier.send_message(chat_id, f"❌ {e}")
        return

    enabled = any(s.enabled for s in subs) if subs else True

    ctx.notifier.send_message(
        chat_id,
        _subscriptions_summary_text(subs),
        keyboard=subscriptions_list_keyboard(subs) if subs else None,
    )
    # Оновлюємо reply-клавіатуру (тумблер сповіщень)
    ctx.notifier.send_message(
        chat_id,
        "⌨️ Меню — знизу 👇",
        keyboard=main_reply_keyboard(enabled),
    )


def on_btn_find_job(chat_id: str, ctx) -> None:
    """🔍 Знайти роботу — почати flow нової підписки."""
    states.clear_state(chat_id)
    ctx.notifier.send_message(
        chat_id,
        "🔍 *Новий пошук*\n\n"
        "Оберемо країну, місто та професію — я шукатиму вакансії "
        "і надсилатиму тільки нові.\n\n"
        "🌍 *Обери країну:*",
        keyboard=country_keyboard(),
    )
    states.set_state(chat_id, states.STATE_CHOOSING_COUNTRY)


def on_btn_toggle(chat_id: str, ctx) -> None:
    """🔔 Сповіщення — глобальний toggle всіх підписок."""
    try:
        subs = list_subscriptions(ctx.client, chat_id, only_enabled=False)
        if not subs:
            ctx.notifier.send_message(
                chat_id,
                "👋 У тебе ще немає пошуків.\n"
                "Натисни «🔍 Знайти роботу», щоб додати перший.",
            )
            return

        currently_enabled = any(s.enabled for s in subs)
        new_state = not currently_enabled
        set_all_subscriptions_enabled(ctx.client, chat_id, new_state)

        status = "✅ увімкнено" if new_state else "🔕 вимкнено"
        ctx.notifier.send_message(
            chat_id,
            f"🔔 Сповіщення: *{status}*",
            keyboard=main_reply_keyboard(new_state),
        )
    except Exception as e:
        ctx.notifier.send_message(chat_id, f"❌ {e}")


def on_btn_help(chat_id: str, ctx) -> None:
    """❓ Допомога (дублює handle_help)."""
    handle_help(chat_id, ctx)


def on_btn_rent_reply(chat_id: str, ctx) -> None:
    """🏠 Житло — перехід у RentAlert з передачею міста."""
    # Беремо перше місто з першої підписки
    city_slug = ""
    try:
        subs = list_subscriptions(ctx.client, chat_id, only_enabled=True)
        if subs and subs[0].city_slug:
            city_slug = subs[0].city_slug
    except Exception:
        pass

    url = _rentalert_url(chat_id, city_slug)

    text = "🏠 *Пошук житла*\n\n"
    text += "RentAlert — окремий сервіс для оренди.\n\n"
    if city_slug:
        city_name = _city_label("ua", city_slug)  # FIXME: країна з підписки
        text += f"📍 Передам місто: *{city_name}*\n\n"
    text += f"👉 [Відкрити RentAlert]({url})"

    ctx.notifier.send_message(chat_id, text)


# ───────────────────────────────────────────────────────
# FSM: очікування тексту
# ───────────────────────────────────────────────────────

def handle_city_query(chat_id: str, text: str, ctx) -> None:
    """Обробка введення міста (FSM STATE_WAITING_CITY_QUERY)."""
    from tumbleweed.services.city_search import search_cities

    if len(text) < 2:
        ctx.notifier.send_message(chat_id, "⚠️ Введи мінімум 2 символи. Спробуй ще раз.")
        return

    country = states.get_user_data(chat_id).get("country", "ua")
    results = search_cities(country, text, limit=3)

    if not results:
        ctx.notifier.send_message(
            chat_id,
            f"🔍 За запитом *{text}* нічого не знайдено.\n\n"
            "Спробуй іншу назву або обери «🌍 Будь-яке місто».",
            keyboard=city_empty_keyboard(text),
        )
        return

    ctx.notifier.send_message(
        chat_id,
        f"🔍 За запитом *{text}* знайдено {len(results)}:\n\nОбери місто:",
        keyboard=city_results_keyboard(results, text),
    )


def handle_feedback(chat_id: str, text: str, ctx) -> None:
    """Обробка feedback (FSM STATE_WAITING_FEEDBACK)."""
    states.clear_state(chat_id)
    # TODO: зберегти feedback
    ctx.notifier.send_message(chat_id, "✅ Дякую за відгук!")


# ───────────────────────────────────────────────────────
# Диспетчери
# ───────────────────────────────────────────────────────

def handle_command(chat_id: str, text: str, ctx) -> None:
    """Диспетчер команд."""
    cmd = text.split()[0].lower()

    if cmd == "/start":
        handle_start(chat_id, ctx)
    elif cmd == "/help":
        handle_help(chat_id, ctx)
    elif cmd == "/settings":
        handle_settings(chat_id, ctx)
    elif cmd == "/stop":
        handle_stop(chat_id, ctx)
    elif cmd == "/resume":
        handle_resume(chat_id, ctx)
    elif cmd == "/cancel":
        handle_cancel(chat_id, ctx)
    else:
        ctx.notifier.send_message(chat_id, "❓ Невідома команда. Спробуй /help.")


def is_reply_button(text: str) -> bool:
    """Чи це reply-кнопка з меню?"""
    return text in {
        BTN_MY_VACANCIES,
        BTN_MY_SUBS,
        BTN_FIND_JOB,
        BTN_RENT,
        BTN_TOGGLE_ON,
        BTN_TOGGLE_OFF,
        BTN_HELP,
    }


def handle_reply_button(chat_id: str, text: str, ctx) -> None:
    """Диспетчер reply-кнопок."""
    if text == BTN_MY_VACANCIES:
        on_btn_my_vacancies(chat_id, ctx)
    elif text == BTN_MY_SUBS:
        on_btn_my_subs(chat_id, ctx)
    elif text == BTN_FIND_JOB:
        on_btn_find_job(chat_id, ctx)
    elif text == BTN_RENT:
        on_btn_rent_reply(chat_id, ctx)
    elif text in (BTN_TOGGLE_ON, BTN_TOGGLE_OFF):
        on_btn_toggle(chat_id, ctx)
    elif text == BTN_HELP:
        on_btn_help(chat_id, ctx)
    else:
        log.warning("Unknown reply button: %r", text)


def send_main_menu(chat_id: str, ctx) -> None:
    """Надсилає головне меню (коли невідомий текст)."""
    try:
        subs = list_subscriptions(ctx.client, chat_id, only_enabled=False)
    except Exception:
        subs = []

    if subs:
        on_btn_my_subs(chat_id, ctx)
    else:
        ctx.notifier.send_message(
            chat_id,
            "👋 Натисни /start, щоб почати.",
        )

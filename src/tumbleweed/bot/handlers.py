"""Обробники TumbleWeed-бота (sync, без PTB Application).

Нова архітектура:
  - handlers.py — текстові повідомлення, команди, reply-кнопки, FSM
  - callbacks.py — inline callback'и
  - dispatcher.py — точка входу, розподіляє update'и

FSM через states.py (простий рядковий):
  set_state(chat_id, STATE_WAITING_CITY_QUERY)
  get_state(chat_id)
  clear_state(chat_id)

Відправка через ctx.notifier — TelegramClient.
"""
from __future__ import annotations

import logging

from tumbleweed.config import settings
from tumbleweed.db.queries_jobs import (
    get_user_profile,
    set_user_enabled,
)
from tumbleweed.services.subcategory_search import get_category_label, get_subcategory

from . import states
from .keyboards import (
    BTN_CHANGE,
    BTN_HELP,
    BTN_MY_PROFILE,
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
)

log = logging.getLogger(__name__)


# ───────────────────────────────────────────────────────
# Утиліти
# ───────────────────────────────────────────────────────

def _rentalert_url(chat_id: str | int, city_slug: str = "") -> str:
    """URL на RentAlert з переданим chat_id і (опційно) містом.

    Args:
        chat_id: ID чату користувача
        city_slug: slug міста ("kropyvnytskyi", "kyiv", ...)

    Returns:
        Deep link: https://t.me/RentAlertBot?start=from_tumbleweed_XXX_CITY
    """
    base = settings.rentalert_bot_url
    parts = ["from_tumbleweed", str(chat_id)]
    if city_slug:
        parts.append(city_slug)
    return f"{base}?start={'_'.join(parts)}"


def _profile_summary_text(profile) -> str:
    """Красивий опис профілю з людськими назвами."""
    from tumbleweed.services.city_search import get_city

    # ── Професії ───────────────────────────────
    profs_raw = profile.professions or []
    if not profs_raw:
        profs_text = "🌍 будь-яка"
    else:
        labels = []
        for p in profs_raw:
            if p.startswith("custom:"):
                labels.append(p.replace("custom:", ""))
            else:
                cat_key, _, _ = p.partition("_")
                sub = get_subcategory(cat_key, p)
                labels.append(sub.label if sub else p)
        profs_text = ", ".join(labels)

    # ── Міста — реальні назви ────────────────────
    city_slugs = profile.cities or []
    if city_slugs:
        city_names = []
        for slug in city_slugs:
            c = get_city(profile.country, slug)
            city_names.append(c.name if c else slug)
        cities_text = ", ".join(city_names)
    else:
        cities_text = "будь-яке"

    # ── Тип зайнятості ─────────────────────────
    jt_labels = {"full": "Повна", "part": "Часткова", "remote": "Віддалена"}
    jts_raw = profile.job_types or []
    jts_text = ", ".join(jt_labels.get(j, j) for j in jts_raw) or "будь-яка"

    # ── Досвід ─────────────────────────────────
    exp_labels = {
        "all": "будь-який",
        "no": "без досвіду",
        "1-3": "1-3 роки",
        "3+": "3+ років",
    }
    exp = exp_labels.get(profile.experience or "all", profile.experience or "all")

    # ── Країна ─────────────────────────────────
    country_labels = {"ua": "🇺🇦 Україна", "pl": "🇵🇱 Польща", "ro": "🇷🇴 Румунія"}
    country_text = country_labels.get(profile.country, profile.country)

    return (
        f"🌍 Країна: *{country_text}*\n"
        f"🏙 Місто: {cities_text}\n"
        f"💼 Професія: {profs_text}\n"
        f"⏰ Зайнятість: {jts_text}\n"
        f"🎓 Досвід: {exp}"
    )


# ───────────────────────────────────────────────────────
# Команди
# ───────────────────────────────────────────────────────

def handle_start(chat_id: str, ctx) -> None:
    """Обробка /start."""
    states.clear_state(chat_id)

    try:
        profile = get_user_profile(ctx.client, chat_id)
    except Exception as e:
        log.warning("Не вдалось прочитати профіль: %s", e)
        profile = None

    if profile:
        status = "✅ увімкнено" if profile.enabled else "🔕 вимкнено"
        text = (
            "🌾 *TumbleWeed*\n\n"
            f"🔔 Сповіщення: *{status}*\n\n"
            f"{_profile_summary_text(profile)}\n\n"
            "📍 Обери дію нижче 👇"
        )
        # 1) Reply-клавіатура
        ctx.notifier.send_message(
            chat_id,
            "⌨️ Меню — знизу 👇",
            keyboard=main_reply_keyboard(profile.enabled),
        )
        # 2) Основне повідомлення
        ctx.notifier.send_message(chat_id, text)
        return

    # Новий користувач — почати діалог фільтрів
    text = (
        "🌾 *Вітаю у TumbleWeed!*\n\n"
        "Я допоможу знайти роботу та житло в обраній країні.\n\n"
        "🌍 *Обери країну:*"
    )
    ctx.notifier.send_message(chat_id, text, keyboard=country_keyboard())
    states.set_state(chat_id, states.STATE_CHOOSING_COUNTRY)


def handle_help(chat_id: str, ctx) -> None:
    """Обробка /help."""
    ctx.notifier.send_message(
        chat_id,
        "❓ *TumbleWeed — довідка*\n\n"

        "🌾 *TumbleWeed* — бот для пошуку роботи "
        "та житла для переселенців.\n\n"

        "*━━━ 📋 Меню (знизу екрана) ━━━*\n\n"

        "📊 *Мої вакансії*\n"
        "  Показує останні знайдені вакансії для тебе. "
        "Кнопки під кожною: відкрити, зберегти, ігнорувати.\n\n"

        "👤 *Мій профіль*\n"
        "  Переглянути свої фільтри: країна, місто, професія, "
        "тип зайнятості, досвід. Показує статус сповіщень.\n\n"

        "🔍 *Знайти роботу*\n"
        "  Налаштувати фільтри пошуку заново: обрати країну, "
        "місто, сферу роботи та підкатегорії.\n\n"

        "🏠 *Житло*\n"
        "  Перейти у RentAlert — окремий бот для оренди "
        "житла. Місто передається автоматично.\n\n"

        "🔔 *Сповіщення*\n"
        "  Увімкнути або вимкнути автоматичні сповіщення "
        "про нові вакансії.\n\n"

        "*━━━ ⚙️ Команди ━━━*\n\n"
        "/start — почати налаштування або переглянути профіль\n"
        "/settings — переглянути поточні налаштування\n"
        "/stop — вимкнути сповіщення\n"
        "/resume — увімкнути сповіщення\n"
        "/help — ця довідка\n\n"

        "💡 *Порада:* просто чекай — я надішлю нові вакансії "
        "автоматично, як тільки знайду.",
    )


def handle_settings(chat_id: str, ctx) -> None:
    """Обробка /settings."""
    try:
        profile = get_user_profile(ctx.client, chat_id)
    except Exception as e:
        ctx.notifier.send_message(chat_id, f"❌ {e}")
        return

    if not profile:
        ctx.notifier.send_message(
            chat_id,
            "👋 Ще немає налаштувань.\nНатисни /start.",
        )
        return

    ctx.notifier.send_message(
        chat_id,
        "⚙️ *Твої налаштування:*\n\n" + _profile_summary_text(profile),
    )


def handle_stop(chat_id: str, ctx) -> None:
    """Обробка /stop — вимкнути сповіщення."""
    try:
        set_user_enabled(ctx.client, chat_id, False)
        ctx.notifier.send_message(
            chat_id,
            "🔕 Вимкнено. /resume — увімкнути.",
            keyboard=main_reply_keyboard(enabled=False),
        )
    except Exception as e:
        ctx.notifier.send_message(chat_id, f"❌ {e}")


def handle_resume(chat_id: str, ctx) -> None:
    """Обробка /resume — увімкнути сповіщення."""
    try:
        set_user_enabled(ctx.client, chat_id, True)
        ctx.notifier.send_message(
            chat_id,
            "🔔 Увімкнено.",
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
    """📊 Мої вакансії."""
    ctx.notifier.send_message(
        chat_id,
        "📊 *Мої вакансії*\n\n"
        "Я надсилаю нові вакансії автоматично, коли знаходжу.\n"
        "Останні показані тут 👇\n\n"
        "_Поки що порожньо — чекай на нові._",
    )


def on_btn_my_profile(chat_id: str, ctx) -> None:
    """👤 Мій профіль."""
    try:
        profile = get_user_profile(ctx.client, chat_id)
    except Exception as e:
        ctx.notifier.send_message(chat_id, f"❌ {e}")
        return

    if not profile:
        ctx.notifier.send_message(
            chat_id,
            "👋 Ще немає профілю.\nНатисни /start.",
        )
        return

    status = "✅ увімкнено" if profile.enabled else "🔕 вимкнено"
    ctx.notifier.send_message(
        chat_id,
        "👤 *Мій профіль*\n\n"
        f"{_profile_summary_text(profile)}\n\n"
        f"🔔 Сповіщення: *{status}*",
        keyboard=main_reply_keyboard(profile.enabled),
    )


def on_btn_toggle(chat_id: str, ctx) -> None:
    """🔔 Сповіщення — toggle."""
    try:
        profile = get_user_profile(ctx.client, chat_id)
        if not profile:
            ctx.notifier.send_message(
                chat_id,
                "👋 Ще немає налаштувань.\nНатисни /start.",
            )
            return

        new_state = not profile.enabled
        set_user_enabled(ctx.client, chat_id, new_state)

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
    from tumbleweed.db.queries_jobs import get_user_profile

    # Отримуємо перше місто з профілю
    city_slug = ""
    try:
        profile = get_user_profile(ctx.client, chat_id)
        if profile and profile.cities:
            city_slug = profile.cities[0]
    except Exception:
        pass

    url = _rentalert_url(chat_id, city_slug)

    text = "🏠 *Пошук житла*\n\n"
    text += "RentAlert — окремий сервіс для оренди.\n\n"
    if city_slug:
        text += f"📍 Передам місто: *{city_slug}*\n\n"
    text += f"👉 [Відкрити RentAlert]({url})"

    ctx.notifier.send_message(chat_id, text)


def on_btn_change_filters(chat_id: str, ctx) -> None:
    """🔍 Знайти роботу — почати діалог заново."""
    states.clear_state(chat_id)
    ctx.notifier.send_message(
        chat_id,
        "🔍 *Знайти роботу*\n\n"
        "Оберемо країну, місто та професію — "
        "я шукатиму вакансії для тебе.\n\n"
        "🌍 *Обери країну:*",
        keyboard=country_keyboard(),
    )
    states.set_state(chat_id, states.STATE_CHOOSING_COUNTRY)


# ───────────────────────────────────────────────────────
# FSM: очікування тексту
# ───────────────────────────────────────────────────────

def handle_city_query(chat_id: str, text: str, ctx) -> None:
    """Обробка введення міста (FSM STATE_WAITING_CITY_QUERY)."""
    from tumbleweed.services.city_search import search_cities

    if len(text) < 2:
        ctx.notifier.send_message(chat_id, "⚠️ Введи мінімум 2 символи. Спробуй ще раз.")
        return

    # Країну беремо зі стану
    country = ctx.user_data.get(chat_id, {}).get("country", "ua") if hasattr(ctx, "user_data") else "ua"

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
        BTN_MY_PROFILE,
        BTN_CHANGE,
        BTN_RENT,
        BTN_TOGGLE_ON,
        BTN_TOGGLE_OFF,
        BTN_HELP,
    }


def handle_reply_button(chat_id: str, text: str, ctx) -> None:
    """Диспетчер reply-кнопок."""
    if text == BTN_MY_VACANCIES:
        on_btn_my_vacancies(chat_id, ctx)
    elif text == BTN_MY_PROFILE:
        on_btn_my_profile(chat_id, ctx)
    elif text == BTN_CHANGE:
        on_btn_change_filters(chat_id, ctx)
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
        profile = get_user_profile(ctx.client, chat_id)
    except Exception:
        profile = None

    if profile:
        on_btn_my_profile(chat_id, ctx)
    else:
        ctx.notifier.send_message(
            chat_id,
            "👋 Натисни /start, щоб почати.",
        )

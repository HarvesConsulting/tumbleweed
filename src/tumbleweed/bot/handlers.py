"""Обробники Telegram-бота TumbleWeed.

Новий флоу:
  /start → COUNTRY → CITY → CATEGORY (сфера)
        → SUBCATEGORY_QUERY (ввід слова)
        → SUBCATEGORY_PICK (toggle ✅, макс 5)
        → JOB_TYPE → EXPERIENCE → DONE

Команди: /start, /settings, /stop, /resume, /cancel.
"""
from __future__ import annotations

import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from tumbleweed.config import settings
from tumbleweed.db.client import TursoClient
from tumbleweed.db.queries_jobs import (
    get_user_profile,
    mark_sent,
    set_user_enabled,
    upsert_user_profile,
)
from tumbleweed.services.subcategory_search import (
    MIN_QUERY_LEN,
    get_category_label,
    get_subcategory,
    search_subcategories,
)

from .keyboards import (
    BTN_CHANGE,
    BTN_HELP,
    BTN_MY_PROFILE,
    BTN_MY_VACANCIES,
    BTN_RENT,
    BTN_TOGGLE_OFF,
    BTN_TOGGLE_ON,
    category_keyboard,
    city_keyboard,
    city_empty_keyboard,
    city_results_keyboard,
    country_keyboard,
    experience_keyboard,
    job_type_keyboard,
    main_reply_keyboard,
    subcategory_empty_keyboard,
    subcategory_results_keyboard,
)
from .states import State

log = logging.getLogger(__name__)

MAX_SUBCATEGORIES = 5


# ───────────────────────────────────────────────────────
# Утиліти
# ───────────────────────────────────────────────────────

def _db() -> TursoClient:
    return TursoClient(settings.turso_url, settings.turso_token)


async def _reply_or_edit(update: Update, text: str, keyboard=None) -> None:
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(
            text, reply_markup=keyboard, parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(
            text, reply_markup=keyboard, parse_mode="Markdown"
        )


def _rentalert_url(chat_id: int) -> str:
    return f"{settings.rentalert_bot_url}?start=from_tumbleweed_{chat_id}"


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

    # ── Міста — реальні назви, не slug'и ───────
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
# /start
# ───────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    chat_id = str(update.effective_chat.id)

    try:
        profile = get_user_profile(_db(), chat_id)
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
        # 1) Reply-клавіатура (встановлюємо меню знизу)
        await update.message.reply_text(
            "⌨️ Меню — знизу 👇",
            reply_markup=main_reply_keyboard(profile.enabled),
        )
        # 2) Основне повідомлення (без inline)
        await update.message.reply_text(text, parse_mode="Markdown")
        return ConversationHandler.END

    text = (
        "🌾 *Вітаю у TumbleWeed!*\n\n"
        "Я допоможу знайти роботу в обраній країні "
        "й покажу, де поруч шукати житло.\n\n"
        "🌍 *Обери країну:*"
    )
    await _reply_or_edit(update, text, country_keyboard())
    return State.CHOOSING_COUNTRY


async def cmd_start_filters(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Entry point для reply-кнопки «✏️ Змінити фільтри»."""
    context.user_data.clear()
    await update.message.reply_text(
        "🌍 *Обери країну:*",
        reply_markup=country_keyboard(),
        parse_mode="Markdown",
    )
    return State.CHOOSING_COUNTRY


# ───────────────────────────────────────────────────────
# Крок 1 → 2. Країна → Місто
# ───────────────────────────────────────────────────────

async def on_country(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    _, country = query.data.split(":", 1)
    context.user_data.clear()
    context.user_data["country"] = country
    context.user_data["cities"] = []

    labels = {"ua": "🇺🇦 Україна", "pl": "🇵🇱 Польща", "ro": "🇷🇴 Румунія"}
    label = labels.get(country, country)

    await query.edit_message_text(
        f"📍 *{label}* — обери місто:",
        reply_markup=city_keyboard(country),
        parse_mode="Markdown",
    )
    return State.CHOOSING_CITY

# ───────────────────────────────────────────────────────
# Крок 2.1. Кнопка «✏️ Ввести місто»
# ───────────────────────────────────────────────────────

async def on_enter_city(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Користувач натиснув «✏️ Ввести місто» — просимо текст."""
    query = update.callback_query
    await query.answer()

    country = context.user_data.get("country", "ua")
    labels = {"ua": "🇺🇦 України", "pl": "🇵🇱 Польщі", "ro": "🇷🇴 Румунії"}

    await query.edit_message_text(
        f"✏️ *Введи назву міста* у {labels.get(country, '')}:\n\n"
        "Наприклад: `Тернопіль`, `Краків`, `Cluj`\n\n"
        "Мінімум 2 символи.",
        parse_mode="Markdown",
    )
    return State.CHOOSING_CITY_QUERY


# ───────────────────────────────────────────────────────
# Крок 2.2. Обробка текстового вводу міста
# ───────────────────────────────────────────────────────

async def on_city_query(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Користувач ввів назву міста — шукаємо збіги."""
    from tumbleweed.services.city_search import search_cities

    text = (update.message.text or "").strip()
    country = context.user_data.get("country", "ua")

    if len(text) < 2:
        await update.message.reply_text(
            "⚠️ Введи мінімум 2 символи. Спробуй ще раз.",
        )
        return State.CHOOSING_CITY_QUERY

    results = search_cities(country, text, limit=3)

    if not results:
        await update.message.reply_text(
            f"🔍 За запитом *{text}* нічого не знайдено.\n\n"
            "Спробуй іншу назву або обери «🌍 Будь-яке місто».",
            reply_markup=city_empty_keyboard(text),
            parse_mode="Markdown",
        )
        return State.CHOOSING_CITY_PICK

    context.user_data["last_city_results"] = results
    context.user_data["last_city_query"] = text

    await update.message.reply_text(
        f"🔍 За запитом *{text}* знайдено {len(results)}:\n\n"
        "Обери місто або введи інше:",
        reply_markup=city_results_keyboard(results, text),
        parse_mode="Markdown",
    )
    return State.CHOOSING_CITY_PICK


# ───────────────────────────────────────────────────────
# Крок 2.3. Вибір міста з результатів
# ───────────────────────────────────────────────────────

async def on_city_pick(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Користувач обрав місто зі списку."""
    from tumbleweed.services.city_search import get_city

    query = update.callback_query
    await query.answer()

    _, slug = query.data.split(":", 1)
    country = context.user_data.get("country", "ua")
    city = get_city(country, slug)

    if not city:
        await query.edit_message_text(f"⚠️ Місто не знайдено: {slug}")
        return State.CHOOSING_CITY_PICK

    # Зберігаємо вибір
    context.user_data["cities"] = [slug]
    context.user_data["city_display"] = city.name

    await query.edit_message_text(
        f"✅ Обрано: *{city.name}*\n\n💼 *Обери сферу роботи:*",
        reply_markup=category_keyboard(),
        parse_mode="Markdown",
    )
    return State.CHOOSING_CATEGORY


# ───────────────────────────────────────────────────────
# Крок 2 → 3. Місто → Сфера
# ───────────────────────────────────────────────────────

async def on_city(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    _, city = query.data.split(":", 1)
    cities = context.user_data.setdefault("cities", [])
    if city not in cities:
        cities.append(city)

    await query.edit_message_text(
        "💼 *Обери сферу роботи:*",
        reply_markup=category_keyboard(),
        parse_mode="Markdown",
    )
    return State.CHOOSING_CATEGORY


async def on_city_skip(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    context.user_data["cities"] = []
    await query.edit_message_text(
        "💼 *Обери сферу роботи:*",
        reply_markup=category_keyboard(),
        parse_mode="Markdown",
    )
    return State.CHOOSING_CATEGORY


# ───────────────────────────────────────────────────────
# Крок 3 → 3.1. Сфера → Запит підкатегорій
# ───────────────────────────────────────────────────────

async def on_category(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    _, cat_key = query.data.split(":", 1)
    context.user_data["category"] = cat_key
    context.user_data["selected_subs"] = set()
    context.user_data["last_results"] = []

    cat_label = get_category_label(cat_key)
    await query.edit_message_text(
        f"*{cat_label}*\n\n"
        f"✏️ Введи слово для пошуку підкатегорії (мін. {MIN_QUERY_LEN} символи).\n"
        "Наприклад: `трак`, `водій`, `python`, `кух`\n\n"
        "Можна обрати до 5 підкатегорій.",
        parse_mode="Markdown",
    )
    return State.CHOOSING_SUBCATEGORY_QUERY


async def on_category_skip(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Користувач обрав «🌍 Будь-яка сфера» — пропускаємо підкатегорії."""
    query = update.callback_query
    await query.answer()
    context.user_data["professions"] = []
    await query.edit_message_text(
        "⏰ *Який тип зайнятості?*",
        reply_markup=job_type_keyboard(),
        parse_mode="Markdown",
    )
    return State.CHOOSING_JOB_TYPE


# ───────────────────────────────────────────────────────
# Крок 3.1 → 3.2. Обробка тексту запиту
# ───────────────────────────────────────────────────────

async def on_subcategory_query(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Користувач ввів слово — шукаємо підкатегорії."""
    text = (update.message.text or "").strip()
    category = context.user_data.get("category")

    if not category:
        await update.message.reply_text("Щось пішло не так. Введи /start.")
        return ConversationHandler.END

    cat_label = get_category_label(category)

    if len(text) < MIN_QUERY_LEN:
        await update.message.reply_text(
            f"⚠️ Занадто короткий запит. Введи мінімум {MIN_QUERY_LEN} символи.\n"
            f"Наприклад: `трак`, `водій`, `python`",
            parse_mode="Markdown",
        )
        return State.CHOOSING_SUBCATEGORY_QUERY

    results = search_subcategories(category, text, limit=8)
    context.user_data["last_results"] = results

    if not results:
        await update.message.reply_text(
            f"🔍 За запитом *{text}* нічого не знайдено в _{cat_label}_.",
            reply_markup=subcategory_empty_keyboard(cat_label),
            parse_mode="Markdown",
        )
        return State.CHOOSING_SUBCATEGORY_PICK

    selected = context.user_data.get("selected_subs", set())
    await update.message.reply_text(
        f"🔍 За запитом *{text}* знайдено:\n\n"
        f"Клікни, щоб обрати (✅) або зняти (⬜). Максимум {MAX_SUBCATEGORIES}.",
        reply_markup=subcategory_results_keyboard(
            results=results,
            selected=selected,
            category_key=category,
            category_label=cat_label,
        ),
        parse_mode="Markdown",
    )
    return State.CHOOSING_SUBCATEGORY_PICK


# ───────────────────────────────────────────────────────
# Крок 3.2. Toggle вибору підкатегорії
# ───────────────────────────────────────────────────────

async def on_subcategory_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    _, sub_key = query.data.split(":", 1)
    selected: set = context.user_data.setdefault("selected_subs", set())
    category = context.user_data.get("category", "")
    results = context.user_data.get("last_results", [])
    cat_label = get_category_label(category)

    if sub_key in selected:
        selected.discard(sub_key)
    else:
        if len(selected) >= MAX_SUBCATEGORIES:
            await query.answer(
                f"⚠️ Максимум {MAX_SUBCATEGORIES} підкатегорій",
                show_alert=True,
            )
            return State.CHOOSING_SUBCATEGORY_PICK
        selected.add(sub_key)

    await query.edit_message_reply_markup(
        reply_markup=subcategory_results_keyboard(
            results=results,
            selected=selected,
            category_key=category,
            category_label=cat_label,
        ),
    )
    return State.CHOOSING_SUBCATEGORY_PICK


async def on_subcategory_search_again(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Кнопка «🔍 Пошукати ще» — повертаємось до вводу."""
    query = update.callback_query
    await query.answer()

    category = context.user_data.get("category")
    cat_label = get_category_label(category) if category else ""

    await query.edit_message_text(
        f"*{cat_label}*\n\n"
        f"✏️ Введи нове слово для пошуку (мін. {MIN_QUERY_LEN} символи).",
        parse_mode="Markdown",
    )
    return State.CHOOSING_SUBCATEGORY_QUERY


async def on_subcategory_skip(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Кнопка «🌍 Будь-яка в сфері» — ігноруємо підкатегорії."""
    query = update.callback_query
    await query.answer()
    context.user_data["professions"] = []
    context.user_data.pop("selected_subs", None)
    await query.edit_message_text(
        "⏰ *Який тип зайнятості?*",
        reply_markup=job_type_keyboard(),
        parse_mode="Markdown",
    )
    return State.CHOOSING_JOB_TYPE


async def on_subcategory_done(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Кнопка «✅ Готово» або «⏭ Пропустити»."""
    query = update.callback_query
    await query.answer()

    selected: set = context.user_data.get("selected_subs", set())
    context.user_data["professions"] = list(selected)

    if not selected:
        # Пропустити — покажемо «Будь-яка»
        await query.edit_message_text(
            "🌍 Будеш отримувати всі вакансії цієї сфери.\n\n⏰ *Який тип зайнятості?*",
            reply_markup=job_type_keyboard(),
            parse_mode="Markdown",
        )
        return State.CHOOSING_JOB_TYPE

    # Гарний текст обраного
    labels = []
    for sk in selected:
        sub = get_subcategory(context.user_data.get("category", ""), sk)
        labels.append(f"✅ {sub.label}" if sub else f"✅ {sk}")

    await query.edit_message_text(
        "Обрано:\n" + "\n".join(labels) + "\n\n⏰ *Який тип зайнятості?*",
        reply_markup=job_type_keyboard(),
        parse_mode="Markdown",
    )
    return State.CHOOSING_JOB_TYPE


# ───────────────────────────────────────────────────────
# Крок 4 → 5. Тип зайнятості → Досвід
# ───────────────────────────────────────────────────────

async def on_job_type(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    _, jt = query.data.split(":", 1)
    context.user_data["job_types"] = [jt]
    await query.edit_message_text(
        "🎓 *Який досвід?*",
        reply_markup=experience_keyboard(),
        parse_mode="Markdown",
    )
    return State.CHOOSING_EXPERIENCE


async def on_job_type_skip(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    context.user_data["job_types"] = []
    await query.edit_message_text(
        "🎓 *Який досвід?*",
        reply_markup=experience_keyboard(),
        parse_mode="Markdown",
    )
    return State.CHOOSING_EXPERIENCE


# ───────────────────────────────────────────────────────
# Крок 5 → DONE
# ───────────────────────────────────────────────────────

async def on_experience(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    _, exp = query.data.split(":", 1)
    context.user_data["experience"] = exp
    return await _finalize(update, context)


async def on_experience_skip(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    context.user_data["experience"] = "all"
    return await _finalize(update, context)


async def _finalize(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    chat_id = str(update.effective_chat.id)
    d = context.user_data

    country = d.get("country") or "ua"
    cities = d.get("cities") or []
    professions = list(d.get("professions") or [])
    job_types = d.get("job_types") or []
    experience = d.get("experience") or "all"

    try:
        upsert_user_profile(
            _db(),
            chat_id=chat_id,
            country=country,
            cities=cities,
            professions=professions,
            job_types=job_types,
            experience=experience,
        )
    except Exception as e:
        log.exception("Не вдалось зберегти профіль")
        await update.callback_query.edit_message_text(
            f"❌ Помилка збереження: `{e}`",
            parse_mode="Markdown",
        )
        return ConversationHandler.END

    # Перечитуємо профіль з БД (щоб отримати канонічні дані)
    try:
        profile = get_user_profile(_db(), chat_id)
    except Exception:
        profile = None

    if profile:
        summary = _profile_summary_text(profile)
    else:
        # Fallback — зібрати з d
        profs_text = ", ".join(professions) if professions else "будь-яка"
        cities_text = ", ".join(cities) if cities else "будь-яке"
        jts_text = ", ".join(job_types) if job_types else "будь-яка"
        summary = (
            f"🌍 Країна: *{country}*\n"
            f"🏙 Місто: {cities_text}\n"
            f"💼 Професія: {profs_text}\n"
            f"⏰ Зайнятість: {jts_text}\n"
            f"🎓 Досвід: {experience}"
        )

    # 1) Reply-клавіатура + інструкція
    await update.effective_chat.send_message(
        "🔍 *Розпочинаю пошук!*\n\n"
        "Знизу 👇 — кнопки:\n"
        "📊 *Мої вакансії* — переглянути знайдені\n"
        "👤 *Мій профіль* — налаштування\n"
        "✏️ *Фільтри* — змінити сферу/місто\n"
        "🏠 *Житло* — RentAlert\n"
        "🔔 *Сповіщення* — увімк/вимк\n"
        "❓ *Допомога* — довідка\n\n"
        "Перші вакансії надійдуть автоматично.",
        reply_markup=main_reply_keyboard(enabled=True),
        parse_mode="Markdown",
    )

    # 2) Фінальний текст (без inline)
    await update.callback_query.edit_message_text(
        f"✅ *Готово!*\n\n{summary}\n\n🔔 *Сповіщення увімкнено.*",
        parse_mode="Markdown",
    )
    return ConversationHandler.END


# ───────────────────────────────────────────────────────
# Назад
# ───────────────────────────────────────────────────────

async def on_back_to_country(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    context.user_data.clear()
    await query.edit_message_text(
        "🌍 *Обери країну:*",
        reply_markup=country_keyboard(),
        parse_mode="Markdown",
    )
    return State.CHOOSING_COUNTRY


async def on_back_to_city(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    country = context.user_data.get("country", "ua")
    await query.edit_message_text(
        "📍 *Обери місто:*",
        reply_markup=city_keyboard(country),
        parse_mode="Markdown",
    )
    return State.CHOOSING_CITY


async def on_back_to_category(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    context.user_data["selected_subs"] = set()
    await query.edit_message_text(
        "💼 *Обери сферу роботи:*",
        reply_markup=category_keyboard(),
        parse_mode="Markdown",
    )
    return State.CHOOSING_CATEGORY


# ───────────────────────────────────────────────────────
# Дії головного меню
# ───────────────────────────────────────────────────────

async def on_toggle_notify(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    chat_id = str(update.effective_chat.id)
    try:
        profile = get_user_profile(_db(), chat_id)
        if profile is None:
            await query.edit_message_text(
                "👋 Ще немає налаштувань.\n"
                "Натисни /start, щоб обрати країну та сферу роботи."
            )
            return ConversationHandler.END

        new_state = not profile.enabled
        set_user_enabled(_db(), chat_id, new_state)
        profile.enabled = new_state

        status = "✅ увімкнено" if new_state else "🔕 вимкнено"
        await query.edit_message_text(
            f"🔔 Сповіщення: *{status}*",
            parse_mode="Markdown",
        )
        # Оновити reply-клавіатуру (щоб toggle-напис змінився)
        await update.effective_chat.send_message(
            "Оновлено 👇",
            reply_markup=main_reply_keyboard(new_state),
        )
    except Exception as e:
        log.exception("toggle: %s", e)
        await query.edit_message_text(f"❌ {e}")
    return ConversationHandler.END


async def on_my_profile(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """👤 Мій профіль (inline callback)."""
    query = update.callback_query
    await query.answer()
    chat_id = str(update.effective_chat.id)
    try:
        profile = get_user_profile(_db(), chat_id)
        if profile is None:
            await query.edit_message_text(
                "👋 Ще немає налаштувань.\nНатисни /start."
            )
            return ConversationHandler.END

        status = "✅ увімкнено" if profile.enabled else "🔕 вимкнено"
        text = (
            "👤 *Мій профіль*\n\n"
            f"{_profile_summary_text(profile)}\n\n"
            f"🔔 Сповіщення: *{status}*"
        )
        await query.edit_message_text(text, parse_mode="Markdown")
    except Exception as e:
        log.exception("my_profile: %s", e)
        await query.edit_message_text(f"❌ {e}")
    return ConversationHandler.END


async def on_change_filters(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    context.user_data.clear()
    await query.edit_message_text(
        "🌍 *Обери країну:*",
        reply_markup=country_keyboard(),
        parse_mode="Markdown",
    )
    return State.CHOOSING_COUNTRY


# ───────────────────────────────────────────────────────
# Команди
# ───────────────────────────────────────────────────────

async def cmd_settings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    chat_id = str(update.effective_chat.id)
    try:
        profile = get_user_profile(_db(), chat_id)
    except Exception as e:
        await update.message.reply_text(f"❌ {e}")
        return ConversationHandler.END
    if not profile:
        await update.message.reply_text(
            "👋 Ще немає налаштувань.\n"
            "Натисни /start, щоб обрати країну та сферу роботи."
        )
        return ConversationHandler.END
    await update.message.reply_text(
        "⚙️ *Твої налаштування:*\n\n" + _profile_summary_text(profile),
        parse_mode="Markdown",
    )
    return ConversationHandler.END


async def cmd_stop(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    chat_id = str(update.effective_chat.id)
    try:
        set_user_enabled(_db(), chat_id, False)
    except Exception as e:
        await update.message.reply_text(f"❌ {e}")
        return ConversationHandler.END
    await update.message.reply_text("🔕 Вимкнено. /resume — увімкнути.")
    return ConversationHandler.END


async def cmd_resume(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    chat_id = str(update.effective_chat.id)
    try:
        set_user_enabled(_db(), chat_id, True)
    except Exception as e:
        await update.message.reply_text(f"❌ {e}")
        return ConversationHandler.END
    await update.message.reply_text("🔔 Увімкнено.")
    return ConversationHandler.END


async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    await update.message.reply_text("❌ Скасовано. /start — почати заново.")
    return ConversationHandler.END


# ───────────────────────────────────────────────────────
# Загальний on_action
# ───────────────────────────────────────────────────────

async def on_action(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    _, action = query.data.split(":", 1)

    if action == "enter_city":
        return await on_enter_city(update, context)
    if action == "back_to_city_menu":
        # Повернення до списку міст
        country = context.user_data.get("country", "ua")
        labels = {"ua": "🇺🇦 Україна", "pl": "🇵🇱 Польща", "ro": "🇷🇴 Румунія"}
        await query.edit_message_text(
            f"📍 *{labels.get(country, '')}* — обери місто:",
            reply_markup=city_keyboard(country),
            parse_mode="Markdown",
        )
        return State.CHOOSING_CITY
    if action == "back_country":
        return await on_back_to_country(update, context)
    if action == "back_city":
        return await on_back_to_city(update, context)
    if action == "back_category":
        return await on_back_to_category(update, context)
    if action == "search_again":
        return await on_subcategory_search_again(update, context)
    if action == "sub_done":
        return await on_subcategory_done(update, context)
    if action == "change_filters":
        return await on_change_filters(update, context)

    await query.edit_message_text(f"❓ {action}")
    return ConversationHandler.END


# ───────────────────────────────────────────────────────
# Кнопка «🚫 Ігнор»
# ───────────────────────────────────────────────────────

async def on_ignore_vacancy(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer("🚫 Ігноровано")
    parts = query.data.split(":", 2)
    if len(parts) != 3:
        return
    _, action, vacancy_id = parts
    if action != "ignore_vacancy":
        return
    chat_id = str(update.effective_chat.id)
    try:
        mark_sent(_db(), chat_id, vacancy_id)
    except Exception as e:
        log.warning("ignore: %s", e)
        return
    original = query.message.text or ""
    if "🚫 Ігноровано" not in original:
        await query.edit_message_text(
            f"{original}\n\n_🚫 Ігноровано — більше не покажемо_",
            parse_mode="Markdown",
            disable_web_page_preview=True,
        )


async def on_btn_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = str(update.effective_chat.id)
    try:
        profile = get_user_profile(_db(), chat_id)
        if not profile:
            await update.message.reply_text(
                "👋 Ще немає налаштувань.\n"
                "Натисни /start, щоб обрати країну та сферу роботи."
            )
            return
        new_state = not profile.enabled
        set_user_enabled(_db(), chat_id, new_state)
        status = "✅ увімкнено" if new_state else "🔕 вимкнено"
        await update.message.reply_text(
            f"🔔 Сповіщення: *{status}*",
            reply_markup=main_reply_keyboard(new_state),
            parse_mode="Markdown",
        )
    except Exception as e:
        log.exception("btn toggle: %s", e)
        await update.message.reply_text(f"❌ {e}")


# ───────────────────────────────────────────────────────
# Reply-кнопки (текстові)
# ───────────────────────────────────────────────────────

async def on_btn_my_vacancies(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """📊 Мої вакансії — показує останні знайдені вакансії."""
    try:
        await update.message.reply_text(
            "📊 *Мої вакансії*\n\n"
            "Я надсилаю нові вакансії автоматично, коли знаходжу.\n"
            "Останні показані тут 👇\n\n"
            "_Поки що порожньо — чекай на нові._",
            parse_mode="Markdown",
        )
    except Exception as e:
        log.exception("my_vacancies: %s", e)
        await update.message.reply_text(f"❌ {e}")


async def on_btn_my_profile(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """👤 Мій профіль — показує фільтри (reply)."""
    chat_id = str(update.effective_chat.id)
    try:
        profile = get_user_profile(_db(), chat_id)
        if not profile:
            await update.message.reply_text(
                "👋 Ще немає профілю.\nНатисни /start."
            )
            return

        status = "✅ увімкнено" if profile.enabled else "🔕 вимкнено"
        text = (
            "👤 *Мій профіль*\n\n"
            f"{_profile_summary_text(profile)}\n\n"
            f"🔔 Сповіщення: *{status}*"
        )
        await update.message.reply_text(
            text,
            reply_markup=main_reply_keyboard(profile.enabled),
            parse_mode="Markdown",
        )
    except Exception as e:
        log.exception("my_profile (reply): %s", e)
        await update.message.reply_text(f"❌ {e}")


async def on_btn_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """❓ Допомога."""
    await update.message.reply_text(
        "❓ *TumbleWeed — довідка*\n\n"
        "📊 *Мої вакансії* — переглянути знайдені\n"
        "👤 *Мій профіль* — фільтри та статус\n"
        "✏️ *Фільтри* — змінити країну/місто/професію\n"
        "🏠 *Житло* — перейти в RentAlert\n"
        "🔔 *Сповіщення* — увімкнути/вимкнути\n\n"
        "*Команди:*\n"
        "/start — налаштувати профіль\n"
        "/settings — переглянути налаштування\n"
        "/stop — вимкнути сповіщення\n"
        "/resume — увімкнути\n"
        "/help — ця довідка",
        parse_mode="Markdown",
    )


async def on_btn_rent_reply(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """🏠 Житло — надсилає inline-посилання на RentAlert."""
    url = _rentalert_url(update.effective_chat.id)
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🏠 Відкрити RentAlert", url=url)],
    ])
    await update.message.reply_text(
        "🏠 *Пошук житла*\n\nRentAlert — окремий сервіс для оренди.",
        reply_markup=kb,
        parse_mode="Markdown",
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Команда /help."""
    await on_btn_help(update, context)
    return ConversationHandler.END


# ───────────────────────────────────────────────────────
# Універсальний обробник reply-кнопок
# ───────────────────────────────────────────────────────

async def on_reply_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Універсальний fallback для reply-кнопок.

    Якщо користувач натискає reply-кнопку під час діалогу —
    скасовуємо діалог і виконуємо відповідну дію.
    """
    text = (update.message.text or "").strip()

    # Скидаємо поточний діалог
    context.user_data.clear()

    # Диспетчеризація
    if text == BTN_MY_VACANCIES:
        await on_btn_my_vacancies(update, context)
    elif text == BTN_MY_PROFILE:
        await on_btn_my_profile(update, context)
    elif text == BTN_RENT:
        await on_btn_rent_reply(update, context)
    elif text in (BTN_TOGGLE_ON, BTN_TOGGLE_OFF):
        await on_btn_toggle(update, context)
    elif text == BTN_HELP:
        await on_btn_help(update, context)

    return ConversationHandler.END

# ───────────────────────────────────────────────────────
# Фабрика ConversationHandler
# ───────────────────────────────────────────────────────

def build_conversation_handler() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[
            CommandHandler("start", cmd_start),
            MessageHandler(filters.Text([BTN_CHANGE]), cmd_start_filters),
        ],
        states={
            State.CHOOSING_COUNTRY: [
                CallbackQueryHandler(on_country, pattern=r"^country:"),
            ],
            State.CHOOSING_CITY: [
                CallbackQueryHandler(on_city, pattern=r"^city:"),
                CallbackQueryHandler(on_city_skip, pattern=r"^skip:city$"),
                CallbackQueryHandler(on_action, pattern=r"^action:"),
            ],
            State.CHOOSING_CITY_QUERY: [
                # Reply-кнопки мають пріоритет над пошуком
                MessageHandler(filters.Text([
                    BTN_MY_VACANCIES, BTN_MY_PROFILE, BTN_RENT,
                    BTN_HELP, BTN_TOGGLE_ON, BTN_TOGGLE_OFF,
                ]), on_reply_button),
                MessageHandler(filters.Text([BTN_CHANGE]), cmd_start_filters),
                # Тепер — вільний текст
                MessageHandler(filters.TEXT & ~filters.COMMAND, on_city_query),
            ],
            State.CHOOSING_CITY_PICK: [
                CallbackQueryHandler(on_city_pick, pattern=r"^city:"),
                CallbackQueryHandler(on_city_skip, pattern=r"^skip:city$"),
                CallbackQueryHandler(on_action, pattern=r"^action:"),
            ],
            State.CHOOSING_CATEGORY: [
                CallbackQueryHandler(on_category, pattern=r"^cat:"),
                CallbackQueryHandler(on_category_skip, pattern=r"^skip:cat$"),
                CallbackQueryHandler(on_action, pattern=r"^action:"),
            ],
            State.CHOOSING_SUBCATEGORY_QUERY: [
                MessageHandler(filters.Text([
                    BTN_MY_VACANCIES, BTN_MY_PROFILE, BTN_RENT,
                    BTN_HELP, BTN_TOGGLE_ON, BTN_TOGGLE_OFF,
                ]), on_reply_button),
                MessageHandler(filters.Text([BTN_CHANGE]), cmd_start_filters),
                MessageHandler(filters.TEXT & ~filters.COMMAND, on_subcategory_query),
            ],
            State.CHOOSING_SUBCATEGORY_PICK: [
                CallbackQueryHandler(on_subcategory_toggle, pattern=r"^sub:"),
                CallbackQueryHandler(on_subcategory_skip, pattern=r"^skip:sub$"),
                CallbackQueryHandler(on_action, pattern=r"^action:"),
            ],
            State.CHOOSING_JOB_TYPE: [
                CallbackQueryHandler(on_job_type, pattern=r"^jobtype:"),
                CallbackQueryHandler(on_job_type_skip, pattern=r"^skip:jobtype$"),
            ],
            State.CHOOSING_EXPERIENCE: [
                CallbackQueryHandler(on_experience, pattern=r"^exp:"),
                CallbackQueryHandler(on_experience_skip, pattern=r"^skip:exp$"),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", cmd_cancel),
            CommandHandler("settings", cmd_settings),
            CommandHandler("stop", cmd_stop),
            CommandHandler("resume", cmd_resume),
            CommandHandler("help", cmd_help),
            MessageHandler(filters.Text([BTN_MY_VACANCIES]), on_btn_my_vacancies),
            MessageHandler(filters.Text([BTN_MY_PROFILE]), on_btn_my_profile),
            MessageHandler(filters.Text([BTN_RENT]), on_btn_rent_reply),
            MessageHandler(filters.Text([BTN_TOGGLE_ON, BTN_TOGGLE_OFF]), on_btn_toggle),
            MessageHandler(filters.Text([BTN_HELP]), on_btn_help),
        ],
        allow_reentry=True,
        per_message=False,    )

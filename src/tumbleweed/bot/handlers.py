"""Обробники Telegram-бота TumbleWeed.

Флоу: /start → країна → місто → професія → тип зайнятості → досвід → DONE.
Команди: /start, /settings, /stop, /resume, /cancel.
"""
from __future__ import annotations

import logging

from telegram import Update
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
    set_user_enabled,
    upsert_user_profile,
    mark_sent,
)

from .keyboards import (
    country_keyboard,
    city_keyboard,
    main_menu_keyboard,
    profession_keyboard,
    job_type_keyboard,
    experience_keyboard,
)
from .states import State

log = logging.getLogger(__name__)


# ───────────────────────────────────────────────────────
# Утиліти
# ───────────────────────────────────────────────────────

def _db() -> TursoClient:
    """Створити Turso-клієнт на запит."""
    return TursoClient(settings.turso_url, settings.turso_token)


async def _reply_or_edit(update: Update, text: str, keyboard=None) -> None:
    """Відповісти на callback (edit) або на message (reply)."""
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
    """Посилання на RentAlert-бота з передзаповненим chat_id."""
    return f"{settings.rentalert_bot_url}?start=from_tumbleweed_{chat_id}"


# ───────────────────────────────────────────────────────
# /start
# ───────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Вітання + вибір країни."""
    context.user_data.clear()
    chat_id = str(update.effective_chat.id)

    # Якщо вже є профіль — показати меню
    try:
        profile = get_user_profile(_db(), chat_id)
    except Exception as e:
        log.warning("Не вдалось прочитати профіль: %s", e)
        profile = None

    if profile and profile.enabled:
        text = (
            "🌾 *З поверненням у TumbleWeed!*\n\n"
            f"📍 Країна: *{profile.country}*\n"
            f"🏙 Міста: {', '.join(profile.cities) or 'усі'}\n"
            f"💼 Професії: {', '.join(profile.professions) or 'усі'}\n"
            f"⏰ Зайнятість: {', '.join(profile.job_types) or 'будь-яка'}\n"
            f"🎓 Досвід: {profile.experience}\n\n"
            "Що хочеш зробити?"
        )
        await _reply_or_edit(update, text, main_menu_keyboard(_rentalert_url(update.effective_chat.id)))
        return ConversationHandler.END

    text = (
        "🌾 *Вітаю у TumbleWeed!*\n\n"
        "Я допоможу знайти роботу в обраній країні "
        "й покажу, де поруч шукати житло.\n\n"
        "🌍 *Обери країну:*"
    )
    await _reply_or_edit(update, text, country_keyboard())
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
# Крок 2 → 3. Місто → Професія
# ───────────────────────────────────────────────────────

async def on_city(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    _, city = query.data.split(":", 1)
    cities = context.user_data.setdefault("cities", [])
    if city not in cities:
        cities.append(city)

    await query.edit_message_text(
        "💼 *Яка робота цікавить?*\n\n"
        "Обери категорію або введи свою професію текстом:",
        reply_markup=profession_keyboard(),
        parse_mode="Markdown",
    )
    return State.CHOOSING_PROFESSION


async def on_city_skip(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    context.user_data["cities"] = []      # будь-яке місто
    await query.edit_message_text(
        "💼 *Яка робота цікавить?*",
        reply_markup=profession_keyboard(),
        parse_mode="Markdown",
    )
    return State.CHOOSING_PROFESSION


# ───────────────────────────────────────────────────────
# Крок 3 → 4. Професія → Тип зайнятості
# ───────────────────────────────────────────────────────

async def on_profession(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    _, prof = query.data.split(":", 1)
    context.user_data["professions"] = [prof]
    await query.edit_message_text(
        "⏰ *Який тип зайнятості?*",
        reply_markup=job_type_keyboard(),
        parse_mode="Markdown",
    )
    return State.CHOOSING_JOB_TYPE


async def on_profession_custom(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Користувач вибрав «✏️ Ввести своє» — просимо текст."""
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "✏️ *Введи ключове слово професії* (наприклад, `Python`, `водій`, `кухар`):",
        parse_mode="Markdown",
    )
    return State.CHOOSING_PROFESSION


async def on_profession_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Користувач ввів текст — зберігаємо як кастомну професію."""
    text = (update.message.text or "").strip()
    if not text:
        await update.message.reply_text("Будь ласка, введи слово.")
        return State.CHOOSING_PROFESSION

    context.user_data["professions"] = [f"custom:{text}"]
    await update.message.reply_text(
        f"✅ Професія: *{text}*\n\n⏰ *Який тип зайнятості?*",
        reply_markup=job_type_keyboard(),
        parse_mode="Markdown",
    )
    return State.CHOOSING_JOB_TYPE


async def on_profession_skip(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    context.user_data["professions"] = []      # будь-яка
    await query.edit_message_text(
        "⏰ *Який тип зайнятості?*",
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
# Крок 5 → DONE. Досвід → Зберегти профіль
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
    """Зберегти профіль у Turso і показати головне меню."""
    chat_id = str(update.effective_chat.id)
    d = context.user_data

    country = d.get("country") or "ua"
    cities = d.get("cities") or []
    professions = d.get("professions") or []
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

    text = (
        "✅ *Готово!*\n\n"
        f"🌍 Країна: *{country}*\n"
        f"🏙 Міста: {', '.join(cities) or 'будь-яке'}\n"
        f"💼 Професії: {', '.join(p.replace('custom:', '') for p in professions) or 'будь-яка'}\n"
        f"⏰ Зайнятість: {', '.join(job_types) or 'будь-яка'}\n"
        f"🎓 Досвід: {experience}\n\n"
        "🔔 *Сповіщення увімкнено.* Я надсилатиму нові вакансії, які підходять під твої фільтри.\n\n"
        "Перші вакансії прийдуть протягом наступного циклу агрегації."
    )
    await update.callback_query.edit_message_text(
        text,
        reply_markup=main_menu_keyboard(_rentalert_url(update.effective_chat.id)),
        parse_mode="Markdown",
    )
    return ConversationHandler.END


# ───────────────────────────────────────────────────────
# Кнопка «Назад»
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


# ───────────────────────────────────────────────────────
# /settings, /stop, /resume
# ───────────────────────────────────────────────────────

async def cmd_settings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    chat_id = str(update.effective_chat.id)
    try:
        profile = get_user_profile(_db(), chat_id)
    except Exception as e:
        await update.message.reply_text(f"❌ Помилка: {e}")
        return ConversationHandler.END

    if not profile:
        await update.message.reply_text("У тебе ще немає налаштувань. Введи /start.")
        return ConversationHandler.END

    text = (
        "⚙️ *Твої налаштування:*\n\n"
        f"🌍 Країна: *{profile.country}*\n"
        f"🏙 Міста: {', '.join(profile.cities) or 'будь-яке'}\n"
        f"💼 Професії: {', '.join(profile.professions) or 'будь-яка'}\n"
        f"⏰ Зайнятість: {', '.join(profile.job_types) or 'будь-яка'}\n"
        f"🎓 Досвід: {profile.experience}\n"
        f"🔔 Статус: {'▶️ увімкнено' if profile.enabled else '⏸ пауза'}\n\n"
        "Змінити фільтри: /start"
    )
    await update.message.reply_text(text, parse_mode="Markdown")
    return ConversationHandler.END


async def cmd_stop(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    chat_id = str(update.effective_chat.id)
    try:
        set_user_enabled(_db(), chat_id, False)
    except Exception as e:
        await update.message.reply_text(f"❌ Помилка: {e}")
        return ConversationHandler.END
    await update.message.reply_text(
        "⏸ Сповіщення вимкнено. Щоб увімкнути — /resume."
    )
    return ConversationHandler.END


async def cmd_resume(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    chat_id = str(update.effective_chat.id)
    try:
        set_user_enabled(_db(), chat_id, True)
    except Exception as e:
        await update.message.reply_text(f"❌ Помилка: {e}")
        return ConversationHandler.END
    await update.message.reply_text("▶️ Сповіщення увімкнено.")
    return ConversationHandler.END


# ───────────────────────────────────────────────────────
# /cancel
# ───────────────────────────────────────────────────────

async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    await update.message.reply_text("❌ Скасовано. Введи /start, щоб почати знову.")
    return ConversationHandler.END


# ───────────────────────────────────────────────────────
# Загальний обробник action:*
# ───────────────────────────────────────────────────────

async def on_action(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    _, action = query.data.split(":", 1)

    if action == "back_country":
        return await on_back_to_country(update, context)
    if action == "back_city":
        return await on_back_to_city(update, context)
    if action == "custom_prof":
        return await on_profession_custom(update, context)
    if action == "settings":
        await query.edit_message_text(
            "⚙️ Використай команду /settings у чаті з ботом.",
        )
        return ConversationHandler.END

    await query.edit_message_text(f"❓ Невідома дія: {action}")
    return ConversationHandler.END


# ───────────────────────────────────────────────────────
# Кнопка «🚫 Ігнор» під вакансією (працює поза діалогом)
# ───────────────────────────────────────────────────────

async def on_ignore_vacancy(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обробник кнопки «🚫 Ігнор» під вакансією.

    Callback_data: "action:ignore:<vacancy_id>"
    """
    query = update.callback_query
    await query.answer("🚫 Ігноровано")

    parts = query.data.split(":", 2)
    if len(parts) != 3:
        return

    _, action, vacancy_id = parts
    if action != "ignore":
        return

    chat_id = str(update.effective_chat.id)

    # Позначаємо як «надіслану», щоб матчер більше не підхоплював
    try:
        mark_sent(_db(), chat_id, vacancy_id)
        log.info("Користувач %s ігнорує вакансію %s", chat_id, vacancy_id)
    except Exception as e:
        log.warning("Не вдалось позначити ігнор: %s", e)
        return

    # Редагуємо повідомлення — додаємо мітку
    original = query.message.text or ""
    if "🚫 Ігноровано" not in original:
        await query.edit_message_text(
            f"{original}\n\n_🚫 Ігноровано — більше не покажемо_",
            parse_mode="Markdown",
            disable_web_page_preview=True,
        )

# ───────────────────────────────────────────────────────
# Фабрика ConversationHandler
# ───────────────────────────────────────────────────────

def build_conversation_handler() -> ConversationHandler:
    """Створює ConversationHandler з усіма станами."""
    return ConversationHandler(
        entry_points=[CommandHandler("start", cmd_start)],
        states={
            State.CHOOSING_COUNTRY: [
                CallbackQueryHandler(on_country, pattern=r"^country:"),
            ],
            State.CHOOSING_CITY: [
                CallbackQueryHandler(on_city, pattern=r"^city:"),
                CallbackQueryHandler(on_city_skip, pattern=r"^skip:city$"),
                CallbackQueryHandler(on_action, pattern=r"^action:"),
            ],
            State.CHOOSING_PROFESSION: [
                CallbackQueryHandler(on_profession, pattern=r"^prof:"),
                CallbackQueryHandler(on_profession_skip, pattern=r"^skip:prof$"),
                CallbackQueryHandler(on_action, pattern=r"^action:"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, on_profession_text),
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
        ],
        allow_reentry=True,
        per_message=False,
    )

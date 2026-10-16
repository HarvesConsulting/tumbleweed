"""Обробка inline callback'ів від Telegram (sync, без PTB).

Точка входу: handle_callback(callback, ctx).

Формат callback_data:
    country:ua              — обрана країна
    city:kyiv               — обране місто
    cat:it                  — обрана сфера
    sub:it_python           — toggle підкатегорії
    jobtype:full            — тип зайнятості
    exp:no                  — досвід
    skip:city               — пропустити крок
    action:enter_city       — службові дії
    action:back_country
    action:back_city
    action:back_category
    action:search_again
    action:sub_done
    action:ignore_vacancy:VACANCY_ID
"""
from __future__ import annotations

import logging
from typing import Any

from tumbleweed.db.queries_jobs import (
    get_user_profile,
    mark_sent,
    upsert_user_profile,
)
from tumbleweed.services.city_search import get_city, search_cities
from tumbleweed.services.subcategory_search import (
    MIN_QUERY_LEN,
    get_category_label,
    get_subcategory,
    search_subcategories,
)

from . import keyboards as kb
from . import states

log = logging.getLogger(__name__)

MAX_SUBCATEGORIES = 5


# ───────────────────────────────────────────────────────
# Точка входу
# ───────────────────────────────────────────────────────

def handle_callback(callback: dict[str, Any], ctx) -> None:
    """Обробляє один callback_query."""
    cb_id = callback["id"]
    chat_id = str(callback["from"]["id"])
    data = callback.get("data", "")
    message = callback.get("message") or {}
    message_id = message.get("message_id")

    if not data:
        ctx.notifier.answer_callback(cb_id)
        return

    parts = data.split(":")
    action = parts[0]
    args = parts[1:]

    try:
        _dispatch(action, args, chat_id, message_id, cb_id, ctx)
    except Exception as e:
        log.exception("Callback error for %s: %s", data, e)
        ctx.notifier.answer_callback(cb_id, "❌ Помилка")


def _dispatch(
    action: str,
    args: list[str],
    chat_id: str,
    message_id: int | None,
    cb_id: str,
    ctx,
) -> None:
    """Маршрутизація callback за action."""

    if action == "country":
        _handle_country(args[0], chat_id, message_id, cb_id, ctx)
    elif action == "city":
        _handle_city(args[0], chat_id, message_id, cb_id, ctx)
    elif action == "cat":
        _handle_category(args[0], chat_id, message_id, cb_id, ctx)
    elif action == "sub":
        _handle_subcategory_toggle(args[0], chat_id, message_id, cb_id, ctx)
    elif action == "jobtype":
        _handle_job_type(args[0], chat_id, message_id, cb_id, ctx)
    elif action == "exp":
        _handle_experience(args[0], chat_id, message_id, cb_id, ctx)
    elif action == "skip":
        _handle_skip(args[0], chat_id, message_id, cb_id, ctx)
    elif action == "action":
        _handle_action(args, chat_id, message_id, cb_id, ctx)
    else:
        ctx.notifier.answer_callback(cb_id)
        log.warning("Unknown callback action: %s", action)


# ───────────────────────────────────────────────────────
# country:ua
# ───────────────────────────────────────────────────────

def _handle_country(
    country: str,
    chat_id: str,
    message_id: int | None,
    cb_id: str,
    ctx,
) -> None:
    """Вибір країни → показати міста."""
    labels = {"ua": "🇺🇦 Україна", "pl": "🇵🇱 Польща", "ro": "🇷🇴 Румунія"}
    if country not in labels:
        ctx.notifier.answer_callback(cb_id, "❌")
        return

    # Зберігаємо країну в user_data
    states.set_user_data(chat_id, {"country": country, "cities": []})
    states.set_state(chat_id, states.STATE_CHOOSING_CITY)

    label = labels[country]
    ctx.notifier.answer_callback(cb_id, label)

    if message_id:
        ctx.notifier.edit_message(
            chat_id,
            message_id,
            f"📍 *{label}* — обери місто:",
            keyboard=kb.city_keyboard(country),
        )


# ───────────────────────────────────────────────────────
# city:kyiv
# ───────────────────────────────────────────────────────

def _handle_city(
    city_slug: str,
    chat_id: str,
    message_id: int | None,
    cb_id: str,
    ctx,
) -> None:
    """Вибір міста → показати сфери."""
    data = states.get_user_data(chat_id)
    country = data.get("country", "ua")

    city = get_city(country, city_slug)
    if not city:
        ctx.notifier.answer_callback(cb_id, "❌ Місто не знайдено")
        return

    # Оновлюємо user_data
    states.update_user_data(chat_id, cities=[city_slug])
    states.set_state(chat_id, states.STATE_CHOOSING_CATEGORY)

    ctx.notifier.answer_callback(cb_id, f"✅ {city.name}")

    if message_id:
        ctx.notifier.edit_message(
            chat_id,
            message_id,
            f"✅ Обрано: *{city.name}*\n\n💼 *Обери сферу роботи:*",
            keyboard=kb.category_keyboard(),
        )


# ───────────────────────────────────────────────────────
# cat:it
# ───────────────────────────────────────────────────────

def _handle_category(
    cat_key: str,
    chat_id: str,
    message_id: int | None,
    cb_id: str,
    ctx,
) -> None:
    """Вибір сфери → запитати пошук підкатегорій."""
    cat_label = get_category_label(cat_key)

    states.update_user_data(
        chat_id,
        category=cat_key,
        selected_subs=set(),
    )
    states.set_state(chat_id, states.STATE_WAITING_SUBCATEGORY_QUERY)

    ctx.notifier.answer_callback(cb_id)

    if message_id:
        ctx.notifier.edit_message(
            chat_id,
            message_id,
            f"*{cat_label}*\n\n"
            f"✏️ Введи слово для пошуку підкатегорії (мін. {MIN_QUERY_LEN} символи).\n"
            "Наприклад: `трак`, `водій`, `python`, `кух`\n\n"
            f"Можна обрати до {MAX_SUBCATEGORIES} підкатегорій.",
        )


# ───────────────────────────────────────────────────────
# sub:it_python — toggle
# ───────────────────────────────────────────────────────

def _handle_subcategory_toggle(
    sub_key: str,
    chat_id: str,
    message_id: int | None,
    cb_id: str,
    ctx,
) -> None:
    """Toggle підкатегорії ✅/⬜."""
    data = states.get_user_data(chat_id)
    selected: set = data.get("selected_subs") or set()
    if not isinstance(selected, set):
        selected = set(selected)

    category = data.get("category", "")
    results = data.get("last_results") or []

    if sub_key in selected:
        selected.discard(sub_key)
    else:
        if len(selected) >= MAX_SUBCATEGORIES:
            ctx.notifier.answer_callback(
                cb_id,
                f"⚠️ Максимум {MAX_SUBCATEGORIES}",
                show_alert=True,
            )
            return
        selected.add(sub_key)

    states.update_user_data(chat_id, selected_subs=selected)

    ctx.notifier.answer_callback(cb_id)

    if message_id:
        ctx.notifier.edit_reply_markup(
            chat_id,
            message_id,
            kb.subcategory_results_keyboard(
                results=results,
                selected=selected,
                category_key=category,
                category_label=get_category_label(category),
            ),
        )


# ───────────────────────────────────────────────────────
# jobtype:full
# ───────────────────────────────────────────────────────

def _handle_job_type(
    jt: str,
    chat_id: str,
    message_id: int | None,
    cb_id: str,
    ctx,
) -> None:
    """Тип зайнятості → перейти до досвіду."""
    states.update_user_data(chat_id, job_types=[jt])
    states.set_state(chat_id, states.STATE_CHOOSING_EXPERIENCE)

    ctx.notifier.answer_callback(cb_id)

    if message_id:
        ctx.notifier.edit_message(
            chat_id,
            message_id,
            "🎓 *Який досвід?*",
            keyboard=kb.experience_keyboard(),
        )


# ───────────────────────────────────────────────────────
# exp:no — фінал
# ───────────────────────────────────────────────────────

def _handle_experience(
    exp: str,
    chat_id: str,
    message_id: int | None,
    cb_id: str,
    ctx,
) -> None:
    """Досвід → зберегти профіль (фінал)."""
    states.update_user_data(chat_id, experience=exp)
    ctx.notifier.answer_callback(cb_id)
    _finalize(chat_id, message_id, ctx)


def _finalize(chat_id: str, message_id: int | None, ctx) -> None:
    """Зберігає профіль і показує фінал."""
    data = states.get_user_data(chat_id)

    country = data.get("country") or "ua"
    cities = data.get("cities") or []
    selected = data.get("selected_subs") or set()
    professions = list(selected) if selected else []
    job_types = data.get("job_types") or []
    experience = data.get("experience") or "all"

    try:
        upsert_user_profile(
            ctx.client,
            chat_id=chat_id,
            country=country,
            cities=cities,
            professions=professions,
            job_types=job_types,
            experience=experience,
        )
    except Exception as e:
        log.exception("Помилка збереження профілю: %s", e)
        ctx.notifier.send_message(chat_id, f"❌ Помилка: {e}")
        return

    # Перечитуємо для канонічного summary
    from .handlers import _profile_summary_text

    try:
        profile = get_user_profile(ctx.client, chat_id)
        summary = _profile_summary_text(profile) if profile else "✅ Збережено."
    except Exception:
        summary = "✅ Збережено."

    # Reply-клавіатура
    ctx.notifier.send_message(
        chat_id,
        "🔍 *Розпочинаю пошук!*\n\n"
        "Знизу 👇 — кнопки:\n"
        "📄 *Моє резюме* — створити резюме\n"
        "👤 *Мій профіль* — налаштування\n"
        "🔍 *Знайти роботу* — змінити сферу/місто\n"
        "🏠 *Житло* — RentAlert\n"
        "🔔 *Сповіщення* — увімк/вимк\n"
        "❓ *Допомога* — довідка\n\n"
        "Перші вакансії надійдуть автоматично.",
        keyboard=kb.main_reply_keyboard(enabled=True),
    )

    # Фінальний текст (без inline)
    if message_id:
        ctx.notifier.edit_message(
            chat_id,
            message_id,
            f"✅ *Готово!*\n\n{summary}\n\n🔔 *Сповіщення увімкнено.*",
        )

    states.clear_state(chat_id)
    states.clear_user_data(chat_id)


# ───────────────────────────────────────────────────────
# skip:city / skip:cat / skip:sub / skip:jobtype / skip:exp
# ───────────────────────────────────────────────────────

def _handle_skip(
    step: str,
    chat_id: str,
    message_id: int | None,
    cb_id: str,
    ctx,
) -> None:
    """Пропустити крок."""
    ctx.notifier.answer_callback(cb_id)

    if step == "city":
        states.update_user_data(chat_id, cities=[])
        states.set_state(chat_id, states.STATE_CHOOSING_CATEGORY)
        if message_id:
            ctx.notifier.edit_message(
                chat_id,
                message_id,
                "💼 *Обери сферу роботи:*",
                keyboard=kb.category_keyboard(),
            )

    elif step == "cat":
        states.update_user_data(chat_id, professions=[], selected_subs=set())
        states.set_state(chat_id, states.STATE_CHOOSING_JOB_TYPE)
        if message_id:
            ctx.notifier.edit_message(
                chat_id,
                message_id,
                "⏰ *Який тип зайнятості?*",
                keyboard=kb.job_type_keyboard(),
            )

    elif step == "sub":
        states.update_user_data(chat_id, selected_subs=set())
        states.set_state(chat_id, states.STATE_CHOOSING_JOB_TYPE)
        if message_id:
            ctx.notifier.edit_message(
                chat_id,
                message_id,
                "🌍 Будеш отримувати всі вакансії цієї сфери.\n\n⏰ *Який тип зайнятості?*",
                keyboard=kb.job_type_keyboard(),
            )

    elif step == "jobtype":
        states.update_user_data(chat_id, job_types=[])
        states.set_state(chat_id, states.STATE_CHOOSING_EXPERIENCE)
        if message_id:
            ctx.notifier.edit_message(
                chat_id,
                message_id,
                "🎓 *Який досвід?*",
                keyboard=kb.experience_keyboard(),
            )

    elif step == "exp":
        states.update_user_data(chat_id, experience="all")
        _finalize(chat_id, message_id, ctx)


# ───────────────────────────────────────────────────────
# action:*
# ───────────────────────────────────────────────────────

def _handle_action(
    args: list[str],
    chat_id: str,
    message_id: int | None,
    cb_id: str,
    ctx,
) -> None:
    """Службові дії."""
    if not args:
        ctx.notifier.answer_callback(cb_id)
        return

    action = args[0]
    ctx.notifier.answer_callback(cb_id)

    if action == "enter_city":
        # Перейти у стан очікування міста
        states.set_state(chat_id, states.STATE_WAITING_CITY_QUERY)
        if message_id:
            data = states.get_user_data(chat_id)
            country = data.get("country", "ua")
            labels = {"ua": "🇺🇦 України", "pl": "🇵🇱 Польщі", "ro": "🇷🇴 Румунії"}
            ctx.notifier.edit_message(
                chat_id,
                message_id,
                f"✏️ *Введи назву міста* у {labels.get(country, '')}:\n\n"
                "Наприклад: `Тернопіль`, `Краків`, `Cluj`\n\n"
                "Мінімум 2 символи.",
            )

    elif action == "back_country":
        states.set_state(chat_id, states.STATE_CHOOSING_COUNTRY)
        if message_id:
            ctx.notifier.edit_message(
                chat_id,
                message_id,
                "🌍 *Обери країну:*",
                keyboard=kb.country_keyboard(),
            )

    elif action == "back_city":
        data = states.get_user_data(chat_id)
        country = data.get("country", "ua")
        states.set_state(chat_id, states.STATE_CHOOSING_CITY)
        if message_id:
            ctx.notifier.edit_message(
                chat_id,
                message_id,
                "📍 *Обери місто:*",
                keyboard=kb.city_keyboard(country),
            )

    elif action == "back_category":
        states.update_user_data(chat_id, selected_subs=set())
        states.set_state(chat_id, states.STATE_CHOOSING_CATEGORY)
        if message_id:
            ctx.notifier.edit_message(
                chat_id,
                message_id,
                "💼 *Обери сферу роботи:*",
                keyboard=kb.category_keyboard(),
            )

    elif action == "search_again":
        data = states.get_user_data(chat_id)
        category = data.get("category", "")
        cat_label = get_category_label(category) if category else ""
        states.set_state(chat_id, states.STATE_WAITING_SUBCATEGORY_QUERY)
        if message_id:
            ctx.notifier.edit_message(
                chat_id,
                message_id,
                f"*{cat_label}*\n\n"
                f"✏️ Введи нове слово для пошуку (мін. {MIN_QUERY_LEN} символи).",
            )

    elif action == "sub_done":
        # Завершити вибір підкатегорій
        data = states.get_user_data(chat_id)
        selected: set = data.get("selected_subs") or set()
        states.update_user_data(chat_id, professions=list(selected) if selected else [])
        states.set_state(chat_id, states.STATE_CHOOSING_JOB_TYPE)

        if message_id:
            if selected:
                labels = []
                category = data.get("category", "")
                for sk in selected:
                    sub = get_subcategory(category, sk)
                    labels.append(f"✅ {sub.label}" if sub else f"✅ {sk}")
                text = "Обрано:\n" + "\n".join(labels) + "\n\n⏰ *Який тип зайнятості?*"
            else:
                text = "🌍 Будеш отримувати всі вакансії цієї сфери.\n\n⏰ *Який тип зайнятості?*"

            ctx.notifier.edit_message(
                chat_id,
                message_id,
                text,
                keyboard=kb.job_type_keyboard(),
            )

    elif action == "ignore_vacancy":
        # args: ["ignore_vacancy", vacancy_id]
        if len(args) >= 2:
            vacancy_id = args[1]
            try:
                mark_sent(ctx.client, chat_id, vacancy_id)
                ctx.notifier.answer_callback(cb_id, "🚫 Ігноровано")
            except Exception as e:
                log.warning("ignore_vacancy: %s", e)


# ───────────────────────────────────────────────────────
# FSM: обробка тексту міста (викликається з dispatcher)
# ───────────────────────────────────────────────────────

def handle_city_text(chat_id: str, text: str, ctx) -> None:
    """Обробка введення міста текстом."""
    data = states.get_user_data(chat_id)
    country = data.get("country", "ua")

    results = search_cities(country, text, limit=3)

    if not results:
        ctx.notifier.send_message(
            chat_id,
            f"🔍 За запитом *{text}* нічого не знайдено.\n\n"
            "Спробуй іншу назву або обери «🌍 Будь-яке місто».",
            keyboard=kb.city_empty_keyboard(text),
        )
        states.set_state(chat_id, states.STATE_CHOOSING_CITY)
        return

    states.set_state(chat_id, states.STATE_CHOOSING_CITY)
    ctx.notifier.send_message(
        chat_id,
        f"🔍 За запитом *{text}* знайдено {len(results)}:\n\nОбери місто:",
        keyboard=kb.city_results_keyboard(results, text),
    )


def handle_subcategory_text(chat_id: str, text: str, ctx) -> None:
    """Обробка введення слова для пошуку підкатегорій."""
    data = states.get_user_data(chat_id)
    category = data.get("category", "")
    cat_label = get_category_label(category) if category else ""

    if len(text) < MIN_QUERY_LEN:
        ctx.notifier.send_message(
            chat_id,
            f"⚠️ Занадто короткий запит. Введи мінімум {MIN_QUERY_LEN} символи.",
        )
        return

    results = search_subcategories(category, text, limit=8)
    states.update_user_data(chat_id, last_results=results)

    if not results:
        ctx.notifier.send_message(
            chat_id,
            f"🔍 За запитом *{text}* нічого не знайдено в _{cat_label}_.",
            keyboard=kb.subcategory_empty_keyboard(cat_label),
        )
        return

    selected = data.get("selected_subs") or set()
    ctx.notifier.send_message(
        chat_id,
        f"🔍 За запитом *{text}* знайдено:\n\n"
        f"Клікни, щоб обрати (✅) або зняти (⬜). Максимум {MAX_SUBCATEGORIES}.",
        keyboard=kb.subcategory_results_keyboard(
            results=results,
            selected=selected,
            category_key=category,
            category_label=cat_label,
        ),
    )

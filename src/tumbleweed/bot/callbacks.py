"""Обробка inline callback'ів від Telegram (sync, без PTB).

Точка входу: handle_callback(callback, ctx).

Формат callback_data:
    country:ua              — обрана країна
    city:kyiv               — обране місто
    cat:it                  — обрана сфера
    sub:it_backend          — обрана підкатегорія (фінальний вибір, одразу → job_type)
    jobtype:full            — toggle типу зайнятості (мультивибір)
    exp:1-3                 — обраний досвід (фінальний, → finalize)
    skip:city|cat|sub|jobtype|exp — пропустити крок
    action:...              — службові дії
    sub_del:<id>            — видалити підписку
    sub_toggle:<id>         — пауза/увімкнути підписку
"""
from __future__ import annotations

import logging
from typing import Any

from tumbleweed.db.queries_jobs import (
    Subscription,
    add_subscription,
    get_subscription,
    list_subscriptions,
    remove_subscription,
    set_subscription_enabled,
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
        _handle_subcategory(args[0], chat_id, message_id, cb_id, ctx)
    elif action == "jobtype":
        _handle_job_type_toggle(args[0], chat_id, message_id, cb_id, ctx)
    elif action == "exp":
        _handle_experience(args[0], chat_id, message_id, cb_id, ctx)
    elif action == "skip":
        _handle_skip(args[0], chat_id, message_id, cb_id, ctx)
    elif action == "sub_del":
        _handle_sub_del(args[0], chat_id, cb_id, ctx)
    elif action == "sub_toggle":
        _handle_sub_toggle(args[0], chat_id, cb_id, ctx)
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
    """Вибір сфери → запитати пошук підкатегорії."""
    data = states.get_user_data(chat_id)
    country = data.get("country", "ua")
    cat_label = get_category_label(cat_key, country=country)

    states.update_user_data(
        chat_id,
        category=cat_key,
        selected_sub="",
        last_results=[],
    )
    states.set_state(chat_id, states.STATE_WAITING_SUBCATEGORY_QUERY)

    ctx.notifier.answer_callback(cb_id)

    if message_id:
        ctx.notifier.edit_message(
            chat_id,
            message_id,
            f"*{cat_label}*\n\n"
            f"✏️ Введи слово для пошуку професії (мін. {MIN_QUERY_LEN} символи).\n"
            "Наприклад: `трак`, `водій`, `python`, `кух`",
        )


# ───────────────────────────────────────────────────────
# sub:agro_tractor — фінальний вибір підкатегорії
# ───────────────────────────────────────────────────────

def _handle_subcategory(
    sub_key: str,
    chat_id: str,
    message_id: int | None,
    cb_id: str,
    ctx,
) -> None:
    """Вибір підкатегорії → одразу перехід до job_type."""
    data = states.get_user_data(chat_id)
    category = data.get("category", "")
    results = data.get("last_results") or []

    # Знайти label для повідомлення
    sub_label = sub_key
    for s in results:
        if getattr(s, "key", None) == sub_key:
            sub_label = s.label
            break

    states.update_user_data(chat_id, selected_sub=sub_key)
    states.update_user_data(chat_id, job_types=[], experience="all")
    states.set_state(chat_id, states.STATE_CHOOSING_JOB_TYPE)

    ctx.notifier.answer_callback(cb_id, f"✅ {sub_label}")

    if message_id:
        ctx.notifier.edit_message(
            chat_id,
            message_id,
            f"✅ Обрано: *{sub_label}*\n\n"
            "⏰ *Який тип зайнятості?* (можна кілька)",
            keyboard=kb.job_type_keyboard(selected=[]),
        )


# ───────────────────────────────────────────────────────
# jobtype:full — toggle у мультивиборі
# ───────────────────────────────────────────────────────

def _handle_job_type_toggle(
    jt: str,
    chat_id: str,
    message_id: int | None,
    cb_id: str,
    ctx,
) -> None:
    """Toggle типу зайнятості (мультивибір)."""
    data = states.get_user_data(chat_id)
    selected: list[str] = list(data.get("job_types") or [])

    if jt in selected:
        selected.remove(jt)
    else:
        selected.append(jt)

    states.update_user_data(chat_id, job_types=selected)

    ctx.notifier.answer_callback(cb_id)

    if message_id:
        ctx.notifier.edit_reply_markup(
            chat_id,
            message_id,
            kb.job_type_keyboard(selected=selected),
        )


# ───────────────────────────────────────────────────────
# exp:1-3 — фінал
# ───────────────────────────────────────────────────────

def _handle_experience(
    exp: str,
    chat_id: str,
    message_id: int | None,
    cb_id: str,
    ctx,
) -> None:
    """Досвід → зберегти підписку (фінал)."""
    states.update_user_data(chat_id, experience=exp)
    ctx.notifier.answer_callback(cb_id)
    _finalize(chat_id, message_id, ctx)


def _finalize(chat_id: str, message_id: int | None, ctx) -> None:
    """Створює підписку на основі user_data."""
    data = states.get_user_data(chat_id)

    country = data.get("country") or "ua"
    cities = data.get("cities") or []
    city_slug = cities[0] if cities else ""
    profession_key = data.get("selected_sub") or ""
    job_types = data.get("job_types") or []
    experience = data.get("experience") or "all"

    # Створюємо підписку
    try:
        sub = add_subscription(
            ctx.client,
            chat_id=chat_id,
            country=country,
            city_slug=city_slug,
            profession_key=profession_key,
            job_types=job_types,
            experience=experience,
        )
    except Exception as e:
        log.exception("add_subscription: %s", e)
        ctx.notifier.send_message(chat_id, f"❌ Помилка: {e}")
        states.clear_state(chat_id)
        states.clear_user_data(chat_id)
        return

    if not sub:
        ctx.notifier.send_message(chat_id, "❌ Не вдалось створити пошук.")
        states.clear_state(chat_id)
        states.clear_user_data(chat_id)
        return

    # Читаємо свіжий список для summary
    try:
        all_subs = list_subscriptions(ctx.client, chat_id, only_enabled=False)
    except Exception:
        all_subs = [sub]

    # Формуємо summary
    from .handlers import _profession_label, _city_label
    city_name = _city_label(country, city_slug)
    prof_label = _profession_label(profession_key, country)

    text = (
        "✅ *Пошук додано!*\n\n"
        f"🏙 {city_name}\n"
        f"💼 {prof_label}\n"
    )
    if job_types:
        labels = {"full": "Повна", "part": "Часткова", "remote": "Віддалена"}
        text += f"⏰ {', '.join(labels.get(j, j) for j in job_types)}\n"
    if experience and experience != "all":
        exp_labels = {"no": "Без досвіду", "1-3": "1-3 роки", "3+": "3+ роки"}
        text += f"🎓 {exp_labels.get(experience, experience)}\n"

    text += (
        "\n━━━━━━━━━━━━━━━━━━━\n"
        "🔍 *Що далі?*\n\n"
        "Я перевіряю нові вакансії *кожні 30 хвилин*.\n\n"
        "📬 *Перші результати* надійдуть протягом 30 хвилин — "
        "топ-10 з усіх джерел (OLX, Work.ua, Robota.ua, Pidbir.ua).\n\n"
        "🔔 *Далі* — тільки нові, миттєво.\n\n"
        "💡 Можеш закрити Telegram — я напишу сам, коли щось знайду.\n"
        "━━━━━━━━━━━━━━━━━━━"
    )

    if message_id:
        ctx.notifier.edit_message(chat_id, message_id, text)
    else:
        ctx.notifier.send_message(chat_id, text)

    # Reply-клавіатура + inline зі списком
    ctx.notifier.send_message(
        chat_id,
        f"📋 *Всього пошуків: {len(all_subs)}*",
        keyboard=kb.subscriptions_list_keyboard(all_subs),
    )
    ctx.notifier.send_message(
        chat_id,
        "⌨️ Меню — знизу 👇",
        keyboard=kb.main_reply_keyboard(enabled=True),
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
        states.update_user_data(chat_id, selected_sub="", category="")
        states.set_state(chat_id, states.STATE_CHOOSING_JOB_TYPE)
        if message_id:
            ctx.notifier.edit_message(
                chat_id,
                message_id,
                "🌍 Будеш отримувати всі вакансії.\n\n"
                "⏰ *Який тип зайнятості?* (можна кілька)",
                keyboard=kb.job_type_keyboard(selected=[]),
            )

    elif step == "sub":
        states.update_user_data(chat_id, selected_sub="")
        states.set_state(chat_id, states.STATE_CHOOSING_JOB_TYPE)
        if message_id:
            ctx.notifier.edit_message(
                chat_id,
                message_id,
                "🌍 Будеш отримувати всі вакансії цієї сфери.\n\n"
                "⏰ *Який тип зайнятості?* (можна кілька)",
                keyboard=kb.job_type_keyboard(selected=[]),
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
# sub_del:N / sub_toggle:N
# ───────────────────────────────────────────────────────

def _handle_sub_del(
    sub_id_str: str,
    chat_id: str,
    cb_id: str,
    ctx,
) -> None:
    """Видалити підписку."""
    try:
        sub_id = int(sub_id_str)
    except ValueError:
        ctx.notifier.answer_callback(cb_id, "❌")
        return

    ok = remove_subscription(ctx.client, chat_id, sub_id)
    if ok:
        ctx.notifier.answer_callback(cb_id, "🗑 Видалено")
    else:
        ctx.notifier.answer_callback(cb_id, "⚠️ Не знайдено")

    # Оновлюємо список
    _refresh_subs_list(chat_id, ctx)


def _handle_sub_toggle(
    sub_id_str: str,
    chat_id: str,
    cb_id: str,
    ctx,
) -> None:
    """Пауза/увімкнення підписки."""
    try:
        sub_id = int(sub_id_str)
    except ValueError:
        ctx.notifier.answer_callback(cb_id, "❌")
        return

    sub = get_subscription(ctx.client, sub_id)
    if not sub or sub.chat_id != chat_id:
        ctx.notifier.answer_callback(cb_id, "⚠️ Не знайдено")
        return

    new_state = not sub.enabled
    set_subscription_enabled(ctx.client, sub_id, new_state)
    ctx.notifier.answer_callback(cb_id, "▶️ Увімкнено" if new_state else "⏸ Пауза")

    _refresh_subs_list(chat_id, ctx)


def _refresh_subs_list(chat_id: str, ctx) -> None:
    """Перемальовує список підписок."""
    try:
        subs = list_subscriptions(ctx.client, chat_id, only_enabled=False)
    except Exception as e:
        log.warning("list_subscriptions: %s", e)
        return

    from .handlers import _subscriptions_summary_text
    text = _subscriptions_summary_text(subs)
    keyboard = kb.subscriptions_list_keyboard(subs) if subs else None

    # Надсилаємо нове повідомлення (бо в inline edit-reply-markup
    # не змінює текст — треба перемалювати повідомлення)
    ctx.notifier.send_message(chat_id, text, keyboard=keyboard)


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
        states.update_user_data(chat_id, selected_sub="", last_results=[])
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
        country = data.get("country", "ua")
        cat_label = get_category_label(category, country=country) if category else ""
        states.set_state(chat_id, states.STATE_WAITING_SUBCATEGORY_QUERY)
        if message_id:
            ctx.notifier.edit_message(
                chat_id,
                message_id,
                f"*{cat_label}*\n\n"
                f"✏️ Введи нове слово для пошуку (мін. {MIN_QUERY_LEN} символи).",
            )

    elif action == "jobtype_done":
        # Завершити вибір job_types → перейти до досвіду
        states.set_state(chat_id, states.STATE_CHOOSING_EXPERIENCE)
        if message_id:
            ctx.notifier.edit_message(
                chat_id,
                message_id,
                "🎓 *Який досвід?*",
                keyboard=kb.experience_keyboard(),
            )

    elif action == "add_sub":
        # Почати flow нової підписки (з reply-кнопки)
        from .handlers import on_btn_find_job
        on_btn_find_job(chat_id, ctx)

    elif action == "show_subs":
        from .handlers import on_btn_my_subs
        on_btn_my_subs(chat_id, ctx)

    elif action == "ignore_vacancy":
        # args: ["ignore_vacancy", vacancy_id]
        if len(args) >= 2:
            vacancy_id = args[1]
            try:
                from tumbleweed.db.queries_jobs import mark_sent
                mark_sent(ctx.client, chat_id, vacancy_id)
                ctx.notifier.answer_callback(cb_id, "🚫 Ігноровано")
            except Exception as e:
                log.warning("ignore_vacancy: %s", e)


# ───────────────────────────────────────────────────────
# FSM: обробка тексту
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
    country = data.get("country", "ua")
    cat_label = get_category_label(category, country=country) if category else ""

    if len(text) < MIN_QUERY_LEN:
        ctx.notifier.send_message(
            chat_id,
            f"⚠️ Занадто короткий запит. Введи мінімум {MIN_QUERY_LEN} символи.",
        )
        return

    results = search_subcategories(category, text, limit=8, country=country)
    states.update_user_data(chat_id, last_results=results)

    if not results:
        ctx.notifier.send_message(
            chat_id,
            f"🔍 За запитом *{text}* нічого не знайдено в _{cat_label}_.",
            keyboard=kb.subcategory_empty_keyboard(cat_label),
        )
        return

    ctx.notifier.send_message(
        chat_id,
        f"🔍 За запитом *{text}* знайдено:\n\n"
        "Клікни професію, щоб обрати її для цього пошуку.",
        keyboard=kb.subcategory_results_keyboard(
            results=results,
            category_key=category,
            category_label=cat_label,
            selected="",
        ),
    )

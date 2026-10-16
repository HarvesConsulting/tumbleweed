"""Створення таблиць TumbleWeed у Turso.

Спільна БД з RentAlert, але свої таблиці:
  vacancies, seen_vacancies,
  user_jobs (legacy, для сумісності),
  user_subscriptions (нова модель, багато підписок на chat_id),
  user_seen_vacancies
"""
from __future__ import annotations

import logging

from .client import TursoClient, TursoError

log = logging.getLogger(__name__)


SCHEMA_SQL = [
    # ─────────────────────────────────────────────────
    # Вакансії
    # ─────────────────────────────────────────────────
    """
    CREATE TABLE IF NOT EXISTS vacancies (
        id TEXT PRIMARY KEY,
        raw_id TEXT NOT NULL,
        source_key TEXT NOT NULL,
        country TEXT NOT NULL,
        city_slug TEXT NOT NULL,
        title TEXT NOT NULL,
        company TEXT,
        salary TEXT,
        job_type TEXT,
        experience TEXT,
        description TEXT,
        link TEXT NOT NULL,
        photo TEXT,
        created_at DATETIME,
        saved_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_vacancies_city ON vacancies(country, city_slug, created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_vacancies_source ON vacancies(source_key)",

    # ─────────────────────────────────────────────────
    # Дедуплікація вакансій (глобальна)
    # ─────────────────────────────────────────────────
    """
    CREATE TABLE IF NOT EXISTS seen_vacancies (
        id TEXT PRIMARY KEY,
        raw_id TEXT NOT NULL,
        source_key TEXT NOT NULL,
        country TEXT NOT NULL,
        city_slug TEXT NOT NULL,
        title TEXT NOT NULL,
        company TEXT,
        salary TEXT,
        link TEXT NOT NULL,
        created_at DATETIME,
        seen_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_seen_city ON seen_vacancies(city_slug, seen_at DESC)",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_seen_source_raw ON seen_vacancies(source_key, raw_id)",

    # ─────────────────────────────────────────────────
    # LEGACY: user_jobs — один рядок на chat_id
    # Залишаємо для сумісності, поки триває міграція на user_subscriptions.
    # Буде видалено після Кроку 3.5.
    # ─────────────────────────────────────────────────
    """
    CREATE TABLE IF NOT EXISTS user_jobs (
        chat_id TEXT PRIMARY KEY,
        country TEXT NOT NULL,
        cities TEXT,
        professions TEXT,
        job_types TEXT,
        experience TEXT,
        enabled INTEGER DEFAULT 1,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_user_jobs_enabled ON user_jobs(enabled)",

    # ─────────────────────────────────────────────────
    # ПІДПИСКИ (user_subscriptions) — нова модель
    # Один рядок = одна підписка (chat_id, city_slug, profession_key).
    # Користувач може мати багато підписок:
    #   Київ+Кухар, Київ+Водій, Львів+Кухар, ...
    #
    # profession_key:
    #   ""                — «будь-яка професія»
    #   "agro_tractor"    — конкретна підкатегорія
    #   "custom:водій"    — кастомна (вільний текст)
    #
    # baseline_done:
    #   0 — перший парсинг ще не зроблено → покажемо топ-5 з джерела
    #   1 — baseline зроблено → показуємо тільки нові (saved_at > last_parsed_at)
    # ─────────────────────────────────────────────────
    """
    CREATE TABLE IF NOT EXISTS user_subscriptions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        chat_id TEXT NOT NULL,
        country TEXT NOT NULL,
        city_slug TEXT NOT NULL,
        profession_key TEXT NOT NULL DEFAULT '',
        job_types TEXT,
        experience TEXT DEFAULT 'all',
        enabled INTEGER DEFAULT 1,
        baseline_done INTEGER DEFAULT 0,
        last_parsed_at DATETIME,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        UNIQUE (chat_id, city_slug, profession_key)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_subs_chat ON user_subscriptions(chat_id, enabled)",
    "CREATE INDEX IF NOT EXISTS idx_subs_active ON user_subscriptions(enabled, country)",
    "CREATE INDEX IF NOT EXISTS idx_subs_baseline ON user_subscriptions(enabled, baseline_done)",

    # ─────────────────────────────────────────────────
    # Що кому надіслали (per-user дедуплікація)
    # Одна вакансія може матчити кілька підписок одного юзера —
    # тут зберігається, щоб не надсилати двічі.
    # ─────────────────────────────────────────────────
    """
    CREATE TABLE IF NOT EXISTS user_seen_vacancies (
        chat_id TEXT NOT NULL,
        vacancy_id TEXT NOT NULL,
        sent_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (chat_id, vacancy_id)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_usv_chat ON user_seen_vacancies(chat_id, sent_at DESC)",
]


def ensure_schema(client: TursoClient) -> None:
    """Ідемпотентно створює всі таблиці TumbleWeed."""
    for sql in SCHEMA_SQL:
        try:
            client.execute_non_query(sql)
        except TursoError as e:
            log.error("Не вдалося виконати SQL: %s\n  %s", sql[:80], e)
            raise
    log.info("✅ Схему TumbleWeed створено (%d запитів)", len(SCHEMA_SQL))

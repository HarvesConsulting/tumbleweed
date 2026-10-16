"""CRUD-запити для TumbleWeed."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from tumbleweed.parsers.base_job import Vacancy

from .client import TursoClient

log = logging.getLogger(__name__)


# ───────────────────────────────────────────────────────
# Вакансії
# ───────────────────────────────────────────────────────

def is_seen(client: TursoClient, source_key: str, raw_id: str) -> bool:
    rows = client.execute(
        "SELECT 1 FROM seen_vacancies WHERE source_key = ? AND raw_id = ? LIMIT 1",
        [source_key, raw_id],
    )
    return bool(rows)


def save_vacancy(client: TursoClient, v: Vacancy) -> None:
    client.execute_non_query(
        """
        INSERT OR IGNORE INTO vacancies
            (id, raw_id, source_key, country, city_slug, title, company,
             salary, job_type, experience, description, link, photo, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            v.id, v.raw_id, v.source_key, v.country, v.city_slug, v.title,
            v.company, v.salary, v.job_type, v.experience, v.description,
            v.link, v.photo, v.created_at,
        ],
    )


def mark_seen(client: TursoClient, v: Vacancy) -> None:
    client.execute_non_query(
        """
        INSERT OR IGNORE INTO seen_vacancies
            (id, raw_id, source_key, country, city_slug, title, company,
             salary, link, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            v.id, v.raw_id, v.source_key, v.country, v.city_slug, v.title,
            v.company, v.salary, v.link, v.created_at,
        ],
    )


def save_and_mark(client: TursoClient, v: Vacancy) -> bool:
    """Зберігає вакансію + позначає як побачену.

    Використовує INSERT OR IGNORE — дедуплікація через PRIMARY KEY.
    Повертає True, якщо вакансія була новою (тобто INSERT вставив рядок).
    """
    try:
        # Одразу вставляємо в seen_vacancies — якщо вже є, IGNORE не вставить
        result = client.execute_non_query(
            """
            INSERT OR IGNORE INTO seen_vacancies
                (id, raw_id, source_key, country, city_slug, title, company,
                 salary, link, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                v.id, v.raw_id, v.source_key, v.country, v.city_slug, v.title,
                v.company, v.salary, v.link, v.created_at,
            ],
        )
        if result == 0:
            # Вже було — не нова
            return False

        # Нова — зберігаємо в vacancies
        client.execute_non_query(
            """
            INSERT OR IGNORE INTO vacancies
                (id, raw_id, source_key, country, city_slug, title, company,
                 salary, job_type, experience, description, link, photo, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                v.id, v.raw_id, v.source_key, v.country, v.city_slug, v.title,
                v.company, v.salary, v.job_type, v.experience, v.description,
                v.link, v.photo, v.created_at,
            ],
        )
        return True
    except Exception as e:
        print(f"⚠️ save_and_mark: {e}")
        return False


# ───────────────────────────────────────────────────────
# Користувачі
# ───────────────────────────────────────────────────────

@dataclass
class UserJobProfile:
    chat_id: str
    country: str
    cities: list[str]
    professions: list[str]
    job_types: list[str]
    experience: str
    enabled: bool


def _row_to_profile(row: list[Any]) -> UserJobProfile:
    chat_id, country, cities, professions, job_types, experience, enabled = row
    return UserJobProfile(
        chat_id=str(chat_id),
        country=str(country),
        cities=json.loads(cities) if cities else [],
        professions=json.loads(professions) if professions else [],
        job_types=json.loads(job_types) if job_types else [],
        experience=str(experience or "all"),
        enabled=bool(int(enabled or 0)),
    )


def get_user_profile(client: TursoClient, chat_id: str) -> UserJobProfile | None:
    rows = client.execute(
        """
        SELECT chat_id, country, cities, professions, job_types, experience, enabled
        FROM user_jobs WHERE chat_id = ? LIMIT 1
        """,
        [chat_id],
    )
    return _row_to_profile(rows[0]) if rows else None


def upsert_user_profile(
    client: TursoClient,
    chat_id: str,
    country: str,
    cities: list[str],
    professions: list[str] | None = None,
    job_types: list[str] | None = None,
    experience: str = "all",
) -> None:
    client.execute_non_query(
        """
        INSERT INTO user_jobs (chat_id, country, cities, professions, job_types, experience, enabled)
        VALUES (?, ?, ?, ?, ?, ?, 1)
        ON CONFLICT(chat_id) DO UPDATE SET
            country = excluded.country,
            cities = excluded.cities,
            professions = excluded.professions,
            job_types = excluded.job_types,
            experience = excluded.experience,
            enabled = 1
        """,
        [
            chat_id,
            country,
            json.dumps(cities),
            json.dumps(professions or []),
            json.dumps(job_types or []),
            experience,
        ],
    )


def set_user_enabled(client: TursoClient, chat_id: str, enabled: bool) -> None:
    client.execute_non_query(
        "UPDATE user_jobs SET enabled = ? WHERE chat_id = ?",
        [1 if enabled else 0, chat_id],
    )


def list_active_profiles(client: TursoClient) -> list[UserJobProfile]:
    rows = client.execute(
        """
        SELECT chat_id, country, cities, professions, job_types, experience, enabled
        FROM user_jobs WHERE enabled = 1
        """,
    )
    return [_row_to_profile(r) for r in rows]

def has_sent_vacancy(client: TursoClient, chat_id: str, vacancy_id: str) -> bool:
    """Чи надсилали вже цю вакансію цьому користувачу?"""
    rows = client.execute(
        "SELECT 1 FROM user_seen_vacancies WHERE chat_id = ? AND vacancy_id = ? LIMIT 1",
        [chat_id, vacancy_id],
    )
    return bool(rows)


def mark_sent(client: TursoClient, chat_id: str, vacancy_id: str) -> None:
    """Позначити, що цю вакансію надіслано користувачу."""
    client.execute_non_query(
        "INSERT OR IGNORE INTO user_seen_vacancies (chat_id, vacancy_id) VALUES (?, ?)",
        [chat_id, vacancy_id],
    )


def list_recent_vacancies(
    client: TursoClient,
    country: str,
    city_slugs: list[str],
    since_hours: int = 24,
    limit: int = 200,
) -> list[dict]:
    """Отримати свіжі вакансії (за останні N годин)."""
    where = ["country = ?"]
    params: list[Any] = [country]

    if city_slugs:
        placeholders = ",".join("?" * len(city_slugs))
        where.append(f"city_slug IN ({placeholders})")
        params.extend(city_slugs)

    where.append("saved_at >= datetime('now', ?)")
    params.append(f"-{since_hours} hours")
    params.append(limit)

    sql = f"""
        SELECT id, source_key, country, city_slug, title, company,
               salary, job_type, experience, link, created_at, saved_at
        FROM vacancies
        WHERE {' AND '.join(where)}
        ORDER BY saved_at DESC
        LIMIT ?
    """
    rows = client.execute(sql, params)

    result: list[dict] = []
    for r in rows:
        result.append({
            "id": r[0],
            "source_key": r[1],
            "country": r[2],
            "city_slug": r[3],
            "title": r[4],
            "company": r[5],
            "salary": r[6],
            "job_type": r[7],
            "experience": r[8],
            "link": r[9],
            "created_at": r[10],
            "saved_at": r[11],       # ← ОСЬ ЦЕЙ РЯДОК
        })
    return result


def list_vacancies_since(
    client: TursoClient,
    country: str,
    city_slug: str,
    since_ts: str,
    limit: int = 500,
) -> list[dict]:
    """Свіжі вакансії з моменту since_ts для конкретного міста.

    Використовується для "нових" вакансій по підписці
    (saved_at > last_parsed_at).

    Args:
        since_ts: ISO timestamp ("2026-10-17 12:00:00").

    Returns:
        Список dict-ів у тому ж форматі, що list_recent_vacancies.
    """
    sql = """
        SELECT id, source_key, country, city_slug, title, company,
               salary, job_type, experience, link, created_at, saved_at
        FROM vacancies
        WHERE country = ? AND city_slug = ?
          AND saved_at > ?
        ORDER BY saved_at DESC
        LIMIT ?
    """
    rows = client.execute(sql, [country, city_slug, since_ts, limit])

    return [
        {
            "id": r[0],
            "source_key": r[1],
            "country": r[2],
            "city_slug": r[3],
            "title": r[4],
            "company": r[5],
            "salary": r[6],
            "job_type": r[7],
            "experience": r[8],
            "link": r[9],
            "created_at": r[10],
            "saved_at": r[11],
        }
        for r in rows
    ]

# ───────────────────────────────────────────────────────
# ПІДПИСКИ (user_subscriptions) — нова модель
# ───────────────────────────────────────────────────────
#
# Один рядок = одна підписка (chat_id, city_slug, profession_key).
# Користувач може мати багато підписок.
#
# profession_key:
#   ""                — «будь-яка професія»
#   "agro_tractor"    — конкретна підкатегорія
#   "custom:водій"    — кастомна (вільний текст)
#
# baseline_done:
#   0 — перший парсинг ще не робили → покажемо топ-5 з джерела
#   1 — baseline зроблено → показуємо тільки нові (saved_at > last_parsed_at)
# ───────────────────────────────────────────────────────


@dataclass
class Subscription:
    """Одна підписка користувача на (місто, професія)."""

    id: int
    chat_id: str
    country: str
    city_slug: str
    profession_key: str              # "" = будь-яка
    job_types: list[str]
    experience: str
    enabled: bool
    baseline_done: bool
    last_parsed_at: str | None
    created_at: str | None


def _row_to_subscription(row: list[Any]) -> Subscription:
    (sub_id, chat_id, country, city_slug, profession_key,
     job_types, experience, enabled, baseline_done,
     last_parsed_at, created_at) = row
    return Subscription(
        id=int(sub_id),
        chat_id=str(chat_id),
        country=str(country),
        city_slug=str(city_slug),
        profession_key=str(profession_key or ""),
        job_types=json.loads(job_types) if job_types else [],
        experience=str(experience or "all"),
        enabled=bool(int(enabled or 0)),
        baseline_done=bool(int(baseline_done or 0)),
        last_parsed_at=str(last_parsed_at) if last_parsed_at else None,
        created_at=str(created_at) if created_at else None,
    )


_SUB_COLUMNS = (
    "id, chat_id, country, city_slug, profession_key, "
    "job_types, experience, enabled, baseline_done, "
    "last_parsed_at, created_at"
)


def add_subscription(
    client: TursoClient,
    chat_id: str,
    country: str,
    city_slug: str,
    profession_key: str = "",
    job_types: list[str] | None = None,
    experience: str = "all",
) -> Subscription | None:
    """Додати підписку. Якщо така вже є — повертає існуючу.

    UNIQUE (chat_id, city_slug, profession_key) гарантує відсутність дублів.

    Returns:
        Subscription (новостворена або існуюча), або None при помилці.
    """
    try:
        client.execute_non_query(
            """
            INSERT OR IGNORE INTO user_subscriptions
                (chat_id, country, city_slug, profession_key,
                 job_types, experience, enabled, baseline_done)
            VALUES (?, ?, ?, ?, ?, ?, 1, 0)
            """,
            [
                chat_id,
                country,
                city_slug,
                profession_key or "",
                json.dumps(job_types or []),
                experience or "all",
            ],
        )
    except Exception as e:
        log.warning("add_subscription: %s", e)
        return None

    # Читаємо назад (нову або існуючу)
    rows = client.execute(
        f"""
        SELECT {_SUB_COLUMNS}
        FROM user_subscriptions
        WHERE chat_id = ? AND city_slug = ? AND profession_key = ?
        LIMIT 1
        """,
        [chat_id, city_slug, profession_key or ""],
    )
    return _row_to_subscription(rows[0]) if rows else None


def list_subscriptions(
    client: TursoClient,
    chat_id: str,
    only_enabled: bool = True,
) -> list[Subscription]:
    """Всі підписки користувача (за замовчуванням — тільки активні)."""
    where = "chat_id = ?"
    params: list[Any] = [chat_id]
    if only_enabled:
        where += " AND enabled = 1"

    rows = client.execute(
        f"""
        SELECT {_SUB_COLUMNS}
        FROM user_subscriptions
        WHERE {where}
        ORDER BY city_slug, profession_key
        """,
        params,
    )
    return [_row_to_subscription(r) for r in rows]


def list_active_subscriptions(client: TursoClient) -> list[Subscription]:
    """Всі увімкнені підписки (для циклу парсингу)."""
    rows = client.execute(
        f"""
        SELECT {_SUB_COLUMNS}
        FROM user_subscriptions
        WHERE enabled = 1
        ORDER BY country, city_slug, profession_key
        """,
    )
    return [_row_to_subscription(r) for r in rows]


def get_subscription(
    client: TursoClient,
    sub_id: int,
) -> Subscription | None:
    """Отримати одну підписку за id."""
    rows = client.execute(
        f"SELECT {_SUB_COLUMNS} FROM user_subscriptions WHERE id = ? LIMIT 1",
        [sub_id],
    )
    return _row_to_subscription(rows[0]) if rows else None


def mark_baseline_done(
    client: TursoClient,
    sub_id: int,
    last_parsed_at: str | None = None,
) -> None:
    """Позначити, що baseline зроблено, і оновити last_parsed_at.

    Args:
        last_parsed_at: ISO-рядок UTC. Якщо None — використати CURRENT_TIMESTAMP.
    """
    if last_parsed_at is None:
        client.execute_non_query(
            """
            UPDATE user_subscriptions
            SET baseline_done = 1, last_parsed_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            [sub_id],
        )
    else:
        client.execute_non_query(
            """
            UPDATE user_subscriptions
            SET baseline_done = 1, last_parsed_at = ?
            WHERE id = ?
            """,
            [last_parsed_at, sub_id],
        )


def update_last_parsed_at(
    client: TursoClient,
    sub_id: int,
    ts: str | None = None,
) -> None:
    """Оновити тільки last_parsed_at."""
    if ts is None:
        client.execute_non_query(
            "UPDATE user_subscriptions SET last_parsed_at = CURRENT_TIMESTAMP WHERE id = ?",
            [sub_id],
        )
    else:
        client.execute_non_query(
            "UPDATE user_subscriptions SET last_parsed_at = ? WHERE id = ?",
            [ts, sub_id],
        )


def set_subscription_enabled(
    client: TursoClient,
    sub_id: int,
    enabled: bool,
) -> None:
    """Увімкнути/вимкнути підписку."""
    client.execute_non_query(
        "UPDATE user_subscriptions SET enabled = ? WHERE id = ?",
        [1 if enabled else 0, sub_id],
    )


def remove_subscription(
    client: TursoClient,
    chat_id: str,
    sub_id: int,
) -> bool:
    """Видалити підписку користувача.

    Повертає True, якщо щось видалили.
    """
    try:
        result = client.execute_non_query(
            "DELETE FROM user_subscriptions WHERE id = ? AND chat_id = ?",
            [sub_id, chat_id],
        )
        return result > 0
    except Exception as e:
        log.warning("remove_subscription: %s", e)
        return False


def count_subscriptions(
    client: TursoClient,
    chat_id: str,
) -> int:
    """Скільки активних підписок у користувача (для лімітів)."""
    rows = client.execute(
        "SELECT COUNT(*) FROM user_subscriptions WHERE chat_id = ? AND enabled = 1",
        [chat_id],
    )
    return int(rows[0][0]) if rows else 0


def set_all_subscriptions_enabled(
    client: TursoClient,
    chat_id: str,
    enabled: bool,
) -> int:
    """Увімкнути/вимкнути ВСІ підписки користувача.

    Returns:
        Кількість змінених рядків (0, якщо не було підписок).
    """
    try:
        return client.execute_non_query(
            "UPDATE user_subscriptions SET enabled = ? WHERE chat_id = ?",
            [1 if enabled else 0, chat_id],
        )
    except Exception as e:
        log.warning("set_all_subscriptions_enabled: %s", e)
        return 0


def any_subscription_enabled(
    client: TursoClient,
    chat_id: str,
) -> bool:
    """Чи є хоч одна активна підписка у користувача?"""
    rows = client.execute(
        "SELECT 1 FROM user_subscriptions WHERE chat_id = ? AND enabled = 1 LIMIT 1",
        [chat_id],
    )
    return bool(rows)

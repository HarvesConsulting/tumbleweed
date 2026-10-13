"""CRUD-запити для TumbleWeed."""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from tumbleweed.parsers.base_job import Vacancy

from .client import TursoClient


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
    """Зберігає вакансію + позначає як побачену. True, якщо вона нова."""
    if is_seen(client, v.source_key, v.raw_id):
        return False
    save_vacancy(client, v)
    mark_seen(client, v)
    return True


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
        enabled=bool(enabled),
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
               salary, job_type, experience, link, created_at
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
        })
    return result

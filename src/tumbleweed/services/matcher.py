"""Матчер: знаходить вакансії, що відповідають профілю користувача."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from tumbleweed.config import DATA_DIR
from tumbleweed.db.client import TursoClient
from tumbleweed.db.queries_jobs import (
    UserJobProfile,
    has_sent_vacancy,
    list_recent_vacancies,
)

log = logging.getLogger(__name__)


# ───────────────────────────────────────────────────────
# Завантаження keywords з professions_ua.json
# ───────────────────────────────────────────────────────

@lru_cache(maxsize=1)
def _load_professions() -> dict[str, list[str]]:
    """Повертає мапу: profession_key → список keywords (у нижньому регістрі)."""
    path = DATA_DIR / "jobs" / "professions_ua.json"
    if not path.exists():
        log.warning("Не знайдено %s — матчинг за професіями вимкнено", path)
        return {}

    raw = json.loads(path.read_text(encoding="utf-8"))
    result: dict[str, list[str]] = {}
    for cat in raw.get("categories", []):
        key = cat.get("key")
        keywords = [k.lower() for k in cat.get("keywords", [])]
        if key:
            result[key] = keywords
    log.info("Завантажено %d категорій професій", len(result))
    return result


# ───────────────────────────────────────────────────────
# Фільтри
# ───────────────────────────────────────────────────────

def _title_matches_professions(title: str, professions: list[str]) -> bool:
    """Чи містить title якесь із keywords обраних категорій?"""
    if not professions:
        return True   # без фільтра — усі підходять

    keywords_map = _load_professions()
    title_lower = title.lower()

    for prof in professions:
        # Кастомна професія — користувач ввів текстом
        if prof.startswith("custom:"):
            custom = prof[len("custom:"):].strip().lower()
            if custom and custom in title_lower:
                return True
            continue

        # Категорія з professions_ua.json
        for kw in keywords_map.get(prof, []):
            if kw in title_lower:
                return True

    return False


def _job_type_matches(vacancy_job_type: str | None, wanted: list[str]) -> bool:
    """Чи відповідає тип зайнятості вакансії бажаному?"""
    if not wanted:
        return True   # без фільтра
    if not vacancy_job_type:
        return True   # OLX часто не вказує job_type; не блокуємо
    vjt = vacancy_job_type.lower()
    for w in wanted:
        wl = w.lower()
        # "full" має збігатись із "pełny etat", "full-time", "повна"
        if wl == "full" and ("pełny" in vjt or "full" in vjt or "повна" in vjt):
            return True
        if wl == "part" and ("część" in vjt or "part" in vjt or "часткова" in vjt):
            return True
        if wl == "remote" and ("zdal" in vjt or "remote" in vjt or "віддал" in vjt):
            return True
        if wl in vjt:
            return True
    return False


# ───────────────────────────────────────────────────────
# Головна функція
# ───────────────────────────────────────────────────────

@dataclass
class MatchResult:
    profile: UserJobProfile
    vacancies: list[dict]


def find_vacancies_for_profile(
    client: TursoClient,
    profile: UserJobProfile,
    since_hours: int = 24,
    max_per_user: int = 5,
) -> list[dict]:
    """Знайти свіжі вакансії, що підходять під профіль (без надісланих раніше)."""
    candidates = list_recent_vacancies(
        client,
        country=profile.country,
        city_slugs=profile.cities,
        since_hours=since_hours,
        limit=500,
    )

    matched: list[dict] = []
    for v in candidates:
        # 1. Фільтр за професією
        if not _title_matches_professions(v["title"], profile.professions):
            continue

        # 2. Фільтр за типом зайнятості
        if not _job_type_matches(v.get("job_type"), profile.job_types):
            continue

        # 3. Чи не надсилали вже?
        try:
            if has_sent_vacancy(client, profile.chat_id, v["id"]):
                continue
        except Exception as e:
            log.warning("Помилка перевірки has_sent_vacancy: %s", e)
            continue

        matched.append(v)
        if len(matched) >= max_per_user:
            break

    return matched


def find_matches_for_all(
    client: TursoClient,
    profiles: list[UserJobProfile],
    since_hours: int = 24,
) -> list[MatchResult]:
    """Пройтись по всіх активних профілях і знайти для кожного вакансії."""
    results: list[MatchResult] = []
    for p in profiles:
        try:
            v = find_vacancies_for_profile(client, p, since_hours=since_hours)
        except Exception as e:
            log.exception("Помилка матчингу для %s: %s", p.chat_id, e)
            continue
        if v:
            results.append(MatchResult(profile=p, vacancies=v))
    return results
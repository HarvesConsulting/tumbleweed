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
# Мапа підкатегорій: "agro_tractor" → ["тракторист", "трактор", "tractor"]
# ───────────────────────────────────────────────────────

@lru_cache(maxsize=3)
def _load_subcategories(country: str = "ua") -> dict[str, list[str]]:
    """Повертає мапу: sub_key → [keywords] для країни."""
    path = DATA_DIR / "jobs" / f"professions_{country}.json"
    if not path.exists():
        log.warning("Не знайдено %s", path)
        return {}

    raw = json.loads(path.read_text(encoding="utf-8"))
    result: dict[str, list[str]] = {}
    for cat in raw.get("categories", []):
        for sub in cat.get("subcategories", []):
            key = sub.get("key")
            if key:
                result[key] = [k.lower() for k in sub.get("keywords", [])]
    log.info("Завантажено %d підкатегорій для %s", len(result), country)
    return result


# ───────────────────────────────────────────────────────
# Фільтри
# ───────────────────────────────────────────────────────

def _title_matches_professions(
    title: str,
    professions: list[str],
    country: str = "ua",
) -> bool:
    """Чи містить title keywords обраних підкатегорій?

    professions містить ключі типу "agro_tractor" або "custom:водій".
    country — для вибору professions_{country}.json.
    """
    if not professions:
        return True   # без фільтра — усі підходять

    subs_map = _load_subcategories(country)
    title_lower = title.lower()

    for prof in professions:
        # Кастомна професія
        if prof.startswith("custom:"):
            custom = prof[len("custom:"):].strip().lower()
            if custom and custom in title_lower:
                return True
            continue

        # Підкатегорія з professions_{country}.json
        for kw in subs_map.get(prof, []):
            if kw in title_lower:
                return True

    return False


def _job_type_matches(vacancy_job_type: str | None, wanted: list[str]) -> bool:
    """Чи відповідає тип зайнятості вакансії бажаному?"""
    if not wanted:
        return True
    if not vacancy_job_type:
        return True   # OLX часто не вказує — не блокуємо
    vjt = vacancy_job_type.lower()
    for w in wanted:
        wl = w.lower()
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
    max_per_source: int = 5,          # ← перейменовано: ліміт на джерело
) -> list[dict]:
    """Знайти свіжі вакансії під профіль (по 5 з кожного джерела)."""
    from collections import defaultdict

    candidates = list_recent_vacancies(
        client,
        country=profile.country,
        city_slugs=profile.cities,
        since_hours=since_hours,
        limit=500,
    )

    # Групуємо по source_key
    by_source: dict[str, list[dict]] = defaultdict(list)

    for v in candidates:
        # Фільтри
        if not _title_matches_professions(
            v["title"], profile.professions, profile.country
        ):
            continue
        if not _job_type_matches(v.get("job_type"), profile.job_types):
            continue
        try:
            if has_sent_vacancy(client, profile.chat_id, v["id"]):
                continue
        except Exception as e:
            log.warning("has_sent_vacancy: %s", e)
            continue

        source_key = v.get("source_key") or "unknown"

        # Скіп — якщо вже набрали 5 від цього джерела
        if len(by_source[source_key]) >= max_per_source:
            continue

        by_source[source_key].append(v)

    # Об'єднати усі джерела
    result: list[dict] = []
    for source_key, items in by_source.items():
        result.extend(items)

    return result


def find_matches_for_all(
    client: TursoClient,
    profiles: list[UserJobProfile],
    since_hours: int = 24,
) -> list[MatchResult]:
    """Пройтись по всіх активних профілях."""
    results: list[MatchResult] = []
    for p in profiles:
        try:
            v = find_vacancies_for_profile(client, p, since_hours=since_hours)
        except Exception as e:
            log.exception("Матчинг для %s: %s", p.chat_id, e)
            continue
        if v:
            results.append(MatchResult(profile=p, vacancies=v))
    return results

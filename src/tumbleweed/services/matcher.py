"""Матчер: знаходить вакансії, що відповідають профілю користувача."""
from __future__ import annotations

import json
import logging
from collections import defaultdict
from dataclasses import dataclass
from functools import lru_cache

from tumbleweed.config import DATA_DIR
from tumbleweed.db.client import TursoClient
from tumbleweed.db.queries_jobs import (
    Subscription,
    UserJobProfile,
    has_sent_vacancy,
    list_recent_vacancies,
    list_vacancies_since,
)
from tumbleweed.services.text_utils import has_word, normalize

log = logging.getLogger(__name__)


# ───────────────────────────────────────────────────────
# Підкатегорії: завантажуємо з professions_{country}.json
# ───────────────────────────────────────────────────────

@dataclass(frozen=True)
class Subcategory:
    """Одна підкатегорія з нормалізованими keywords."""
    key: str
    keywords: list[str]       # нормалізовані


@lru_cache(maxsize=3)
def _load_subcategories(country: str = "ua") -> dict[str, Subcategory]:
    """Повертає мапу: sub_key → Subcategory для країни."""
    path = DATA_DIR / "jobs" / f"professions_{country}.json"
    if not path.exists():
        log.warning("Не знайдено %s", path)
        return {}

    raw = json.loads(path.read_text(encoding="utf-8"))
    result: dict[str, Subcategory] = {}
    for cat in raw.get("categories", []):
        for sub in cat.get("subcategories", []):
            key = sub.get("key")
            if not key:
                continue
            # Нормалізуємо keywords на етапі завантаження — щоб не робити це 100 разів
            raw_kws = sub.get("keywords", [])
            kws = [normalize(k) for k in raw_kws if isinstance(k, str) and k.strip()]
            result[key] = Subcategory(key=key, keywords=kws)

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

    if not title or not title.strip():
        return False

    subs_map = _load_subcategories(country)

    for prof in professions:
        # Кастомна професія: "custom:водій"
        if prof.startswith("custom:"):
            custom = prof[len("custom:"):].strip()
            if custom and has_word(title, custom):
                return True
            continue

        # Підкатегорія з professions_{country}.json
        sub = subs_map.get(prof)
        if not sub:
            continue

        for kw in sub.keywords:
            # has_word нормалізує обидві сторони всередині,
            # тому додатково normalize(title) не потрібен
            if has_word(title, kw):
                return True

    return False


def _job_type_matches(vacancy_job_type: str | None, wanted: list[str]) -> bool:
    """Чи відповідає тип зайнятості вакансії бажаному?"""
    if not wanted:
        return True
    if not vacancy_job_type:
        return True   # OLX часто не вказує — не блокуємо
    vjt = normalize(vacancy_job_type)
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
    max_per_source: int = 5,
) -> list[dict]:
    """Знайти свіжі вакансії під профіль (по N з кожного джерела)."""
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
        # 1) Фільтр по професії (title)
        if not _title_matches_professions(
            v["title"], profile.professions, profile.country
        ):
            continue

        # 2) Фільтр по типу зайнятості
        if not _job_type_matches(v.get("job_type"), profile.job_types):
            continue

        # 3) Скіп — якщо вже набрали N від цього джерела
        source_key = v.get("source_key") or "unknown"
        if len(by_source[source_key]) >= max_per_source:
            continue

        # 4) Перевірка "чи вже надсилали" — тільки для тих, кого беремо
        #    (це економить SQL-запити для відфільтрованих вакансій)
        try:
            if has_sent_vacancy(client, profile.chat_id, v["id"]):
                continue
        except Exception as e:
            log.warning("has_sent_vacancy: %s", e)
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


# ───────────────────────────────────────────────────────
# НОВА МОДЕЛЬ: матчинг по підписках (user_subscriptions)
# ───────────────────────────────────────────────────────

def _score_for_profile(
    title: str,
    profession_keys: list[str],
    country: str,
) -> float:
    """Обчислює score матчингу title до однієї з professions.

    Використовується для сортування baseline-вакансій.
    Повертає 0.0, якщо жодна не підходить.
    """
    if not profession_keys:
        return 1.0  # «будь-яка» — усі підходять рівноцінно

    if not title or not title.strip():
        return 0.0

    subs_map = _load_subcategories(country)
    best = 0.0

    for prof in profession_keys:
        if prof.startswith("custom:"):
            custom = prof[len("custom:"):].strip()
            if custom and has_word(title, custom):
                best = max(best, 1.0)
            continue

        sub = subs_map.get(prof)
        if not sub:
            continue
        for kw in sub.keywords:
            if has_word(title, kw):
                # чим коротше keyword, тим вища впевненість
                w = 1.0 if len(kw) >= 5 else 0.7
                best = max(best, w)

    return best


def _baseline_vacancies(
    client: TursoClient,
    sub: Subscription,
    max_per_source: int = 5,
) -> list[dict]:
    """Перший парсинг: топ-N за score з кожного джерела.

    Оскільки baseline_done ще не встановлено, показуємо свіжі вакансії
    за останні 7 днів (або всі, якщо менше).
    """
    candidates = list_recent_vacancies(
        client,
        country=sub.country,
        city_slugs=[sub.city_slug],
        since_hours=24 * 7,           # 7 днів — широке вікно для baseline
        limit=500,
    )

    # Скор + фільтри
    scored: list[tuple[float, dict]] = []
    profession_keys = [sub.profession_key] if sub.profession_key else []

    for v in candidates:
        score = _score_for_profile(v["title"], profession_keys, sub.country)
        if score <= 0:
            continue
        if not _job_type_matches(v.get("job_type"), sub.job_types):
            continue
        scored.append((score, v))

    # Сортування: score DESC, потім created_at DESC
    scored.sort(key=lambda x: (-x[0], x[1].get("created_at") or ""))

    # Групування по джерелах: топ-N за score
    by_source: dict[str, list[dict]] = defaultdict(list)
    for score, v in scored:
        source_key = v.get("source_key") or "unknown"
        if len(by_source[source_key]) >= max_per_source:
            continue
        # Перевірка "чи вже надсилали"
        try:
            if has_sent_vacancy(client, sub.chat_id, v["id"]):
                continue
        except Exception as e:
            log.warning("has_sent_vacancy: %s", e)
            continue
        by_source[source_key].append(v)

    result: list[dict] = []
    for items in by_source.values():
        result.extend(items)

    # Фінальне сортування — щоб топ з різних джерел перемішався за score
    result.sort(key=lambda v: v.get("saved_at") or "", reverse=True)
    return result


def _new_vacancies(
    client: TursoClient,
    sub: Subscription,
) -> list[dict]:
    """Наступні парсинги: усі нові вакансії з моменту last_parsed_at."""
    if not sub.last_parsed_at:
        # не мало б траплятись, але захищаємось
        log.warning("sub %s: baseline_done=1, але last_parsed_at порожній", sub.id)
        return []

    candidates = list_vacancies_since(
        client,
        country=sub.country,
        city_slug=sub.city_slug,
        since_ts=sub.last_parsed_at,
        limit=500,
    )

    profession_keys = [sub.profession_key] if sub.profession_key else []

    new_vacancies: list[dict] = []
    for v in candidates:
        # Матчинг професії
        score = _score_for_profile(v["title"], profession_keys, sub.country)
        if score <= 0:
            continue
        # Матчинг типу зайнятості
        if not _job_type_matches(v.get("job_type"), sub.job_types):
            continue
        # Дедуплікація per-user (щоб не надіслати двічі)
        try:
            if has_sent_vacancy(client, sub.chat_id, v["id"]):
                continue
        except Exception as e:
            log.warning("has_sent_vacancy: %s", e)
            continue

        new_vacancies.append(v)

    # Сортування за часом публікації (новіші першими)
    new_vacancies.sort(key=lambda v: v.get("created_at") or "", reverse=True)
    return new_vacancies


def find_vacancies_for_subscription(
    client: TursoClient,
    sub: Subscription,
    max_per_source: int = 5,
) -> list[dict]:
    """Знайти вакансії для однієї підписки.

    Логіка:
      - baseline_done == 0 → топ-N з кожного джерела (перший показ)
      - baseline_done == 1 → усі нові з last_parsed_at (дедупліковано)

    Args:
        sub: підписка (chat_id, country, city_slug, profession_key).
        max_per_source: ліміт для baseline.

    Returns:
        Список вакансій (dict-ів) — порожній, якщо нічого не підходить.
    """
    if not sub.baseline_done:
        return _baseline_vacancies(client, sub, max_per_source=max_per_source)
    return _new_vacancies(client, sub)


def find_matches_for_all_subscriptions(
    client: TursoClient,
    subscriptions: list[Subscription],
    max_per_source: int = 5,
) -> list[tuple[Subscription, list[dict]]]:
    """Пройтись по всіх підписках — повертає (sub, [vacancies]) парами.

    Args:
        subscriptions: зазвичай результат list_active_subscriptions(client).

    Returns:
        Список (Subscription, list[vacancies]) — тільки для тих,
        у кого є хоч одна вакансія.
    """
    results: list[tuple[Subscription, list[dict]]] = []
    for sub in subscriptions:
        try:
            vacancies = find_vacancies_for_subscription(
                client, sub, max_per_source=max_per_source
            )
        except Exception as e:
            log.exception("Матчинг для підписки %s (chat=%s): %s",
                          sub.id, sub.chat_id, e)
            continue
        if vacancies:
            results.append((sub, vacancies))
    return results

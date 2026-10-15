"""Пошук міст у каталозі data/cities/{country}.json.

Використовується в UX, коли користувач вводить назву міста текстом.
Підтримує fuzzy-пошук по українській, російській та англійській.

ЄДИНЕ ДЖЕРЕЛО ІСТИНИ — data/cities/{country}.json.
Міста з priority: true — вважаються "популярними" і йдуть першими.
"""
from __future__ import annotations

import json
import logging
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from tumbleweed.config import DATA_DIR

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class City:
    slug: str            # "kyiv"
    name: str            # "Київ"
    region: str | None   # "Київська область"
    olx_id: int | None   # city_id у OLX
    workua_id: int | None
    priority: bool = False  # True → показувати у "популярних"


# ───────────────────────────────────────────────────────
# Нормалізація
# ───────────────────────────────────────────────────────

def _normalize(text: str) -> str:
    """Привести до нижнього регістру, прибрати діакритику, зайві пробіли."""
    text = text.lower().strip()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return text


# ───────────────────────────────────────────────────────
# Завантаження каталогу
# ───────────────────────────────────────────────────────

@lru_cache(maxsize=3)
def _load_cities(country: str) -> list[City]:
    """Завантажує data/cities/{country}.json один раз.

    Повертає список City, відсортований:
      1. priority: true — першими (у порядку JSON)
      2. решта — у порядку JSON
    """
    cities: list[City] = []
    seen_slugs: set[str] = set()

    path = DATA_DIR / "cities" / f"{country}.json"
    if not path.exists():
        log.warning("Не знайдено %s", path)
        return []

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        items = raw.get("cities") if isinstance(raw, dict) else raw
        if not isinstance(items, list):
            log.error("Неправильний формат %s", path)
            return []

        priority_cities: list[City] = []
        normal_cities: list[City] = []

        for item in items:
            if not isinstance(item, dict):
                continue

            slug = item.get("slug") or item.get("key") or ""
            name = item.get("name") or item.get("label") or ""

            if not slug or not name:
                continue
            if slug in seen_slugs:
                continue
            seen_slugs.add(slug)

            # olx_id з refs.olx_ua
            refs = item.get("refs") or {}
            olx_id = refs.get("olx_ua") if isinstance(refs, dict) else None

            # workua_id (якщо є у JSON)
            workua_id = item.get("workua_id")

            is_priority = bool(item.get("priority", False))

            city = City(
                slug=slug,
                name=name,
                region=item.get("region") or item.get("state"),
                olx_id=olx_id,
                workua_id=workua_id,
                priority=is_priority,
            )

            if is_priority:
                priority_cities.append(city)
            else:
                normal_cities.append(city)

        # Priority — першими
        cities = priority_cities + normal_cities

    except Exception as e:
        log.error("Помилка читання %s: %s", path, e)
        return []

    log.info(
        "Завантажено %d міст для %s (з них %d priority)",
        len(cities), country, sum(1 for c in cities if c.priority),
    )
    return cities


def _city_cache() -> dict[str, dict[str, City]]:
    """Хелпер: повертає {country: {slug: City}} — не потрібно, бо використовуємо lru_cache."""
    # Використовується рідко — тому окремо не кешуємо
    return {}


def get_city(country: str, slug: str) -> City | None:
    """Знайти місто за slug.

    Шукає у _load_cities(country) — єдине джерело істини.
    """
    if not slug:
        return None

    for c in _load_cities(country):
        if c.slug == slug:
            return c
    return None


# ───────────────────────────────────────────────────────
# Пошук (fuzzy)
# ───────────────────────────────────────────────────────

def search_cities(
    country: str,
    query: str,
    limit: int = 3,
) -> list[City]:
    """Пошук міст за назвою (fuzzy).

    Пріоритет:
      1000 — точний збіг назви
       500 — назва починається з запиту
       300 — якесь слово в назві починається з запиту
       200 — регіон починається з запиту
    """
    q = _normalize(query)
    if len(q) < 2:
        return []

    cities = _load_cities(country)
    scored: list[tuple[City, int]] = []

    for c in cities:
        name_norm = _normalize(c.name)
        region_norm = _normalize(c.region or "")

        score = 0

        if name_norm == q:
            score = 1000
        elif name_norm.startswith(q):
            score = 500
        elif any(word.startswith(q) for word in name_norm.split()):
            score = 300
        elif region_norm and region_norm.startswith(q):
            score = 200
        else:
            continue

        # Бонус за olx_id
        if c.olx_id:
            score += 10
        # Бонус за priority
        if c.priority:
            score += 5

        scored.append((c, score))

    scored.sort(key=lambda x: (-x[1], x[0].name))

    if not scored:
        return []

    top_score = scored[0][1]

    if top_score >= 500:
        same_top = [c for c, s in scored if s == top_score]
        return same_top[:limit]

    return [c for c, _ in scored[:limit]]


def popular_cities(country: str, limit: int = 6) -> list[City]:
    """Повертає ТОП limit міст з priority: true (у порядку JSON)."""
    cities = _load_cities(country)
    priority = [c for c in cities if c.priority]
    return priority[:limit]


# ───────────────────────────────────────────────────────
# Динамічний пошук city_id у OLX (для міст без olx_id)
# ───────────────────────────────────────────────────────

def find_olx_city_id(country: str, city_name: str) -> int | None:
    """Шукає city_id у OLX API за назвою міста.

    Fallback для міст без olx_id у JSON. Довгий запит — викликати рідко.
    """
    domains = {"ua": "olx.ua", "pl": "olx.pl", "ro": "olx.ro"}
    domain = domains.get(country)
    if not domain:
        return None

    try:
        from curl_cffi import requests as cffi_requests

        url = f"https://www.{domain}/api/v1/cities/"
        r = cffi_requests.get(
            url,
            params={"query": city_name, "limit": 5},
            headers={"Accept": "application/json"},
            impersonate="chrome124",
            timeout=15,
        )
        if r.status_code != 200:
            log.warning("OLX cities API: HTTP %d", r.status_code)
            return None

        data = r.json().get("data") or []
        if not data:
            return None

        first = data[0]
        return first.get("id")
    except Exception as e:
        log.warning("Не вдалось знайти city_id: %s", e)
        return None

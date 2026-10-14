"""Завантажує та кешує мапу міст Robota.ua (slug → cityId)."""
from __future__ import annotations

import json
import logging
from pathlib import Path

log = logging.getLogger(__name__)

# Кеш у пам'яті
_CACHE: dict[str, str] | None = None

# Файловий кеш
CACHE_FILE = Path("data/jobs/robota_cities.json")


def _normalize(slug: str) -> str:
    """Нормалізує slug — прибирає різницю між нашим і Robota."""
    return slug.lower().strip().replace("_", "-")


def load_cities(force: bool = False) -> dict[str, str]:
    """Повертає мапу slug → cityId з локального файлу.

    Джерело — data/jobs/robota_cities.json. API більше не викликається,
    бо getCities на dracula.robota.ua стабільно віддає 403.
    """
    global _CACHE
    if _CACHE is not None and not force:
        return _CACHE

    if not CACHE_FILE.exists():
        log.warning("Файл %s не знайдено", CACHE_FILE)
        _CACHE = {}
        return _CACHE

    try:
        data = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        _CACHE = {_normalize(item["slug"]): str(item["id"]) for item in data}
        log.info("Завантажено %d міст Robota.ua з файлу", len(_CACHE))
        return _CACHE
    except Exception as e:
        log.exception("Помилка читання %s: %s", CACHE_FILE, e)
        _CACHE = {}
        return _CACHE


def get_city_id(slug: str) -> str | None:
    """Повертає cityId для нашого slug."""
    cities = load_cities()
    normalized = _normalize(slug)
    return cities.get(normalized)

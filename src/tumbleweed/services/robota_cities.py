"""Завантажує та кешує мапу міст Robota.ua (slug → cityId)."""
from __future__ import annotations

import json
import logging
from pathlib import Path

log = logging.getLogger(__name__)

# Кеш у пам'яті: два словники
_CACHE: dict[str, str] | None = None
_CACHE_BY_NAME: dict[str, str] | None = None

# Файловий кеш
CACHE_FILE = Path("data/jobs/robota_cities.json")


def _normalize(slug: str) -> str:
    """Нормалізує slug — прибирає різницю між нашим і Robota."""
    return slug.lower().strip().replace("_", "-")


def load_cities(force: bool = False) -> dict[str, str]:
    """Мапа slug → cityId з локального файлу."""
    global _CACHE, _CACHE_BY_NAME
    if _CACHE is not None and not force:
        return _CACHE

    if not CACHE_FILE.exists():
        log.warning("Файл %s не знайдено", CACHE_FILE)
        _CACHE = {}
        _CACHE_BY_NAME = {}
        return _CACHE

    try:
        data = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        _CACHE = {_normalize(item["slug"]): str(item["id"]) for item in data}
        _CACHE_BY_NAME = {item["name"].strip(): str(item["id"]) for item in data}
        log.info("Завантажено %d міст Robota.ua з файлу", len(_CACHE))
        return _CACHE
    except Exception as e:
        log.exception("Помилка читання %s: %s", CACHE_FILE, e)
        _CACHE = {}
        _CACHE_BY_NAME = {}
        return _CACHE


def get_city_id(slug: str) -> str | None:
    """Повертає cityId за slug."""
    cities = load_cities()
    return cities.get(_normalize(slug))


def get_city_id_by_name(name: str) -> str | None:
    """Повертає cityId за українською назвою міста."""
    load_cities()  # гарантує, що _CACHE_BY_NAME заповнено
    return (_CACHE_BY_NAME or {}).get(name.strip())

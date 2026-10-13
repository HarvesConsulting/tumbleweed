"""Реєстр парсерів TumbleWeed."""
from __future__ import annotations

from .base_job import JobParser
from .olx_jobs import OLX_COUNTRIES, OlxJobParser


def get_parser(country: str) -> JobParser | None:
    """Повертає парсер для вказаної країни (поки — тільки OLX)."""
    cfg = OLX_COUNTRIES.get(country)
    return OlxJobParser(cfg) if cfg else None


def get_available_countries() -> list[str]:
    """Список країн, для яких є парсер."""
    return list(OLX_COUNTRIES.keys())
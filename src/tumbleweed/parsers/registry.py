"""Реєстр парсерів TumbleWeed.

Підтримує кілька парсерів на одну країну (OLX, Work.ua, Robota.ua).
"""
from __future__ import annotations

from .base_job import JobParser
from .olx_jobs import OLX_COUNTRIES, OlxJobParser
from .robota_ua import RobotaUaParser
from .workua import WorkUaParser


def get_parsers(country: str) -> list[JobParser]:
    """Повертає список усіх парсерів для країни."""
    parsers: list[JobParser] = []

    # OLX — для всіх країн
    cfg = OLX_COUNTRIES.get(country)
    if cfg:
        parsers.append(OlxJobParser(cfg))

    # Work.ua — тільки UA (на паузі)
    if country == "ua":
        parsers.append(WorkUaParser())

    # Robota.ua — тільки UA
    if country == "ua":
        parsers.append(RobotaUaParser())

    return parsers


def get_parser(country: str) -> JobParser | None:
    """Застаріле — повертає перший парсер для країни."""
    parsers = get_parsers(country)
    return parsers[0] if parsers else None


def get_available_countries() -> list[str]:
    return list(OLX_COUNTRIES.keys())

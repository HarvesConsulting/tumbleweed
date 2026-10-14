"""Реєстр парсерів TumbleWeed.

Підтримує кілька парсерів на одну країну: OLX, Work.ua, Robota.ua, Pidbir.ua.
"""
from __future__ import annotations

from .base_job import JobParser
from .olx_jobs import OLX_COUNTRIES, OlxJobParser
from .pidbir_ua import PidbirUaParser
from .robota_ua import RobotaUaParser
from .workua import WorkUaParser


def get_parsers(country: str) -> list[JobParser]:
    """Повертає список усіх парсерів для країни.

    Args:
        country: ISO код країни ("ua", "pl", "ro").

    Returns:
        Список парсерів. Для "ua" — OLX, Work.ua, Robota.ua, Pidbir.ua.
        Для інших — тільки OLX (якщо налаштований).
    """
    parsers: list[JobParser] = []

    # OLX — для всіх країн, де налаштовано
    cfg = OLX_COUNTRIES.get(country)
    if cfg:
        parsers.append(OlxJobParser(cfg))

    # Українські джерела
    if country == "ua":
        parsers.append(WorkUaParser())
        parsers.append(RobotaUaParser())
        parsers.append(PidbirUaParser())

    return parsers


def get_available_countries() -> list[str]:
    """Повертає список країн, для яких є налаштовані парсери."""
    return list(OLX_COUNTRIES.keys())

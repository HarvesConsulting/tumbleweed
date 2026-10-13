"""Базові абстракції для парсерів вакансій TumbleWeed."""
from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Vacancy:
    """Універсальна вакансія — те, що повертає будь-який парсер."""

    id: str                       # md5(source_key + raw_id) — PK у БД
    raw_id: str                   # оригінальний ID з джерела
    source_key: str               # "olx_ua", "olx_pl", ...
    country: str                  # ISO: "ua", "pl", "ro"
    city_slug: str                # slug зі спільного каталогу (data/cities/*.json)
    title: str
    link: str
    company: str | None = None
    salary: str | None = None
    job_type: str | None = None
    experience: str | None = None
    description: str | None = None
    photo: str | None = None
    created_at: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @staticmethod
    def make_id(source_key: str, raw_id: str) -> str:
        """Детермінований ID — одна вакансія = один id у БД."""
        return hashlib.md5(f"{source_key}:{raw_id}".encode()).hexdigest()


class JobParser(ABC):
    """Базовий клас для всіх парсерів вакансій."""

    source_key: str          # напр. "olx_ua"
    country: str             # ISO код: ua, pl, ro
    display_name: str        # для логів

    @abstractmethod
    async def fetch(
        self,
        city_slug: str | None = None,
        query: str = "",
        limit: int = 40,
    ) -> list[Vacancy]:
        """Повертає список вакансій.

        Args:
            city_slug: slug міста (None → вся країна)
            query: ключове слово (професія)
            limit: максимум вакансій
        """
        ...
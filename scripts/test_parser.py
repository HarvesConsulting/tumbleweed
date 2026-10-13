"""Швидкий тест парсера OLX: UA, PL, RO (без БД)."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tumbleweed.parsers.registry import get_parser


async def main() -> None:
    cases = [
        ("ua", "kyiv", "Python"),
        ("pl", "warszawa", "programista"),
        ("ro", "bucuresti", ""),
    ]
    for country, city, query in cases:
        parser = get_parser(country)
        if parser is None:
            print(f"❌ Немає парсера для {country}")
            continue

        print(f"\n{'=' * 70}")
        print(f"[{country}] city={city!r} query={query!r}")
        print(f"{'=' * 70}")

        vacancies = await parser.fetch(city_slug=city, query=query, limit=6)
        print(f"  Знайдено: {len(vacancies)}")
        for v in vacancies[:3]:
            print(f"  • {v.title[:60]}")
            print(f"    company: {v.company!r}")
            print(f"    salary:  {v.salary!r}")
            print(f"    link:    {v.link[:70]}")
            print(f"    id:      {v.id}")


if __name__ == "__main__":
    asyncio.run(main())

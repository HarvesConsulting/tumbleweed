"""Один цикл агрегації вакансій: парсинг → збереження в Turso."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tumbleweed.config import settings
from tumbleweed.db.client import TursoClient
from tumbleweed.db.queries_jobs import save_and_mark
from tumbleweed.parsers.registry import get_parser


# (country, city_slug, query) — перша хвиля
JOBS = [
    ("ua", "kyiv", "Python"),
    ("ua", "kyiv", ""),           # всі категорії
    ("pl", "warszawa", "programista"),
    ("pl", "warszawa", ""),
    ("ro", "bucuresti", ""),
]


async def run_one(
    country: str,
    city: str,
    query: str,
    client: TursoClient,
) -> tuple[int, int]:
    parser = get_parser(country)
    if parser is None:
        print(f"⚠️  Немає парсера: {country}")
        return (0, 0)

    print(f"\n→ [{country}/{city}] query={query!r}")
    try:
        vacancies = await parser.fetch(city_slug=city, query=query, limit=40)
    except Exception as e:
        print(f"  ❌ Помилка парсингу: {type(e).__name__}: {e}")
        return (0, 0)

    new_count = 0
    for v in vacancies:
        try:
            if save_and_mark(client, v):
                new_count += 1
        except Exception as e:
            print(f"  ❌ Помилка збереження {v.raw_id}: {type(e).__name__}: {e}")

    print(f"  Знайдено: {len(vacancies)}, нових: {new_count}")
    return (len(vacancies), new_count)


async def main() -> None:
    client = TursoClient(settings.turso_url, settings.turso_token)
    total_found = 0
    total_new = 0
    for country, city, query in JOBS:
        found, new = await run_one(country, city, query, client)
        total_found += found
        total_new += new

    print(f"\n{'=' * 60}")
    print(f"✅ Знайдено всього: {total_found}")
    print(f"✅ Нових збережено: {total_new}")

    # Перевірка — скільки всього в БД
    rows = client.execute("SELECT COUNT(*) FROM vacancies")
    print(f"✅ Всього у БД vacancies: {rows[0][0]}")
    rows = client.execute("SELECT COUNT(*) FROM seen_vacancies")
    print(f"✅ Всього у БД seen_vacancies: {rows[0][0]}")


if __name__ == "__main__":
    asyncio.run(main())

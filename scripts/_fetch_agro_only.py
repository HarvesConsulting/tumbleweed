"""Швидкий точковий парсинг ТІЛЬКИ для agro у Києві."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tumbleweed.config import settings
from tumbleweed.db.client import TursoClient
from tumbleweed.db.queries_jobs import save_and_mark
from tumbleweed.parsers.registry import get_parser


# Ключові слова з agro-підкатегорій (беремо найважливіші)
AGRO_QUERIES = [
    "агроном",
    "тракторист",
    "комбайнер",
    "фермер",
    "садівник",
    "городник",
    "пасічник",
    "тваринник",
    "виноградар",
    "механізатор",
]


async def run_one(city: str, query: str, client: TursoClient) -> tuple[int, int]:
    parser = get_parser("ua")
    if parser is None:
        return (0, 0)

    print(f"→ [ua/{city}] query={query!r}")
    try:
        vacancies = await parser.fetch(city_slug=city, query=query, limit=40)
    except Exception as e:
        print(f"  ❌ {type(e).__name__}: {e}")
        return (0, 0)

    new_count = 0
    for v in vacancies:
        try:
            if save_and_mark(client, v):
                new_count += 1
        except Exception as e:
            print(f"  ❌ збереження: {e}")

    print(f"  Знайдено: {len(vacancies)}, нових: {new_count}")
    return (len(vacancies), new_count)


async def main() -> None:
    client = TursoClient(settings.turso_url, settings.turso_token)

    # Тільки Київ — швидко
    cities = ["kyiv"]
    total_found = 0
    total_new = 0

    for city in cities:
        for query in AGRO_QUERIES:
            found, new = await run_one(city, query, client)
            total_found += found
            total_new += new

    print(f"\n{'=' * 60}")
    print(f"✅ Знайдено всього: {total_found}")
    print(f"✅ Нових збережено: {total_new}")

    # Перевірка
    rows = client.execute(
        "SELECT COUNT(*) FROM vacancies WHERE "
        "LOWER(title) LIKE '%агроном%' OR "
        "LOWER(title) LIKE '%тракторист%' OR "
        "LOWER(title) LIKE '%комбайн%' OR "
        "LOWER(title) LIKE '%фермер%' OR "
        "LOWER(title) LIKE '%садівник%'"
    )
    print(f"\n🌾 Агро-вакансій у БД: {rows[0][0]}")


if __name__ == "__main__":
    asyncio.run(main())

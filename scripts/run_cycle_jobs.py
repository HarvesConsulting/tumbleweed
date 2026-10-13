"""Один цикл агрегації вакансій: парсинг → збереження в Turso.

Запити генеруються автоматично з data/jobs/professions_ua.json:
беремо найпопулярніші keywords з кожної сфери.
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tumbleweed.config import DATA_DIR, settings
from tumbleweed.db.client import TursoClient
from tumbleweed.db.queries_jobs import save_and_mark
from tumbleweed.parsers.registry import get_parser


# ───────────────────────────────────────────────────────
# Генерація запитів з professions_ua.json
# ───────────────────────────────────────────────────────

def build_ua_queries(max_per_category: int = 3) -> list[str]:
    """Повертає список ключових слів для пошуку в UA.

    Для кожної сфери беремо перші max_per_category підкатегорій
    і від кожного — перше (найважливіше) ключове слово.
    """
    path = DATA_DIR / "jobs" / "professions_ua.json"
    raw = json.loads(path.read_text(encoding="utf-8"))

    queries: list[str] = []
    for cat in raw.get("categories", []):
        subs = cat.get("subcategories", [])[:max_per_category]
        for sub in subs:
            keywords = sub.get("keywords", [])
            if not keywords:
                continue
            # Перше keyword — найважливіше
            queries.append(keywords[0])
    return queries


# ───────────────────────────────────────────────────────
# Специфічні запити для PL та RO (польська/румунська)
# ───────────────────────────────────────────────────────

PL_QUERIES = [
    "programista", "developer", "kierowca", "kurier",
    "budowlaniec", "spawacz", "kucharz", "kelner",
    "sprzedawca", "magazynier", "opiekun", "nauczyciel",
    "elektryk", "hydraulik", "sprzątaczka", "rolnik",
]

RO_QUERIES = [
    "programator", "developer", "șofer", "curier",
    "constructor", "sudor", "bucătar", "ospătar",
    "vânzător", "depozit", "profesor", "electrician",
    "agricultor", "curățenie",
]


def build_jobs() -> list[tuple[str, str, str]]:
    """Повертає список (country, city_slug, query)."""
    jobs: list[tuple[str, str, str]] = []

    # UA — по всіх містах
    ua_cities = ["kyiv", "lviv", "odesa", "kharkiv", "dnipro"]
    ua_queries = build_ua_queries(max_per_category=2)  # 10 сфер × 2 = 20 запитів
    for city in ua_cities:
        for q in ua_queries:
            jobs.append(("ua", city, q))

    # PL — Варшава, Краків (найпопулярніші)
    pl_cities = ["warszawa", "krakow"]
    for city in pl_cities:
        for q in PL_QUERIES[:10]:      # 10 запитів
            jobs.append(("pl", city, q))

    # RO — Бухарест
    for q in RO_QUERIES[:10]:
        jobs.append(("ro", "bucuresti", q))

    return jobs


# ───────────────────────────────────────────────────────
# Основна логіка
# ───────────────────────────────────────────────────────

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
            print(f"  ❌ Збереження {v.raw_id}: {e}")

    print(f"  Знайдено: {len(vacancies)}, нових: {new_count}")
    return (len(vacancies), new_count)


async def main() -> None:
    client = TursoClient(settings.turso_url, settings.turso_token)
    jobs = build_jobs()
    print(f"📊 Загальна кількість запитів: {len(jobs)}")

    total_found = 0
    total_new = 0
    for country, city, query in jobs:
        found, new = await run_one(country, city, query, client)
        total_found += found
        total_new += new

    print(f"\n{'=' * 60}")
    print(f"✅ Знайдено всього: {total_found}")
    print(f"✅ Нових збережено: {total_new}")

    rows = client.execute("SELECT COUNT(*) FROM vacancies")
    print(f"✅ Всього у БД vacancies: {rows[0][0]}")


if __name__ == "__main__":
    asyncio.run(main())

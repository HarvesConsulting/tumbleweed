"""Один цикл агрегації вакансій: парсинг → збереження в Turso.

НОВИЙ ПІДХІД: парсимо ТІЛЬКИ те, що шукають активні користувачі.
Запити формуються динамічно з user_jobs.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tumbleweed.config import settings
from tumbleweed.db.client import TursoClient
from tumbleweed.db.queries_jobs import list_active_profiles, save_and_mark
from tumbleweed.parsers.registry import get_parsers
from tumbleweed.services.subcategory_search import get_subcategory


# ───────────────────────────────────────────────────────
# «Холодний старт» — що парсити, навіть якщо немає підписок
# ───────────────────────────────────────────────────────

COLD_START = [
    ("ua", "kyiv", "backend"),
    ("ua", "kyiv", "продавець"),
    ("ua", "kyiv", "водій"),
]


# ───────────────────────────────────────────────────────
# Динамічна генерація запитів з профілів користувачів
# ───────────────────────────────────────────────────────

def build_jobs_from_users(client: TursoClient) -> list[tuple[str, str, str]]:
    """Формує запити ТІЛЬКИ з активних профілів користувачів.

    Читає user_jobs, для кожної підкатегорії бере перше keyword,
    формує (country, city, query) для кожного міста.

    Returns:
        Список унікальних (country, city_slug, query).
    """
    profiles = list_active_profiles(client)
    seen: set[tuple[str, str, str]] = set()
    jobs: list[tuple[str, str, str]] = []

    for p in profiles:
        # Профіль без professions — підписка на всю країну/місто.
        # Ставимо загальний запит — але нам потрібне хоч якесь слово.
        # У цьому випадку — пропускаємо, бо OLX без query = забагато запитів.
        if not p.professions:
            continue

        cities = p.cities or [""]      # порожнє = вся країна

        for sub_key in p.professions:
            # sub_key може бути "agro_tractor" або "custom:водій"
            if sub_key.startswith("custom:"):
                query = sub_key[len("custom:"):].strip()
                if not query:
                    continue
            else:
                cat_key, _, _ = sub_key.partition("_")
                sub = get_subcategory(cat_key, sub_key)
                if not sub or not sub.keywords:
                    continue
                # Перше keyword — найважливіше
                query = sub.keywords[0]

            for city in cities:
                job = (p.country, city, query)
                if job not in seen:
                    seen.add(job)
                    jobs.append(job)

    return jobs


def build_jobs(client: TursoClient) -> list[tuple[str, str, str]]:
    """Об'єднує запити з профілів + холодний старт."""
    from_users = build_jobs_from_users(client)

    # Додаємо cold-start запити (щоб нові користувачі одразу бачили результат)
    combined: set[tuple[str, str, str]] = set(from_users)
    for j in COLD_START:
        combined.add(j)

    return list(combined)


# ───────────────────────────────────────────────────────
# Основна логіка
# ───────────────────────────────────────────────────────

async def run_one(
    country: str,
    city: str,
    query: str,
    client: TursoClient,
) -> tuple[int, int]:
    """Запускає ВСІ парсери для країни та об'єднує результати."""
    parsers = get_parsers(country)
    if not parsers:
        print(f"⚠️  Немає парсерів для {country}")
        return (0, 0)

    total_found = 0
    total_new = 0

    for parser in parsers:
        print(f"\n→ [{parser.display_name} | {city or 'вся країна'}] query={query!r}", flush=True)
        try:
            vacancies = await parser.fetch(
                city_slug=city or None,
                query=query,
                limit=40,
            )
        except Exception as e:
            print(f"  ❌ Помилка: {type(e).__name__}: {e}", flush=True)
            continue

        new_count = 0
        for v in vacancies:
            try:
                if save_and_mark(client, v):
                    new_count += 1
            except Exception as e:
                print(f"  ❌ Збереження: {e}", flush=True)

        print(f"  Знайдено: {len(vacancies)}, нових: {new_count}", flush=True)
        total_found += len(vacancies)
        total_new += new_count

    return (total_found, total_new)


async def main() -> None:
    client = TursoClient(settings.turso_url, settings.turso_token)

    print("=" * 60, flush=True)
    print("СТАРТ ЦИКЛУ АГРЕГАЦІЇ", flush=True)
    print("=" * 60, flush=True)

    # 1. Скільки активних профілів
    profiles = list_active_profiles(client)
    print(f"\n📊 Активних профілів: {len(profiles)}", flush=True)

    # 2. Скільки запитів треба зробити
    jobs = build_jobs(client)
    print(f"📊 Унікальних запитів: {len(jobs)}", flush=True)

    if not jobs:
        print("ℹ️  Немає активних підписок і холодного старту — виходимо.", flush=True)
        return

    # 3. Показуємо список
    print("\nЗапити:", flush=True)
    for country, city, query in jobs:
        print(f"  → {country}/{city or '—'}: {query}", flush=True)

    # 4. Парсимо
    print(f"\n{'=' * 60}", flush=True)
    total_found = 0
    total_new = 0
    for country, city, query in jobs:
        found, new = await run_one(country, city, query, client)
        total_found += found
        total_new += new

    # 5. Підсумок
    print(f"\n{'=' * 60}", flush=True)
    print(f"✅ Знайдено всього: {total_found}", flush=True)
    print(f"✅ Нових збережено: {total_new}", flush=True)

    rows = client.execute("SELECT COUNT(*) FROM vacancies")
    print(f"✅ Всього у БД vacancies: {rows[0][0]}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())

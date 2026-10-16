"""Один цикл агрегації вакансій: парсинг → збереження в Turso.

НОВИЙ ПІДХІД (v2): парсимо ТІЛЬКИ те, що шукають активні підписки
(user_subscriptions). Запити дедуплікуються — якщо 5 користувачів
підписані на "Київ + Кухар", парсимо ОДИН раз.
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tumbleweed.config import settings
from tumbleweed.db.client import TursoClient
from tumbleweed.db.queries_jobs import (
    list_active_subscriptions,
    save_and_mark,
)
from tumbleweed.parsers.registry import get_parsers
from tumbleweed.services.subcategory_search import get_subcategory


USE_WORKUA = os.getenv("USE_WORKUA", "1") == "1"


# ───────────────────────────────────────────────────────
# Хелпер: profession_key → query для парсера
# ───────────────────────────────────────────────────────

def _query_from_profession_key(profession_key: str, country: str) -> str:
    """Перетворює ключ підписки у пошуковий запит.

    - ""                → "" (будь-яка професія)
    - "custom:водій"    → "водій"
    - "agro_tractor"    → перше keyword з professions_{country}.json
    """
    if not profession_key:
        return ""

    if profession_key.startswith("custom:"):
        return profession_key[len("custom:"):].strip()

    # sub_key вигляду "agro_tractor" → cat_key="agro", sub_key="agro_tractor"
    cat_key, _, _ = profession_key.partition("_")
    sub = get_subcategory(cat_key, profession_key)
    if not sub or not sub.keywords:
        return ""
    return sub.keywords[0]


# ───────────────────────────────────────────────────────
# Динамічна генерація запитів з підписок
# ───────────────────────────────────────────────────────

def build_jobs(client: TursoClient) -> list[tuple[str, str, str]]:
    """Формує унікальні (country, city_slug, query) з активних підписок.

    Дедуплікує: якщо 5 підписок на (ua, kyiv, "кухар") — один запит.
    """
    subs = list_active_subscriptions(client)
    seen: set[tuple[str, str, str]] = set()
    jobs: list[tuple[str, str, str]] = []

    for sub in subs:
        query = _query_from_profession_key(sub.profession_key, sub.country)
        job = (sub.country, sub.city_slug, query)
        if job in seen:
            continue
        seen.add(job)
        jobs.append(job)

    return jobs


# ───────────────────────────────────────────────────────
# Парсинг
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

    if not USE_WORKUA:
        parsers = [p for p in parsers if p.source_key != "workua_ua"]

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
    print("СТАРТ ЦИКЛУ АГРЕГАЦІЇ (v2: user_subscriptions)", flush=True)
    print("=" * 60, flush=True)

    subs = list_active_subscriptions(client)
    print(f"\n📊 Активних підписок: {len(subs)}", flush=True)

    jobs = build_jobs(client)
    print(f"📊 Унікальних запитів (дедупліковано): {len(jobs)}", flush=True)

    if not jobs:
        print("ℹ️  Немає активних підписок — виходимо.", flush=True)
        return

    print("\nЗапити:", flush=True)
    for country, city, query in jobs:
        print(f"  → {country}/{city or '—'}: {query!r}", flush=True)

    print(f"\n{'=' * 60}", flush=True)
    total_found = 0
    total_new = 0
    for country, city, query in jobs:
        found, new = await run_one(country, city, query, client)
        total_found += found
        total_new += new

    print(f"\n{'=' * 60}", flush=True)
    print(f"✅ Знайдено всього: {total_found}", flush=True)
    print(f"✅ Нових збережено: {total_new}", flush=True)

    rows = client.execute("SELECT COUNT(*) FROM vacancies")
    print(f"✅ Всього у БД vacancies: {rows[0][0]}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())

"""Будує data/jobs/robota_cities.json з довідника назв → ID.

Використовується як fallback, бо API getCities на dracula.robota.ua
віддає 403.
"""
from __future__ import annotations

import json
from pathlib import Path


# ──────────────────────────────────────────────────────────
# Мапа: українська назва міста → ID у Robota.ua
# (взято з того JSON, який ти скидав раніше)
# ──────────────────────────────────────────────────────────
NAME_TO_ROBOTA_ID: dict[str, int] = {
    # Обласні центри та великі міста
    "Київ": 1,
    "Львів": 2,
    "Одеса": 3,
    "Дніпро": 4,
    "Вінниця": 5,
    "Донецьк": 6,
    "Житомир": 7,
    "Запоріжжя": 9,
    "Івано-Франківськ": 10,
    "Кропивницький": 11,
    "Луганськ": 13,
    "Луцьк": 14,
    "Миколаїв": 15,
    "Полтава": 17,
    "Рівне": 18,
    "Суми": 19,
    "Тернопіль": 20,
    "Харків": 21,
    "Херсон": 22,
    "Хмельницький": 23,
    "Черкаси": 24,
    "Чернігів": 25,
    "Чернівці": 26,
    "Маріуполь": 27,
    "Ужгород": 28,
    "Сімферополь": 29,
    "Кривий Ріг": 31,
    "Севастополь": 32,
    # ... (решта з мого попереднього повідомлення — 150+ міст)
}


def main() -> None:
    cities_file = Path("data/cities/ua.json")
    out_file = Path("data/jobs/robota_cities.json")

    if not cities_file.exists():
        print(f"❌ Не знайдено {cities_file}")
        return

    data = json.loads(cities_file.read_text(encoding="utf-8"))
    cities_list = data.get("cities", [])

    result: list[dict] = []
    matched = 0
    skipped = 0

    for c in cities_list:
        name = c.get("name")
        slug = c.get("slug")
        if not name or not slug:
            continue

        rid = NAME_TO_ROBOTA_ID.get(name)
        if rid is None:
            skipped += 1
            continue

        result.append({
            "id": str(rid),
            "slug": slug,
            "name": name,
        })
        matched += 1

    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"✅ Записано {len(result)} міст у {out_file}")
    print(f"   Зматчено: {matched}")
    print(f"   Пропущено (немає в мапі): {skipped}")


if __name__ == "__main__":
    main()

"""Видаляє вакансії старіші за N днів з Turso.

Запускається з GitHub Actions.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tumbleweed.config import settings
from tumbleweed.db.client import TursoClient

DAYS_OLD = 7


def main() -> None:
    print(f"=== Cleanup TumbleWeed: видаляю старіші за {DAYS_OLD} днів ===")

    client = TursoClient(settings.turso_url, settings.turso_token)

    # Скільки до
    rows = client.execute("SELECT COUNT(*) FROM vacancies")
    before = int(rows[0][0]) if rows else 0
    print(f"Vacancies до: {before}")

    # Скільки старих
    rows = client.execute(
        "SELECT COUNT(*) FROM vacancies WHERE saved_at < datetime('now', ?)",
        [f"-{DAYS_OLD} days"],
    )
    old_count = int(rows[0][0]) if rows else 0
    print(f"Старіших за {DAYS_OLD} днів: {old_count}")

    if old_count == 0:
        print("Нічого видаляти.")
        return

    # Видалити
    client.execute_non_query(
        "DELETE FROM vacancies WHERE saved_at < datetime('now', ?)",
        [f"-{DAYS_OLD} days"],
    )

    # Також видалити відповідні seen_vacancies (orphans)
    client.execute_non_query(
        "DELETE FROM seen_vacancies WHERE NOT EXISTS (SELECT 1 FROM vacancies v WHERE v.raw_id = seen_vacancies.raw_id AND v.source_key = seen_vacancies.source_key)"
    )

    # Скільки після
    rows = client.execute("SELECT COUNT(*) FROM vacancies")
    after = int(rows[0][0]) if rows else 0
    print(f"Vacancies після: {after}")
    print(f"✅ Видалено: {before - after}")


if __name__ == "__main__":
    main()

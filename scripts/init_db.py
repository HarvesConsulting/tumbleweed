"""Створити таблиці TumbleWeed у Turso."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tumbleweed.config import settings
from tumbleweed.db.client import TursoClient
from tumbleweed.db.schema import ensure_schema


def main() -> None:
    client = TursoClient(settings.turso_url, settings.turso_token)
    ensure_schema(client)
    print("✅ Таблиці створено")

    rows = client.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    )
    print("\nТаблиці в БД:")
    for row in rows:
        print(f"  • {row[0]}")


if __name__ == "__main__":
    main()
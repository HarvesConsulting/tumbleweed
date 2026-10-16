"""Одноразове застосування схеми TumbleWeed."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from tumbleweed.config import settings
from tumbleweed.db.client import TursoClient
from tumbleweed.db.schema import ensure_schema


def main():
    client = TursoClient(settings.turso_url, settings.turso_token)
    ensure_schema(client)

    # Показуємо, що створилось
    print("\n📋 Таблиці:")
    rows = client.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    )
    for (name,) in rows:
        print(f"  ✓ {name}")

    print("\n📋 Колонки user_subscriptions:")
    rows = client.execute("PRAGMA table_info(user_subscriptions)")
    for r in rows:
        # r: (cid, name, type, notnull, dflt_value, pk)
        print(f"  {r[1]:<20} {r[2]:<15} {'NOT NULL' if r[3] else '':<10} {'PK' if r[5] else ''}")

    print("\n📋 Індекси user_subscriptions:")
    rows = client.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='user_subscriptions'"
    )
    for (name,) in rows:
        print(f"  ✓ {name}")


if __name__ == "__main__":
    main()

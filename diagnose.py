"""Діагностика таблиць TumbleWeed vs RentAlert."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from tumbleweed.config import settings
from tumbleweed.db.client import TursoClient


client = TursoClient(settings.turso_url, settings.turso_token)


def show_table(name: str) -> None:
    print(f"\n=== {name} ===")

    rows = client.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
        [name],
    )
    if not rows:
        print("  (не існує)")
        return

    print("  CREATE TABLE:")
    for line in rows[0][0].splitlines():
        print(f"    {line}")

    count = client.execute(f"SELECT COUNT(*) FROM {name}")[0][0]
    print(f"  Рядків: {count}")


def main() -> None:
    # Наші таблиці
    for name in [
        "vacancies",
        "seen_vacancies",
        "user_jobs",
        "user_subscriptions",
        "user_seen_vacancies",
    ]:
        show_table(name)

    # RentAlert (для довідки — які імена вони займають)
    print("\n\n=== ВСІ ТАБЛИЦІ ===")
    rows = client.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    )
    for (name,) in rows:
        print(f"  {name}")


if __name__ == "__main__":
    main()

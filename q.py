"""Швидкий запуск SQL-запиту у Turso.

Використання:
  python q.py "SELECT * FROM vacancies LIMIT 5"
  python q.py "SELECT COUNT(*) FROM vacancies"
"""
import sys

sys.path.insert(0, "src")

from tumbleweed.config import settings
from tumbleweed.db.client import TursoClient


def main():
    if len(sys.argv) < 2:
        print("Використання: python q.py \"SELECT ...\"")
        sys.exit(1)

    sql = sys.argv[1]

    client = TursoClient(settings.turso_url, settings.turso_token)
    rows = client.execute(sql)

    if not rows:
        print("(порожньо)")
        return

    for r in rows:
        print(" | ".join(str(x) if x is not None else "NULL" for x in r))


if __name__ == "__main__":
    main()

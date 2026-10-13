"""Діагностика: скільки в seen_vacancies і vacancies, і чи збігається."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tumbleweed.config import settings
from tumbleweed.db.client import TursoClient

c = TursoClient(settings.turso_url, settings.turso_token)

# 1. Скільки всього
for table in ["vacancies", "seen_vacancies"]:
    r = c.execute(f"SELECT COUNT(*) FROM {table}")
    print(f"{table}: {r[0][0]}")

# 2. Скільки агро в кожній таблиці
for table in ["vacancies", "seen_vacancies"]:
    r = c.execute(
        f"SELECT title FROM {table} WHERE "
        f"LOWER(title) LIKE '%агроном%' OR "
        f"LOWER(title) LIKE '%тракторист%' OR "
        f"LOWER(title) LIKE '%комбайн%' OR "
        f"LOWER(title) LIKE '%фермер%'"
    )
    print(f"\nАгро у {table}: {len(r)}")
    for row in r[:10]:
        print(f"  • {row[0][:70]}")

# 3. Порівняння: що є в seen, але немає в vacancies?
r = c.execute("""
    SELECT s.title FROM seen_vacancies s
    LEFT JOIN vacancies v ON s.id = v.id
    WHERE v.id IS NULL
    LIMIT 20
""")
print(f"\nУ seen, але не у vacancies: {len(r)} (перші 20)")
for row in r:
    print(f"  • {row[0][:70]}")

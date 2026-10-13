"""Перевірка: чи матчер знаходить вакансії для нашого профілю."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tumbleweed.config import settings
from tumbleweed.db.client import TursoClient
from tumbleweed.db.queries_jobs import list_active_profiles
from tumbleweed.services.matcher import find_vacancies_for_profile


def main() -> None:
    c = TursoClient(settings.turso_url, settings.turso_token)

    # 1. Скільки вакансій у Києві?
    rows = c.execute(
        "SELECT COUNT(*) FROM vacancies WHERE country = ? AND city_slug = ?",
        ["ua", "kyiv"],
    )
    print(f"Всього вакансій у ua/kyiv: {rows[0][0]}")

    # 2. Приклади
    rows = c.execute(
        "SELECT title FROM vacancies WHERE country = 'ua' AND city_slug = 'kyiv' LIMIT 20"
    )
    print("\nПриклади 20 вакансій у Києві:")
    for r in rows:
        print(f"  • {r[0][:75]}")

    # 3. Чи є вакансії з "агроном"?
    rows = c.execute(
        "SELECT title FROM vacancies "
        "WHERE LOWER(title) LIKE '%агроном%' OR LOWER(title) LIKE '%agronom%'"
    )
    print(f"\nВакансій зі словом «агроном» у всій БД: {len(rows)}")
    for r in rows[:10]:
        print(f"  • {r[0][:75]}")

    # 4. Активні профілі
    profiles = list_active_profiles(c)
    print(f"\nАктивних профілів: {len(profiles)}")
    for p in profiles:
        print(f"  {p.chat_id}: {p.country}/{p.cities} | "
              f"profs={p.professions} | jt={p.job_types} | exp={p.experience}")

    # 5. Матчер без обмеження seen (since_hours=720 = 30 днів)
    print("\n=== Матчер ===")
    for p in profiles:
        matches = find_vacancies_for_profile(c, p, since_hours=720, max_per_user=20)
        print(f"Для {p.chat_id}: знайдено {len(matches)} вакансій")
        for v in matches[:10]:
            print(f"  ✅ {v['title'][:70]}")

    # 6. Перевіримо `seen` окремо
    rows = c.execute(
        "SELECT COUNT(*) FROM user_seen_vacancies WHERE chat_id = ?",
        [profiles[0].chat_id] if profiles else [""],
    )
    print(f"\nУже позначено як 'надіслано': {rows[0][0]} вакансій")


if __name__ == "__main__":
    main()

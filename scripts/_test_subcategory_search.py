"""Тест пошуку підкатегорій."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tumbleweed.services.subcategory_search import (
    all_subcategories,
    get_category_label,
    search_subcategories,
)


def show(cat: str, query: str) -> None:
    print(f'\n--- "{query}" у {cat} ---')
    results = search_subcategories(cat, query)
    if not results:
        print("  (нічого)")
        return
    for s in results:
        print(f"  {s.key:>20}  {s.label}")


def main() -> None:
    print("Сфера agro:", get_category_label("agro"))
    print("Усього підкатегорій у agro:", len(all_subcategories("agro")))

    show("agro", "трак")
    show("agro", "ферм")
    show("agro", "комб")
    show("bud", "мул")
    show("it", "python")
    show("it", "front")
    show("med", "медсестра")
    show("driver", "b")
    show("food", "кух")
    show("factory", "токар")
    show("agro", "ффф")  # нічого


if __name__ == "__main__":
    main()

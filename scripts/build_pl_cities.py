"""Автоматично зібрати city_id для Польщі з OLX.pl offers."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from curl_cffi import requests as cffi_requests


def main() -> None:
    url = "https://www.olx.pl/api/v1/offers/"
    cities: dict[str, dict] = {}  # slug → {id, name}

    # Збираємо з кількох категорій і сторінок
    categories = [4]  # Робота
    offsets = [0, 40, 80, 120, 160]

    for cat_id in categories:
        for offset in offsets:
            params = {
                "offset": offset,
                "limit": 40,
                "category_id": cat_id,
                "sort_by": "created_at:desc",
            }
            r = cffi_requests.get(
                url,
                params=params,
                headers={"Accept": "application/json"},
                impersonate="chrome124",
                timeout=30,
            )
            if r.status_code != 200:
                print(f"❌ cat={cat_id} offset={offset}: HTTP {r.status_code}")
                continue

            items = r.json().get("data") or []
            print(f"cat={cat_id} offset={offset}: {len(items)} items")

            for it in items:
                loc = it.get("location") or {}
                city = loc.get("city") or {}
                city_id = city.get("id")
                city_name = city.get("name")
                if not city_id or not city_name:
                    continue
                # slug = lower, replace spaces
                # Транслітерація польських наголосів → латиниця
                _TRANSLIT = str.maketrans({
                    "ą": "a", "ć": "c", "ę": "e", "ł": "l", "ń": "n",
                    "ó": "o", "ś": "s", "ź": "z", "ż": "z",
                    "Ą": "A", "Ć": "C", "Ę": "E", "Ł": "L", "Ń": "N",
                    "Ó": "O", "Ś": "S", "Ź": "Z", "Ż": "Z",
                })
                slug = city_name.translate(_TRANSLIT).lower().replace(" ", "-")
                if slug not in cities:
                    cities[slug] = {"id": city_id, "name": city_name}

    # Зберегти
    out = Path("data/jobs/pl_cities.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(cities, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\n✅ Збережено {len(cities)} міст у {out}")
    for slug, info in sorted(cities.items()):
        print(f"  {slug:20s} → id={info['id']}")


if __name__ == "__main__":
    main()

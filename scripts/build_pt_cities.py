"""Зібрати city_id для Португалії з OLX.pt offers."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from curl_cffi import requests as cffi_requests

_TRANSLIT = str.maketrans({
    "á": "a", "à": "a", "â": "a", "ã": "a", "é": "e", "ê": "e",
    "í": "i", "ó": "o", "ô": "o", "õ": "o", "ú": "u", "ç": "c",
})


def main() -> None:
    url = "https://www.olx.pt/api/v1/offers/"
    cities: dict[str, dict] = {}

    for offset in [0, 40, 80, 120, 160]:
        params = {
            "offset": offset,
            "limit": 40,
            "category_id": 190,
        }
        r = cffi_requests.get(
            url,
            params=params,
            headers={"Accept": "application/json"},
            impersonate="chrome124",
            timeout=30,
        )
        if r.status_code != 200:
            print(f"offset={offset}: HTTP {r.status_code}")
            continue

        items = r.json().get("data") or []
        print(f"offset={offset}: {len(items)} items")

        for it in items:
            loc = it.get("location") or {}
            city = loc.get("city") or {}
            city_id = city.get("id")
            city_name = city.get("name")
            if not city_id or not city_name:
                continue
            slug = city_name.translate(_TRANSLIT).lower().replace(" ", "-").replace(",", "").replace("/", "-")
            if slug not in cities:
                cities[slug] = {"id": city_id, "name": city_name}

    out = Path("data/jobs/pt_cities.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(cities, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\n✅ Збережено {len(cities)} міст у {out}")
    for slug, info in sorted(cities.items()):
        print(f"  {slug:25s} → id={info['id']}")


if __name__ == "__main__":
    main()

"""Прощупування category_id для OLX.ua — знайти всі підкатегорії 'Робота'."""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from curl_cffi import requests as cffi_requests

HEADERS = {"Accept": "application/json"}
BASE = "https://www.olx.ua/api/v1/offers/"

# Діапазони для перевірки
CANDIDATES = (
    list(range(1800, 1851)) +      # біля 1804 (косметологія)
    list(range(1000, 1051)) +      # загальні
    [4, 5, 6, 7, 8, 9, 10]         # найнижчі
)


def probe(cat_id: int) -> tuple[int, int, str]:
    """Повертає (http_status, кількість_items, перший_title)."""
    try:
        r = cffi_requests.get(
            BASE,
            params={
                "offset": 0,
                "limit": 2,
                "category_id": cat_id,
                "sort_by": "created_at:desc",
            },
            headers=HEADERS,
            impersonate="chrome124",
            timeout=15,
        )
    except Exception as e:
        return (-1, 0, f"ERR {type(e).__name__}")

    if r.status_code != 200:
        try:
            detail = r.json().get("error", {}).get("detail", "")[:50]
        except Exception:
            detail = r.text[:50]
        return (r.status_code, 0, detail)

    data = r.json().get("data") or []
    first_title = (data[0].get("title", "")[:60] if data else "")
    return (200, len(data), first_title)


def main() -> None:
    live: list[tuple[int, int, str]] = []
    print(f"Перевіряємо {len(CANDIDATES)} category_id...\n")
    for i, c in enumerate(CANDIDATES, 1):
        status, n, info = probe(c)
        marker = "✅" if status == 200 and n > 0 else ("  " if status == 400 else "⚠️")
        print(f"  {marker} cat={c:>5}  HTTP {status:>3}  n={n}  {info}")
        if status == 200 and n > 0:
            live.append((c, n, info))
        time.sleep(0.4)  # щоб не спалитись

    print(f"\n{'=' * 70}")
    print(f"ЖИВИХ КАТЕГОРІЙ: {len(live)}")
    for c, n, info in live:
        print(f"  {c:>5}  {info}")


if __name__ == "__main__":
    main()

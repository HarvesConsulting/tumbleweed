"""Тест: чи OLX PL API віддає вакансії для gdansk."""
import json
from curl_cffi import requests as cffi_requests

url = "https://www.olx.pl/api/v1/offers/"

# Тест 1: з city_id=2853 (gdansk)
print("=== Тест 1: query + city_id=2853 ===")
params = {
    "offset": 0,
    "limit": 40,
    "category_id": 4,
    "query": "traktorzysta",
    "city_id": 2853,
    "sort_by": "created_at:desc",
}
r = cffi_requests.get(
    url,
    params=params,
    headers={"Accept": "application/json"},
    impersonate="chrome124",
    timeout=20,
)
print(f"Status: {r.status_code}")
data = r.json()
items = data.get("data") or []
print(f"Found: {len(items)}")
for it in items[:5]:
    title = it.get("title", "")[:60]
    loc = (it.get("location") or {}).get("city") or {}
    city = loc.get("name", "?")
    print(f"  - {city}: {title}")

# Тест 2: без city_id (вся Польща)
print("\n=== Тест 2: query БЕЗ city_id ===")
params2 = {k: v for k, v in params.items() if k != "city_id"}
r2 = cffi_requests.get(
    url,
    params=params2,
    headers={"Accept": "application/json"},
    impersonate="chrome124",
    timeout=20,
)
print(f"Status: {r2.status_code}")
data2 = r2.json()
items2 = data2.get("data") or []
print(f"Found: {len(items2)}")
for it in items2[:5]:
    title = it.get("title", "")[:60]
    loc = (it.get("location") or {}).get("city") or {}
    city = loc.get("name", "?")
    print(f"  - {city}: {title}")

# Тест 3: без query, тільки city_id=2853
print("\n=== Тест 3: city_id=2853 БЕЗ query ===")
params3 = {k: v for k, v in params.items() if k != "query"}
r3 = cffi_requests.get(
    url,
    params=params3,
    headers={"Accept": "application/json"},
    impersonate="chrome124",
    timeout=20,
)
print(f"Status: {r3.status_code}")
data3 = r3.json()
items3 = data3.get("data") or []
print(f"Found: {len(items3)}")
for it in items3[:5]:
    title = it.get("title", "")[:60]
    loc = (it.get("location") or {}).get("city") or {}
    city = loc.get("name", "?")
    print(f"  - {city}: {title}")

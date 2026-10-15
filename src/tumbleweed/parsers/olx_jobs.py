"""Парсер вакансій OLX (UA, PL, RO).

Використовує внутрішній API olx.{domain}/api/v1/offers/.
Кожна країна має СПИСОК category_id (бо OLX.ua розбиває «Роботу»
на ~50 підкатегорій; OLX.pl/ro має одну категорію 4).

category_id для OLX.ua перевірено 2026-10-13: діапазон 1800–1850,
плюс 6 (кур'єри) і 7 (вантажники).
"""
from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass

from curl_cffi import requests as cffi_requests

from .base_job import JobParser, Vacancy


@dataclass(frozen=True)
class OlxCountryConfig:
    country: str
    domain: str
    category_ids: list[int]         # список категорій (для UA — багато)
    city_ids: dict[str, int]


# ~50 підкатегорій «Роботи» OLX.ua
UA_JOB_CATEGORIES = [
    6, 7,                                   # кур'єри, вантажники
    1800, 1801, 1802, 1803, 1804, 1805, 1806, 1807, 1808, 1809,
    1810, 1811, 1812, 1813, 1814, 1815, 1816, 1817, 1818, 1819,
    1820, 1821, 1822, 1823, 1824, 1825, 1826, 1827, 1828, 1829,
    1830, 1831, 1832, 1833, 1834, 1835, 1836, 1837, 1838, 1839,
    1840, 1841, 1842, 1843, 1844, 1845, 1846, 1847, 1848, 1849,
    1850,
]


OLX_COUNTRIES: dict[str, OlxCountryConfig] = {
    "ua": OlxCountryConfig(
        country="ua",
        domain="olx.ua",
        category_ids=UA_JOB_CATEGORIES,
        city_ids={
            "kyiv": 268,
            "lviv": 273,
            "odesa": 271,
            "kharkiv": 269,
            "dnipro": 270,
        },
    ),
    "pl": OlxCountryConfig(
        country="pl",
        domain="olx.pl",
        category_ids=[4],                   # у PL «Робота» — одна категорія
        city_ids={
            "warszawa": 17871,
            "krakow": 8959,
            "wroclaw": 9462,
            "gdansk": 2853,
            "poznan": 10011,
        },
    ),
    "ro": OlxCountryConfig(
        country="ro",
        domain="olx.ro",
        category_ids=[4],
        city_ids={
            "bucuresti": 1,
        },
    ),
}

HEADERS = {
    "Accept": "application/json",
    "Accept-Language": "uk-UA,uk;q=0.9,en;q=0.8",
}


class OlxJobParser(JobParser):
    """Парсер вакансій OLX для однієї країни."""

    def __init__(self, cfg: OlxCountryConfig):
        self.cfg = cfg
        self.source_key = f"olx_{cfg.country}"
        self.country = cfg.country
        self.display_name = f"OLX {cfg.country.upper()}"

    async def fetch(
        self,
        city_slug: str | None = None,
        query: str = "",
        limit: int = 40,
    ) -> list[Vacancy]:
        """Якщо є query — швидкий шлях (один запит).
        Якщо немає — обхід усіх категорій."""

        if query:
            # ── Швидкий шлях з пагінацією ────────────────────────
            print(f"  → {self.display_name} (query={query!r}, з пагінацією)")

            PAGE_SIZE = 50
            MAX_PAGES = 5
            total_wanted = max(1, limit)
            pages_needed = min(MAX_PAGES, (total_wanted + PAGE_SIZE - 1) // PAGE_SIZE)

            all_vacancies: list[Vacancy] = []
            seen_ids: set[str] = set()
            offset = 0

            for page_num in range(pages_needed):
                try:
                    batch = await self._fetch_one(
                        cat_id=self.cfg.category_ids[0],
                        city_slug=city_slug,
                        query=query,
                        limit=PAGE_SIZE,
                        offset=offset,
                    )
                except Exception as e:
                    print(f"  ❌ {self.display_name}: {type(e).__name__}: {e}")
                    break

                if not batch:
                    print(f"  ℹ️  offset={offset}: порожньо — стоп")
                    break

                new_on_page = 0
                for v in batch:
                    if v.raw_id not in seen_ids:
                        seen_ids.add(v.raw_id)
                        all_vacancies.append(v)
                        new_on_page += 1

                print(
                    f"  📄 offset={offset}: отримано {len(batch)}, "
                    f"нових {new_on_page} (всього: {len(all_vacancies)})"
                )

                if len(all_vacancies) >= total_wanted:
                    break

                if len(batch) < PAGE_SIZE:
                    # неповна сторінка — далі не йдемо
                    break

                offset += PAGE_SIZE

            return all_vacancies[:total_wanted]

        # ── Повільний шлях — обхід усіх категорій (без query) ────
        print(f"  → {self.display_name} (обхід {len(self.cfg.category_ids)} категорій)")
        seen: dict[str, Vacancy] = {}
        per_cat_limit = max(10, limit // max(1, len(self.cfg.category_ids)) + 5)

        for cat_id in self.cfg.category_ids:
            try:
                items = await self._fetch_one(
                    cat_id=cat_id,
                    city_slug=city_slug,
                    query=query,
                    limit=per_cat_limit,
                    offset=0,
                )
            except Exception as e:
                print(f"⚠️  {self.display_name} cat={cat_id}: {type(e).__name__}: {e}")
                continue

            for v in items:
                if v and v.raw_id not in seen:
                    seen[v.raw_id] = v

            await asyncio.sleep(random.uniform(0.3, 0.8))

        return list(seen.values())[:limit]

    async def _fetch_one(
        self,
        cat_id: int,
        city_slug: str | None,
        query: str,
        limit: int,
        offset: int = 0,
    ) -> list[Vacancy]:
        url = f"https://www.{self.cfg.domain}/api/v1/offers/"
        params: dict[str, object] = {
            "offset": offset,
            "limit": min(limit, 50),
            "category_id": cat_id,
            "sort_by": "created_at:desc",
        }
        if query:
            params["query"] = query

        if city_slug:
            city_id = None

            # Гілка 1: olx_ua_64 → 64
            if city_slug.startswith("olx_"):
                parts = city_slug.split("_")
                if len(parts) >= 3:
                    try:
                        city_id = int(parts[-1])
                    except ValueError:
                        pass

            # Гілка 2: hardcoded (kyiv, lviv, ...)
            elif city_slug in self.cfg.city_ids:
                city_id = self.cfg.city_ids[city_slug]

            # Гілка 3: НОВА — через довідник (kropyvnytskyi → olx_id)
            if city_id is None:
                try:
                    from ..services.city_search import get_city
                    city = get_city(self.country, city_slug)
                    if city and city.olx_id:
                        city_id = city.olx_id
                        print(
                            f"  ↻ {self.display_name}: '{city_slug}' "
                            f"→ '{city.name}' → city_id={city_id}"
                        )
                except Exception as e:
                    print(f"  ⚠️ {self.display_name}: fallback lookup failed: {e}")

            if city_id:
                params["city_id"] = city_id

        await asyncio.sleep(random.uniform(2.0, 4.0))

        def _do_request():
            return cffi_requests.get(
                url,
                params=params,
                headers=HEADERS,
                impersonate="chrome124",
                timeout=20,
            )

        r = await asyncio.to_thread(_do_request)

        if r.status_code != 200:
            return []

        items = (r.json().get("data") or [])
        return [v for v in (self._parse_item(it, city_slug or "") for it in items) if v]

    def _parse_item(self, item: dict, city_slug: str) -> Vacancy | None:
        raw_id = str(item.get("id") or "")
        title = (item.get("title") or "").strip()
        if not raw_id or not title:
            return None

        # --- params: price, type, experience, agreement ---
        salary = job_type = experience = ""
        for p in item.get("params", []):
            k, v = p.get("key"), p.get("value")
            if not isinstance(v, dict):
                continue
            label = v.get("label", "") or ""
            if k == "salary" and label:
                salary = label
            elif k == "price" and label and not salary:
                salary = label
            elif k in ("type", "job_type") and label:
                job_type = label
            elif k == "experience" and label:
                experience = label

        # --- компанія: company → user.name → contact.name ---
        company = None
        comp = item.get("company")
        if isinstance(comp, dict):
            company = comp.get("name")
        if not company:
            user = item.get("user") or {}
            if isinstance(user, dict):
                company = user.get("name")
        if not company:
            contact = item.get("contact") or {}
            if isinstance(contact, dict):
                company = contact.get("name")

        # --- фото ---
        photo = None
        photos = item.get("photos") or []
        if photos and isinstance(photos[0], dict):
            photo = photos[0].get("link")

        # --- локація ---
        location = item.get("location") or {}
        city_name = (location.get("city") or {}).get("name") or ""

        return Vacancy(
            id=Vacancy.make_id(self.source_key, raw_id),
            raw_id=raw_id,
            source_key=self.source_key,
            country=self.country,
            city_slug=city_slug or city_name.lower(),
            title=title,
            link=item.get("url", "") or "",
            company=company,
            salary=salary or None,
            job_type=job_type or None,
            experience=experience or None,
            photo=photo,
            created_at=item.get("created_at"),
            extra={"location": location},
        )

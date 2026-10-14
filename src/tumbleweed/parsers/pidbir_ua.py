"""Парсер вакансій з Pidbir.ua (Україна).

JSON API на https://admin.pidbir.ua/api/v1/vacancy/feed.
Повертає {data: [...], meta: {total, last_page, per_page, current_page}}.

Pidbir.ua — вузькоспеціалізований агро-сайт (мало вакансій),
тому використовується як ДОПОВНЕННЯ до Robota.ua / OLX / Work.ua.
"""
from __future__ import annotations

import asyncio
import random
import re
import unicodedata
from html import unescape

from curl_cffi import requests as cffi_requests

from .base_job import JobParser, Vacancy
from ..services.city_search import get_city


class PidbirUaParser(JobParser):
    """Парсер вакансій з Pidbir.ua."""

    source_key = "pidbir_ua"
    country = "ua"
    display_name = "Pidbir.ua"

    API_URL = "https://admin.pidbir.ua/api/v1/vacancy/feed"

    HEADERS = {
        "accept": "application/json, text/plain, */*",
        "accept-language": "uk",
        "origin": "https://pidbir.ua",
        "referer": "https://pidbir.ua/",
    }

    # досвід: числовий код → людський опис
    EXPERIENCE_MAP = {
        "0": "Без досвіду",
        "1": "від 1 року",
        "2": "від 2 років",
        "3": "від 3 років",
    }

    async def fetch(
        self,
        city_slug: str | None = None,
        query: str = "",
        limit: int = 40,
    ) -> list[Vacancy]:
        """Повертає вакансії з Pidbir.ua.

        Args:
            city_slug: ігнорується на рівні API — фільтруємо після парсингу
            query: ключове слово (обов'язкове — без нього сенсу мало)
            limit: максимум вакансій
        """
        if not query:
            # без keyword Pidbir віддає загальний фід, але він занадто малий
            print(f"  ℹ️  {self.display_name}: без query — пропускаємо")
            return []

        vacancies: list[Vacancy] = []
        seen_ids: set[int] = set()

        page = 1
        MAX_PAGES = 5  # запобіжник (у Pidbir зазвичай 1-2 сторінки)

        while page <= MAX_PAGES:
            params = {"page": page, "query": query}
            await asyncio.sleep(random.uniform(1.0, 2.0))

            try:
                r = await asyncio.to_thread(
                    lambda p=params: cffi_requests.get(
                        self.API_URL,
                        params=p,
                        headers=self.HEADERS,
                        impersonate="chrome124",
                        timeout=20,
                    )
                )
            except Exception as e:
                print(f"  ❌ {self.display_name}: {type(e).__name__}: {e}")
                break

            if r.status_code != 200:
                print(f"  ❌ {self.display_name}: HTTP {r.status_code} (page={page})")
                break

            try:
                payload = r.json() or {}
            except Exception as e:
                print(f"  ❌ {self.display_name}: JSON error: {e}")
                break

            items = payload.get("data") or []
            meta = payload.get("meta") or {}
            total = meta.get("total", 0)
            last_page = meta.get("last_page", 1)

            if not items:
                print(
                    f"  ℹ️  {self.display_name}: page={page} порожньо "
                    f"(total={total})"
                )
                break

            new_on_page = 0
            for item in items:
                vid = item.get("id")
                if not vid or vid in seen_ids:
                    continue
                seen_ids.add(vid)

                v = self._parse_item(item, city_slug or "")
                if v:
                    vacancies.append(v)
                    new_on_page += 1

            print(
                f"  📄 {self.display_name}: page={page}/{last_page}, "
                f"отримано {len(items)}, нових {new_on_page}, "
                f"всього {len(vacancies)}/{total}"
            )

            if len(vacancies) >= limit:
                break
            if page >= last_page:
                break

            page += 1

        return vacancies[:limit]

    def _parse_item(self, item: dict, city_slug: str) -> Vacancy | None:
        """Перетворює один елемент JSON у Vacancy."""
        vid = str(item.get("id") or "")
        title = (item.get("job_title") or "").strip()
        if not vid or not title:
            return None

        # ── Місто ─────────────────────────────────────
        city_obj = item.get("job_city") or {}
        city_name = (city_obj.get("main_text") or "").strip()
        region = (city_obj.get("secondary_text") or "").strip()

        district_obj = item.get("job_district") or {}
        district = (district_obj.get("main_text") or "").strip()

        # ── ФІЛЬТР ПО МІСТУ ───────────────────────────
        # Pidbir API НЕ фільтрує по місту — робимо це самі.
        if city_slug:
            try:
                target = get_city(self.country, city_slug)
            except Exception:
                target = None

            if target:
                # Матч 1: точна назва міста
                name_match = target.name.lower() == city_name.lower()

                # Матч 2: регіон (для сіл типу "Лядське" в "Тернопільській")
                region_match = (
                    target.region
                    and region
                    and target.region.lower() in region.lower()
                )

                if not (name_match or region_match):
                    return None  # не наше місто — пропускаємо

        # ── Компанія ──────────────────────────────────
        company = None
        company_obj = item.get("company")
        if isinstance(company_obj, dict):
            # Пріоритет: brand_name → company_name → responsible_user_name
            company = (
                (company_obj.get("brand_name") or "").strip()
                or (company_obj.get("company_name") or "").strip()
                or None
            )
        if not company:
            company = (item.get("responsible_user_name") or "").strip() or None

        # ── Зарплата ──────────────────────────────────
        salary_obj = item.get("salary") or {}
        salary_type = salary_obj.get("type") or "none"
        salary = None
        if salary_type != "none":
            start = (salary_obj.get("start_amount") or "").strip()
            end = (salary_obj.get("end_amount") or "").strip()
            note = (salary_obj.get("note") or "").strip()

            # "0" і "" вважаємо відсутніми
            start_ok = start and start != "0"
            end_ok = end and end != "0"

            if start_ok and end_ok and start != end:
                salary = f"{start}–{end} грн"
            elif start_ok:
                salary = f"від {start} грн"
            elif end_ok:
                salary = f"до {end} грн"

            if note:
                salary = f"{salary} ({note})" if salary else note

        # ── Опис (HTML → plain text) ──────────────────
        desc_html = item.get("description_html") or ""
        desc_text = re.sub(r"<[^>]+>", " ", desc_html)
        desc_text = unescape(desc_text)
        desc_text = re.sub(r"\s+", " ", desc_text).strip()
        description = desc_text[:500] or None

        # ── URL: https://pidbir.ua/vacancies/{id}-{slug} ──
        slug = (item.get("slug") or "").strip()
        if slug:
            link = f"https://pidbir.ua/vacancies/{vid}-{slug}"
        else:
            link = f"https://pidbir.ua/vacancies/{vid}"

        # ── city_slug ─────────────────────────────────
        # якщо caller передав city_slug — використовуємо його,
        # інакше нормалізуємо з назви міста
        if not city_slug:
            city_slug = self._normalize_city(city_name)

        # ── Тип зайнятості ────────────────────────────
        emp = item.get("employment_types") or {}
        work = item.get("work_types") or {}
        job_type = None
        if emp.get("full"):
            job_type = "Повна зайнятість"
        elif emp.get("partial"):
            job_type = "Часткова зайнятість"
        elif emp.get("project"):
            job_type = "Проєктна робота"
        elif work.get("remote"):
            job_type = "Віддалена робота"

        # ── Досвід ────────────────────────────────────
        experience = self.EXPERIENCE_MAP.get(str(item.get("experience") or ""))

        # ── Телефон (перший зі списку) ────────────────
        phones = item.get("phones") or []
        phone = phones[0].get("number") if phones and isinstance(phones[0], dict) else None

        return Vacancy(
            id=Vacancy.make_id(self.source_key, vid),
            raw_id=vid,
            source_key=self.source_key,
            country=self.country,
            city_slug=city_slug,
            title=title,
            link=link,
            company=company,
            salary=salary,
            job_type=job_type,
            experience=experience,
            description=description,
            created_at=item.get("created_at") or None,
            extra={
                "city_name": city_name,
                "region": region,
                "district": district,
                "categories": item.get("job_categoy_names") or [],
                "phone": phone,
                "lat": city_obj.get("lat"),
                "lon": city_obj.get("lon"),
            },
        )

    @staticmethod
    def _normalize_city(name: str) -> str:
        """Груба нормалізація назви міста в slug."""
        if not name:
            return ""
        text = name.lower().strip()
        text = unicodedata.normalize("NFKD", text)
        text = "".join(c for c in text if not unicodedata.combining(c))
        text = re.sub(r"[^a-zа-яїієґ0-9\s-]", "", text)
        text = re.sub(r"\s+", "-", text)
        return text

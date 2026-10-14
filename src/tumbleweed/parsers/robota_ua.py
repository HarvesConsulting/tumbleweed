"""Парсер вакансій з Robota.ua (Україна).

GraphQL API на https://dracula.robota.ua/?q=getPublishedVacanciesList.
"""
from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass

from curl_cffi import requests as cffi_requests

from .base_job import JobParser, Vacancy


GRAPHQL_QUERY = """
query getPublishedVacanciesList($filter: PublishedVacanciesFilterInput!, $pagination: PublishedVacanciesPaginationInput!, $sort: PublishedVacanciesSortType!) {
  publishedVacancies(filter: $filter, pagination: $pagination, sort: $sort) {
    totalCount
    items {
      id
      title
      description
      salary { amount comment amountFrom amountTo }
      company { id name logoUrl }
      city { id name }
      schedules { id }
      sortDateText
    }
  }
}
"""


class RobotaUaParser(JobParser):
    """Парсер вакансій з Robota.ua."""

    source_key = "robota_ua"
    country = "ua"
    display_name = "Robota.ua UA"

    API_URL = "https://dracula.robota.ua/?q=getPublishedVacanciesList"

    HEADERS = {
        "accept": "application/json, text/plain, */*",
        "accept-language": "uk",
        "apollographql-client-name": "seeker-web",
        "apollographql-client-version": "f78142a",
        "content-type": "application/json",
        "origin": "https://robota.ua",
        "referer": "https://robota.ua/",
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-site",
    }

    async def fetch(
        self,
        city_slug: str | None = None,
        query: str = "",
        limit: int = 40,
    ) -> list[Vacancy]:
        """Повертає вакансії з Robota.ua, фільтруючи за містом."""

        # ── ФІКС: резолвимо slug → cityId ──────────────────────────
        city_id: int | None = None
        if city_slug:
            # Синтетичний slug виду "robota_ua_1" → int("1")
            if city_slug.startswith("robota_ua_"):
                try:
                    city_id = int(city_slug.rsplit("_", 1)[-1])
                except ValueError:
                    pass

            # Інакше — через сервіс (спочатку API, потім fallback-словник)
            if city_id is None:
                from ..services.robota_cities import get_city_id
                raw = get_city_id(city_slug)
                if raw is not None:
                    try:
                        city_id = int(raw)
                    except (ValueError, TypeError):
                        city_id = None

            if city_id is None:
                print(
                    f"⚠️  {self.display_name}: місто '{city_slug}' "
                    f"не знайдено в довіднику — шукаю по всій Україні"
                )
            else:
                print(
                    f"  → {self.display_name}: фільтр по місту "
                    f"'{city_slug}' (cityId={city_id})"
                )
        # ───────────────────────────────────────────────────────────

        filter_data = {
            "keywords": query or "",
            "militaryVacancyDisplayMode": "APPENDED",
            "metroBranches": [],
            "additionalKeywords": "",
            "clusterKeywords": [],
            "salary": 0,
            "districtIds": [],
            "microDistrictIds": [],
            "scheduleIds": [],
            "rubrics": [],
            "showAgencies": True,
            "showOnlyNoCvApplyVacancies": False,
            "showOnlySpecialNeeds": False,
            "showOnlyWithoutExperience": False,
            "showOnlyNotViewed": False,
            "showWithoutSalary": True,
            "location": {"latitude": 0, "longitude": 0},
            "isForVeterans": False,
            "isReservation": False,
            "isOfficeWithGenerator": False,
            "isOfficeWithShelter": False,
            "gender": None,
            "branchIds": [],
        }

        # ── ФІКС: передаємо cityId у GraphQL-фільтр ────────────────
        if city_id is not None:
            filter_data["cityId"] = city_id
        # ───────────────────────────────────────────────────────────

        variables = {
            "pagination": {"count": min(limit, 40), "page": 0},
            "filter": filter_data,
            "sort": "BY_BUSINESS_SCORE",
        }

        payload = {
            "operationName": "getPublishedVacanciesList",
            "variables": variables,
            "query": GRAPHQL_QUERY,
        }

        await asyncio.sleep(random.uniform(1.0, 2.0))

        def _do_request():
            return cffi_requests.post(
                self.API_URL,
                json=payload,
                headers=self.HEADERS,
                impersonate="chrome124",
                timeout=25,
            )

        r = await asyncio.to_thread(_do_request)

        if r.status_code != 200:
            print(f"❌ {self.display_name}: HTTP {r.status_code} — {r.text[:150]}")
            return []

        try:
            data = r.json()
        except Exception as e:
            print(f"❌ {self.display_name}: JSON error: {e}")
            return []

        items = (data.get("data") or {}).get("publishedVacancies", {}).get("items", [])

        vacancies = []
        for item in items:
            v = self._parse_item(item, city_slug or "")
            if v:
                vacancies.append(v)

        return vacancies

    def _parse_item(self, item: dict, city_slug: str) -> Vacancy | None:
        raw_id = str(item.get("id") or "")
        title = (item.get("title") or "").strip()
        if not raw_id or not title:
            return None

        # Компанія (name + id)
        company = None
        company_id = None
        comp = item.get("company")
        if isinstance(comp, dict):
            company = comp.get("name")
            company_id = comp.get("id")

        # Зарплата
        salary = None
        sal = item.get("salary")
        if isinstance(sal, dict):
            amount = sal.get("amount") or sal.get("amountFrom") or sal.get("amountTo")
            comment = (sal.get("comment") or "").strip()
            if amount:
                salary = f"{amount} грн"
                if comment:
                    salary += f" ({comment})"
            elif comment:
                salary = comment

        # Місто
        city_name = None
        city = item.get("city")
        if isinstance(city, dict):
            city_name = city.get("name")

        # URL: https://robota.ua/company{company_id}/vacancy{vacancy_id}
        if company_id:
            link = f"https://robota.ua/company{company_id}/vacancy{raw_id}"
        else:
            link = f"https://robota.ua/vacancy{raw_id}"

        return Vacancy(
            id=Vacancy.make_id(self.source_key, raw_id),
            raw_id=raw_id,
            source_key=self.source_key,
            country=self.country,
            city_slug=city_slug or (city_name or "").lower(),
            title=title,
            link=link,
            company=company,
            salary=salary,
            description=(item.get("description") or "")[:500] or None,
            created_at=item.get("sortDateText"),
        )

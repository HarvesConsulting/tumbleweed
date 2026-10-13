"""Парсер вакансій з work.ua (Україна).

Використовує публічні HTML-сторінки:
  https://www.work.ua/jobs/?search={query}&city_id={city_id}
"""
from __future__ import annotations

import asyncio
import random
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from curl_cffi import requests as cffi_requests

from .base_job import JobParser, Vacancy


class WorkUaParser(JobParser):
    """Парсер вакансій з work.ua."""

    source_key = "workua_ua"
    country = "ua"
    display_name = "Work.ua UA"

    BASE_URL = "https://www.work.ua"

    CITY_IDS = {
        "kyiv": 1,
        "lviv": 2,
        "odesa": 3,
        "kharkiv": 4,
        "dnipro": 5,
        "zaporizhzhia": 6,
        "vinnytsia": 7,
    }

    HEADERS = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "uk-UA,uk;q=0.9,en;q=0.8",
    }

    async def fetch(
        self,
        city_slug: str | None = None,
        query: str = "",
        limit: int = 40,
    ) -> list[Vacancy]:
        url = f"{self.BASE_URL}/jobs/"
        params: dict[str, object] = {}

        if query:
            params["search"] = query
        if city_slug and city_slug in self.CITY_IDS:
            params["city_id"] = self.CITY_IDS[city_slug]

        await asyncio.sleep(random.uniform(1.0, 2.0))

        def _do_request():
            return cffi_requests.get(
                url,
                params=params,
                headers=self.HEADERS,
                impersonate="chrome124",
                timeout=25,
            )

        r = await asyncio.to_thread(_do_request)

        if r.status_code != 200:
            print(f"❌ {self.display_name}: HTTP {r.status_code}")
            return []

        soup = BeautifulSoup(r.text, "html.parser")
        return self._parse(soup, city_slug or "")[:limit]

    def _parse(self, soup: BeautifulSoup, city_slug: str) -> list[Vacancy]:
        vacancies: list[Vacancy] = []
        # Картки вакансій мають клас "job-link"
        cards = soup.select("div.card.job-link")
        if not cards:
            # Фолбек — будь-який div з класом card + посилання /jobs/
            cards = [d for d in soup.find_all("div", class_="card")
                     if d.find("a", href=re.compile(r"^/jobs/\d+/?$"))]

        for card in cards:
            v = self._parse_card(card, city_slug)
            if v:
                vacancies.append(v)
        return vacancies

    def _parse_card(self, card, city_slug: str) -> Vacancy | None:
        # 1. Посилання на вакансію
        a = card.find("a", href=re.compile(r"^/jobs/\d+/?$"))
        if not a:
            return None

        href = a.get("href", "")
        m = re.match(r"^/jobs/(\d+)/?$", href)
        if not m:
            return None
        raw_id = m.group(1)

        # 2. Title
        title = (a.get_text(strip=True) or a.get("title", "")).strip()
        if not title:
            return None

        # 3. Компанія + зарплата
        company = None
        salary = None

        # «Сміттєві» фрази, які work.ua ставить у salary-блок
        SALARY_NOISE = {
            "після всіх відрахувань", "на руки", "в місяць",
            "за результатами співбесіди", "гідна",
            "не вказано", "за домовленістю",
        }

        def is_salary_text(text: str) -> bool:
            """Чи це зарплата, а не компанія?"""
            low = text.lower()
            # Явні індикатори зарплати
            if "грн" in low or "usd" in low or "eur" in low:
                return True
            # Числа з пробілами/дефісами (50 000 – 120 000)
            import re as _re
            if _re.match(r"^[\d\s\-–—₴$€]+$", text):
                return True
            # «Сміттєві» фрази
            if low in SALARY_NOISE:
                return True
            return False

        # Перебираємо всі span.strong-600
        for strong in card.find_all("span", class_="strong-600"):
            text = strong.get_text(strip=True)
            if not text:
                continue
            if is_salary_text(text):
                if not salary:
                    salary = text
                continue
            if not company:
                company = text

        # 4. Якщо компанія не знайдена — беремо з <img alt="...">
        if not company:
            img = card.find("img", class_=re.compile(r"preview-img-logo"))
            if img and img.get("alt"):
                company = img.get("alt").strip()

        # 5. Зарплата з glyphicon-hryvnia (якщо не знайшли вище)
        if not salary:
            hryvnia_icon = card.find("span", class_=re.compile(r"glyphicon-hryvnia"))
            if hryvnia_icon:
                nxt = hryvnia_icon.find_next_sibling("span")
                if nxt:
                    salary = nxt.get_text(strip=True)

        # 6. Місто
        city = None
        marker = card.find("span", class_=re.compile(r"glyphicon-map-marker"))
        if marker:
            nxt = marker.find_next_sibling("span")
            if nxt:
                city = nxt.get_text(strip=True)

        link = urljoin(self.BASE_URL, href)

        return Vacancy(
            id=Vacancy.make_id(self.source_key, raw_id),
            raw_id=raw_id,
            source_key=self.source_key,
            country=self.country,
            city_slug=city_slug or (city or "").lower(),
            title=title,
            link=link,
            company=company,
            salary=salary,
            description=None,
        )

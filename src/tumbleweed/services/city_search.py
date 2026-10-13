"""Пошук міст у каталозі data/cities/{country}.json.

Використовується в UX, коли користувач вводить назву міста текстом.
Підтримує fuzzy-пошук по українській, російській та англійській.
"""
from __future__ import annotations

import json
import logging
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from tumbleweed.config import DATA_DIR

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class City:
    slug: str            # "kyiv"
    name: str            # "Київ"
    region: str | None   # "Київська область"
    olx_id: int | None   # city_id у OLX
    workua_id: int | None


# Популярні міста — захардкоджені ID (для швидкості)
POPULAR_CITIES = {
    "ua": {
        "kyiv":          {"name": "Київ",           "region": "Київ",              "olx": 268, "workua": 1},
        "lviv":          {"name": "Львів",          "region": "Львівська",         "olx": 273, "workua": 2},
        "odesa":         {"name": "Одеса",          "region": "Одеська",           "olx": 271, "workua": 3},
        "kharkiv":       {"name": "Харків",         "region": "Харківська",        "olx": 269, "workua": 4},
        "dnipro":        {"name": "Дніпро",         "region": "Дніпропетровська",  "olx": 270, "workua": 5},
        "zaporizhzhia":  {"name": "Запоріжжя",      "region": "Запорізька",        "olx": 272, "workua": 6},
        "vinnytsia":     {"name": "Вінниця",        "region": "Вінницька",         "olx": 274, "workua": 7},
        "ternopil":      {"name": "Тернопіль",      "region": "Тернопільська",     "olx": 285, "workua": 8},
        "ivano_frankivsk":{"name": "Івано-Франківськ","region": "Івано-Франківська","olx": 293, "workua": 9},
        "rivne":         {"name": "Рівне",          "region": "Рівненська",        "olx": 297, "workua": 10},
        "lutsk":         {"name": "Луцьк",          "region": "Волинська",         "olx": 305, "workua": 11},
        "zhytomyr":      {"name": "Житомир",        "region": "Житомирська",       "olx": 308, "workua": 12},
        "cherkasy":      {"name": "Черкаси",        "region": "Черкаська",         "olx": 311, "workua": 13},
        "poltava":       {"name": "Полтава",        "region": "Полтавська",        "olx": 314, "workua": 14},
        "chernihiv":     {"name": "Чернігів",       "region": "Чернігівська",      "olx": 317, "workua": 15},
        "sumy":          {"name": "Суми",           "region": "Сумська",           "olx": 320, "workua": 16},
        "mykolaiv":      {"name": "Миколаїв",       "region": "Миколаївська",      "olx": 323, "workua": 17},
        "kherson":       {"name": "Херсон",         "region": "Херсонська",        "olx": 326, "workua": 18},
        "kropyvnytskyi": {"name": "Кропивницький",  "region": "Кіровоградська",    "olx": 329, "workua": 19},
        "uzhhorod":      {"name": "Ужгород",        "region": "Закарпатська",      "olx": 332, "workua": 20},
        "chernivtsi":    {"name": "Чернівці",       "region": "Чернівецька",       "olx": 335, "workua": 21},
    },
    "pl": {
        "warszawa":  {"name": "Варшава",   "region": "Мазовецьке",   "olx": 17871, "workua": None},
        "krakow":    {"name": "Краків",    "region": "Малопольське", "olx": 8959,  "workua": None},
        "wroclaw":   {"name": "Вроцлав",   "region": "Нижньосілезьке", "olx": 9462, "workua": None},
        "gdansk":    {"name": "Гданськ",   "region": "Поморське",     "olx": 2853, "workua": None},
        "poznan":    {"name": "Познань",   "region": "Великопольське", "olx": 10011, "workua": None},
    },
    "ro": {
        "bucuresti": {"name": "Бухарест",  "region": "Бухарест",    "olx": 1, "workua": None},
    },
}


# ───────────────────────────────────────────────────────
# Нормалізація
# ───────────────────────────────────────────────────────

def _normalize(text: str) -> str:
    """Привести до нижнього регістру, прибрати діакритику, зайві пробіли."""
    text = text.lower().strip()
    text = unicodedata.normalize("NFKD", text)
    # Видалити діакритичні знаки
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    # Замінити схожі кириличні на латинські? Ні — залишимо як є.
    return text


# ───────────────────────────────────────────────────────
# Завантаження каталогу
# ───────────────────────────────────────────────────────

@lru_cache(maxsize=3)
def _load_cities(country: str) -> list[City]:
    """Завантажує data/cities/{country}.json один раз.

    ВАЖЛИВО: популярні міста додаються ПЕРШИМИ — щоб мали пріоритет
    з правильними olx_id. Каталог додається після, але пропускає
    ті slug, які вже є в популярних.
    """
    cities: list[City] = []
    seen_slugs: set[str] = set()

    # 1. Популярні міста ПЕРШИМИ
    popular = POPULAR_CITIES.get(country, {})
    for slug, info in popular.items():
        cities.append(City(
            slug=slug,
            name=info["name"],
            region=info.get("region"),
            olx_id=info.get("olx"),
            workua_id=info.get("workua"),
        ))
        seen_slugs.add(slug)

    # 2. Каталог з JSON
    path = DATA_DIR / "cities" / f"{country}.json"
    if path.exists():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            items = raw.get("cities") if isinstance(raw, dict) else raw
            if isinstance(items, list):
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    slug = item.get("slug") or item.get("key") or ""
                    name = item.get("name") or item.get("label") or ""
                    if not slug or not name:
                        continue
                    if slug in seen_slugs:
                        continue
                    seen_slugs.add(slug)
                    cities.append(City(
                        slug=slug,
                        name=name,
                        region=item.get("region") or item.get("state"),
                        olx_id=item.get("olx_id"),
                        workua_id=item.get("workua_id"),
                    ))
        except Exception as e:
            log.error("Помилка читання %s: %s", path, e)

    log.info("Завантажено %d міст для %s", len(cities), country)
    return cities


def get_city(country: str, slug: str) -> City | None:
    """Знайти місто за slug."""
    # Спочатку — популярні (у них є olx_id)
    popular = POPULAR_CITIES.get(country, {})
    if slug in popular:
        info = popular[slug]
        return City(
            slug=slug,
            name=info["name"],
            region=info.get("region"),
            olx_id=info.get("olx"),
            workua_id=info.get("workua"),
        )

    for c in _load_cities(country):
        if c.slug == slug:
            return c
    return None


# ───────────────────────────────────────────────────────
# Пошук
# ───────────────────────────────────────────────────────

def search_cities(
    country: str,
    query: str,
    limit: int = 3,
) -> list[City]:
    """Пошук міст за назвою (fuzzy).

    Пріоритет:
      1000 — точний збіг назви
       500 — назва починається з запиту
       300 — якесь слово в назві починається з запиту
       200 — регіон починається з запиту
    Прибираємо матчі "підрядок у назві" — занадто дозвільно.
    """
    q = _normalize(query)
    if len(q) < 2:
        return []

    cities = _load_cities(country)
    scored: list[tuple[City, int]] = []

    for c in cities:
        name_norm = _normalize(c.name)
        region_norm = _normalize(c.region or "")

        score = 0

        # 1. Точна назва
        if name_norm == q:
            score = 1000

        # 2. Назва починається з запиту
        elif name_norm.startswith(q):
            score = 500

        # 3. Якесь слово в назві починається з запиту
        #    "тернопіль" → ["тернопіль"], а "кривий ріг" → ["кривий", "ріг"]
        elif any(word.startswith(q) for word in name_norm.split()):
            score = 300

        # 4. Регіон починається з запиту
        elif region_norm and region_norm.startswith(q):
            score = 200

        else:
            # Все інше — ігноруємо (прибрали "підрядок у назві")
            continue

        # Бонус за наявність olx_id
        if c.olx_id:
            score += 10

        scored.append((c, score))

    scored.sort(key=lambda x: (-x[1], x[0].name))

    if not scored:
        return []

    top_score = scored[0][1]

    # Точний збіг або name.startswith — тільки 1 результат
    if top_score >= 500:
        # Але якщо є кілька з однаковим скором — показати всі
        same_top = [c for c, s in scored if s == top_score]
        return same_top[:limit]

    # Інші випадки — до limit
    return [c for c, _ in scored[:limit]]


def popular_cities(country: str, limit: int = 6) -> list[City]:
    """Повертає ТОП limit популярних міст."""
    popular = POPULAR_CITIES.get(country, {})
    result: list[City] = []
    for slug, info in list(popular.items())[:limit]:
        result.append(City(
            slug=slug,
            name=info["name"],
            region=info.get("region"),
            olx_id=info.get("olx"),
            workua_id=info.get("workua"),
        ))
    return result


# ───────────────────────────────────────────────────────
# Динамічний пошук city_id у OLX (для міст без olx_id)
# ───────────────────────────────────────────────────────

def find_olx_city_id(country: str, city_name: str) -> int | None:
    """Шукає city_id у OLX API за назвою міста.

    Використовується для міст, яких немає в POPULAR_CITIES.
    Довгий запит — тому викликати рідко.
    """
    import logging
    log = logging.getLogger(__name__)

    # Домени OLX
    domains = {"ua": "olx.ua", "pl": "olx.pl", "ro": "olx.ro"}
    domain = domains.get(country)
    if not domain:
        return None

    try:
        from curl_cffi import requests as cffi_requests

        url = f"https://www.{domain}/api/v1/cities/"
        r = cffi_requests.get(
            url,
            params={"query": city_name, "limit": 5},
            headers={"Accept": "application/json"},
            impersonate="chrome124",
            timeout=15,
        )
        if r.status_code != 200:
            log.warning("OLX cities API: HTTP %d", r.status_code)
            return None

        data = r.json().get("data") or []
        if not data:
            return None

        # Беремо перший результат
        first = data[0]
        return first.get("id")
    except Exception as e:
        log.warning("Не вдалось знайти city_id: %s", e)
        return None

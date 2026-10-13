"""Пошук підкатегорій за запитом користувача.

Використовується у флоу вибору професії:
  користувач обрав сферу (agro) → вводить слово «трак» → отримує 8 результатів.

Логіка оцінки (score):
  - 100 — label містить запит (наприклад, «Тракторист» містить «трак»)
  - 80  — keyword починається з запиту (наприклад, «трактор» для «трак»)
  - 60  — keyword містить запит (наприклад, «tractor driver» містить «трак»)
  - 40  — частковий збіг (усі символи запиту є в ключі)
  - 0   — немає збігу
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from tumbleweed.config import DATA_DIR

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Subcategory:
    key: str
    label: str
    keywords: list[str]
    category_key: str
    category_label: str


@lru_cache(maxsize=1)
def _load_all_subcategories() -> dict[str, list[Subcategory]]:
    """Повертає мапу: category_key → [Subcategory, ...]."""
    path = DATA_DIR / "jobs" / "professions_ua.json"
    raw = json.loads(path.read_text(encoding="utf-8"))

    result: dict[str, list[Subcategory]] = {}
    for cat in raw.get("categories", []):
        cat_key = cat["key"]
        cat_label = cat["label"]
        subs: list[Subcategory] = []
        for sub in cat.get("subcategories", []):
            subs.append(Subcategory(
                key=sub["key"],
                label=sub["label"],
                keywords=[k.lower() for k in sub.get("keywords", [])],
                category_key=cat_key,
                category_label=cat_label,
            ))
        result[cat_key] = subs

    log.info("Завантажено %d сфер, %d підкатегорій",
             len(result), sum(len(v) for v in result.values()))
    return result


def get_category_label(category_key: str) -> str:
    """Повертає людську назву сфери (наприклад, «🌾 Сільське господарство»)."""
    subs = _load_all_subcategories().get(category_key, [])
    return subs[0].category_label if subs else category_key


def get_subcategory(category_key: str, sub_key: str) -> Subcategory | None:
    """Знайти підкатегорію за ключем у межах сфери."""
    for s in _load_all_subcategories().get(category_key, []):
        if s.key == sub_key:
            return s
    return None


MIN_QUERY_LEN = 3


def _score(sub: Subcategory, query: str) -> int:
    """Обчислити релевантність підкатегорії для запиту.

    Правила:
      - label містить запит → 100
      - keyword починається з запиту → 90
      - якесь слово в label починається з запиту → 80
      - keyword містить запит як підрядок → 70 (мінімум 4 символи)
      - немає збігу → 0
    """
    q = query.lower().strip()
    if len(q) < MIN_QUERY_LEN:
        return 0

    label_lower = sub.label.lower()

    # 1. Label містить запит
    if q in label_lower:
        return 100

    # 2. Keyword починається з запиту
    for kw in sub.keywords:
        if kw.startswith(q):
            return 90

    # 3. Якесь слово в label починається з запиту (по префіксу)
    for word in label_lower.replace("/", " ").replace("(", " ").replace(")", " ").split():
        if word.startswith(q):
            return 80

    # 4. Keyword містить запит як підрядок (тільки для запитів ≥ 4 символів)
    if len(q) >= 4:
        for kw in sub.keywords:
            if q in kw:
                return 70

    return 0


def search_subcategories(
    category_key: str,
    query: str,
    limit: int = 8,
) -> list[Subcategory]:
    """Знайти підкатегорії в межах сфери за запитом.

    Args:
        category_key: ключ сфери (наприклад, "agro")
        query: слово користувача (наприклад, "трак", мін. 3 символи)
        limit: максимум результатів (8 за замовчуванням)

    Returns:
        Список підкатегорій, відсортований за релевантністю (спадання).
        Порожній, якщо запит коротший за 3 символи.
    """
    q = (query or "").strip()
    if len(q) < MIN_QUERY_LEN:
        return []

    subs = _load_all_subcategories().get(category_key, [])
    if not subs:
        return []

    scored = [(sub, _score(sub, q)) for sub in subs]
    scored = [(s, sc) for s, sc in scored if sc > 0]
    scored.sort(key=lambda x: (-x[1], x[0].label))
    return [s for s, _ in scored[:limit]]

def all_subcategories(category_key: str) -> list[Subcategory]:
    """Повертає всі підкатегорії сфери (для випадку «Будь-яка» не потрібен)."""
    return list(_load_all_subcategories().get(category_key, []))

"""Переклад назв вакансій (PL → UA) з кешем.

Основний: MyMemoryTranslator (безкоштовно, 5000 слів/день).
Fallback: GoogleTranslator (якщо MyMemory не відповідає).
"""
from __future__ import annotations

import json
import logging
import time
from functools import lru_cache

from tumbleweed.config import DATA_DIR

log = logging.getLogger(__name__)

CACHE_PATH = DATA_DIR / "jobs" / "translations_pl_uk.json"

_MIN_INTERVAL_SEC = 0.5   # пауза між запитами (MyMemory не любить спам)
_MAX_RETRIES = 2

_last_request_ts: float = 0.0


@lru_cache(maxsize=1)
def _load_cache() -> dict[str, str]:
    if not CACHE_PATH.exists():
        return {}
    try:
        return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except Exception as e:
        log.warning("translate: cache load failed: %s", e)
        return {}


def _save_cache(cache: dict[str, str]) -> None:
    try:
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        CACHE_PATH.write_text(
            json.dumps(cache, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception as e:
        log.warning("translate: cache save failed: %s", e)


def _throttle() -> None:
    global _last_request_ts
    now = time.time()
    elapsed = now - _last_request_ts
    if elapsed < _MIN_INTERVAL_SEC:
        time.sleep(_MIN_INTERVAL_SEC - elapsed)
    _last_request_ts = time.time()


def _translate_with_mymemory(text: str) -> str | None:
    """Спроба через MyMemory (безкоштовно, 5000 слів/день)."""
    try:
        from deep_translator import MyMemoryTranslator
        translator = MyMemoryTranslator(source="pl-PL", target="uk-UA")
        _throttle()
        result = translator.translate(text)
        if result and result.strip() and result.strip() != text:
            return result.strip()
    except Exception as e:
        log.warning("MyMemory(%r): %s", text[:40], e)
    return None


def _translate_with_google(text: str) -> str | None:
    """Спроба через Google (може бути 429)."""
    try:
        from deep_translator import GoogleTranslator
        translator = GoogleTranslator(source="pl", target="uk")
        _throttle()
        result = translator.translate(text)
        if result and result.strip():
            return result.strip()
    except Exception as e:
        log.warning("Google(%r): %s", text[:40], e)
    return None


def translate_pl_to_uk(text: str) -> str:
    """Перекласти PL → UA.

    Порядок:
      1. Кеш (миттєво)
      2. MyMemory (основний)
      3. Google (fallback)
      4. Оригінал (якщо все впало)
    """
    if not text or not text.strip():
        return text

    text = text.strip()
    if len(text) < 2:
        return text

    # 1. Кеш
    cache = _load_cache()
    if text in cache:
        return cache[text]

    # 2. MyMemory
    result = _translate_with_mymemory(text)

    # 3. Google (якщо MyMemory не спрацював)
    if not result:
        result = _translate_with_google(text)

    # 4. Зберегти в кеш
    if result and result != text:
        cache[text] = result
        _save_cache(cache)
        _load_cache.cache_clear()
        return result

    # 5. Fallback — оригінал
    return text


def translate_batch(texts: list[str]) -> list[str]:
    """Перекласти пакет текстів (послідовно, з паузами)."""
    if not texts:
        return []

    cache = _load_cache()
    results: list[str] = []

    for t in texts:
        if not t or not t.strip():
            results.append(t)
            continue
        t = t.strip()
        if t in cache:
            results.append(cache[t])
        else:
            results.append(translate_pl_to_uk(t))

    return results

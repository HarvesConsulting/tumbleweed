"""Переклад назв вакансій (PL/RO → UA) з кешем.

Основний: MyMemoryTranslator (безкоштовно, 5000 слів/день).
Fallback: GoogleTranslator (якщо MyMemory не відповідає).
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from functools import lru_cache

from tumbleweed.config import DATA_DIR

log = logging.getLogger(__name__)

_MIN_INTERVAL_SEC = 0.5
_MAX_RETRIES = 2

_last_request_ts: float = 0.0


def _cache_path(source: str, target: str) -> Path:
    return DATA_DIR / "jobs" / f"translations_{source}_{target}.json"


@lru_cache(maxsize=4)
def _load_cache(source: str, target: str) -> dict[str, str]:
    path = _cache_path(source, target)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        log.warning("translate: cache load failed (%s→%s): %s", source, target, e)
        return {}


def _save_cache(cache: dict[str, str], source: str, target: str) -> None:
    path = _cache_path(source, target)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(cache, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception as e:
        log.warning("translate: cache save failed (%s→%s): %s", source, target, e)


def _throttle() -> None:
    global _last_request_ts
    now = time.time()
    elapsed = now - _last_request_ts
    if elapsed < _MIN_INTERVAL_SEC:
        time.sleep(_MIN_INTERVAL_SEC - elapsed)
    _last_request_ts = time.time()


def _translate_with_mymemory(text: str, source: str, target: str) -> str | None:
    """MyMemory (безкоштовно, 5000 слів/день)."""
    try:
        from deep_translator import MyMemoryTranslator
        
        # MyMemory потребує повних кодів
        LANG_CODES = {
            "pl": "pl-PL",
            "ro": "ro-RO",
            "uk": "uk-UA",
            "en": "en-GB",
            "ru": "ru-RU",
            "pt": "pt-PT",
        }
        src = LANG_CODES.get(source, f"{source}-{source.upper()}")
        tgt = LANG_CODES.get(target, f"{target}-{target.upper()}")
        
        translator = MyMemoryTranslator(source=src, target=tgt)
        _throttle()
        result = translator.translate(text)
        if result and result.strip() and result.strip() != text:
            return result.strip()
    except Exception as e:
        log.warning("MyMemory(%s→%s, %r): %s", source, target, text[:40], e)
    return None


def _translate_with_google(text: str, source: str, target: str) -> str | None:
    """Google Translate (може бути 429)."""
    try:
        from deep_translator import GoogleTranslator
        translator = GoogleTranslator(source=source, target=target)
        _throttle()
        result = translator.translate(text)
        if result and result.strip():
            return result.strip()
    except Exception as e:
        log.warning("Google(%s→%s, %r): %s", source, target, text[:40], e)
    return None


def _translate(text: str, source: str, target: str = "uk") -> str:
    """Універсальний переклад."""
    if not text or not text.strip():
        return text

    text = text.strip()
    if len(text) < 2:
        return text

    # 1. Кеш
    cache = _load_cache(source, target)
    if text in cache:
        return cache[text]

    # 2. MyMemory
    result = _translate_with_mymemory(text, source, target)

    # 3. Google (fallback)
    if not result:
        result = _translate_with_google(text, source, target)

    # 4. Зберегти
    if result and result != text:
        cache[text] = result
        _save_cache(cache, source, target)
        _load_cache.cache_clear()
        return result

    # 5. Fallback — оригінал
    return text


def translate_pl_to_uk(text: str) -> str:
    """PL → UA."""
    return _translate(text, source="pl", target="uk")


def translate_ro_to_uk(text: str) -> str:
    """RO → UA."""
    return _translate(text, source="ro", target="uk")


def translate_pt_to_uk(text: str) -> str:
    """PT → UA."""
    return _translate(text, source="pt", target="uk")


def translate_batch(texts: list[str], source: str = "pl") -> list[str]:
    """Перекласти пакет текстів."""
    if not texts:
        return []

    cache = _load_cache(source, "uk")
    results: list[str] = []

    for t in texts:
        if not t or not t.strip():
            results.append(t)
            continue
        t = t.strip()
        if t in cache:
            results.append(cache[t])
        else:
            results.append(_translate(t, source=source))

    return results

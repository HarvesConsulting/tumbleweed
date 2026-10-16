"""Нормалізація та стемінг тексту для матчингу вакансій.

Підтримка: українська, російська, польська, англійська.
Без зовнішніх залежностей — швидко і достатньо для ~500 вакансій/цикл.

Приклади:
    >>> normalize("Python-розробник (Senior)  C++")
    'python-розробник senior c++'
    >>> has_word("водій навантажувача", "водій")
    True
    >>> has_word("водійське посвідчення", "водій")
    False
    >>> stem("вчителів") == stem("вчитель")
    True
"""
from __future__ import annotations

import re
import unicodedata

# ─────────────────────────────────────────────────────────
# 1. Базова нормалізація
# ─────────────────────────────────────────────────────────

_WS_RE = re.compile(r"\s+")

# Дозволяємо: літери (усі Unicode), цифри, пробіл,
# а також . + # - _ для c++, c#, .net, node.js, full-stack, ui-ux
# ВАЖЛИВО: `/` НЕ в списку → стає пробілом (ui/ux → ui ux)
_CLEAN_RE = re.compile(r"[^\w\s\.\+#\-_]", re.UNICODE)


def normalize(text: str) -> str:
    """Приводить текст до канонічного вигляду для пошуку.

    - NFKC (І → І, ﬁ → fi, № → No)
    - lowercase
    - прибирає пунктуацію (крім . + # - _), / замінює на пробіл
    - стискає пробіли
    """
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", text)
    text = text.lower()
    text = _CLEAN_RE.sub(" ", text)
    text = _WS_RE.sub(" ", text).strip()
    return text


# ─────────────────────────────────────────────────────────
# 2. Стемінг (спрощений, швидкий)
# ─────────────────────────────────────────────────────────

# Порядок ВАЖЛИВИЙ: довші суфікси першими, інакше зріжемо зайве.
# "ь" і "й" в самому кінці — вони найкоротші, ріжемо їх останніми,
# щоб не зламати слова типу "сталь" → "стал" (ок) або "край" → "кра" (ок).
_UK_RU_SUFFIXES: tuple[str, ...] = (
    # дієприкметники/іменники (довгі)
    "уваннями", "юваннями", "ування", "ювання",
    "анням", "енням", "ання", "ення", "іння", "иття", "уття",
    # прикметники
    "ість", "ості", "істю", "остю",
    "ський", "цький", "зький",
    "овий", "евий", "євий", "ний", "ній",
    # множина
    "ами", "ями", "ові", "еві", "єві",
    "ів", "їв", "ей", "ій",
    "ам", "ям", "ах", "ях",
    "ом", "ем", "єм",
    # однина
    "ий", "ій", "ого", "ому", "ої",
    "ти", "ть", "ся", "сь",
    "и", "і", "а", "я", "у", "ю", "е", "о",
    # м'який знак / йот — ПІСЛЯ односкладових
    "ь", "й",
)

_EN_SUFFIXES: tuple[str, ...] = (
    "ization", "isation", "ations",
    "ingly", "fully",
    "tion", "sion", "ment", "ness", "ship", "ance", "ence",
    "ers", "ing", "ied", "ies",
    "er", "ed", "es", "s",
)

_UK_RU_CHARS_RE = re.compile(r"[іїєґыэёъ]", re.IGNORECASE)
_LATIN_RE = re.compile(r"^[a-z0-9\.\+\#\-_]+$")


def _stem_one(word: str) -> str:
    """Стемінг одного слова. Не чіпає короткі слова (<4) і технічні терміни."""
    if len(word) < 4:
        return word

    # Технічні терміни (c++, c#, .net, node.js, ui-ux) — не стемімо
    if any(c in word for c in ".+#/"):
        return word

    # Кирилиця (укр/рос)
    if _UK_RU_CHARS_RE.search(word) or re.search(r"[а-яА-Я]", word):
        for suf in _UK_RU_SUFFIXES:
            if word.endswith(suf) and len(word) - len(suf) >= 4:
                return word[: -len(suf)]
        return word

    # Латиниця (англ)
    if _LATIN_RE.match(word):
        for suf in _EN_SUFFIXES:
            if word.endswith(suf) and len(word) - len(suf) >= 4:
                return word[: -len(suf)]
        return word

    return word


def stem(text: str) -> str:
    """Стемінг усього тексту: спочатку normalize, потім кожне слово."""
    return " ".join(_stem_one(w) for w in normalize(text).split())


# ─────────────────────────────────────────────────────────
# 3. Пошук слова з межею
# ─────────────────────────────────────────────────────────

# Межа слова: перед/після needle не має бути \w (літера/цифра/_).
_BOUNDARY_BEFORE = r"(?<![\w])"
_BOUNDARY_AFTER = r"(?![\w])"

# Мінімальна довжина needle, для якої дозволяємо префікс-матч.
# Це компроміс: агроном(7) → агрономія ✅, але водій(5) → водійське ❌
_PREFIX_MATCH_MIN_LEN = 6


def has_word(haystack: str, needle: str) -> bool:
    """Чи є needle у haystack як ОКРЕМЕ слово (або як префікс для довгих термінів).

    Обидва аргументи нормалізуються всередині.

    >>> has_word("Senior Python Developer", "python")
    True
    >>> has_word("JavaScript", "java")
    False
    >>> has_word("водій навантажувача", "водій")
    True
    >>> has_word("Агрономія та рослинництво", "агроном")
    True
    """
    if not haystack or not needle:
        return False
    h = normalize(haystack)
    n = normalize(needle)
    if not n:
        return False

    # 1) Точний збіг з межами
    if re.search(rf"{_BOUNDARY_BEFORE}{re.escape(n)}{_BOUNDARY_AFTER}", h):
        return True

    # 2) Префікс-збіг для довгих термінів
    if len(n) >= _PREFIX_MATCH_MIN_LEN:
        if re.search(rf"{_BOUNDARY_BEFORE}{re.escape(n)}\w*", h):
            return True

    return False


def has_any_word(haystack: str, needles: list[str]) -> bool:
    """Чи є ХОЧ ОДНЕ з needles у haystack як окреме слово."""
    return any(has_word(haystack, n) for n in needles)


def has_all_words(haystack: str, needles: list[str]) -> bool:
    """Чи є ВСІ needles у haystack як окремі слова."""
    return all(has_word(haystack, n) for n in needles)


# ─────────────────────────────────────────────────────────
# 4. Допоміжне: токенізація
# ─────────────────────────────────────────────────────────

def tokenize(text: str) -> list[str]:
    """Розбиває на нормалізовані токени."""
    return normalize(text).split()


def stem_tokens(text: str) -> list[str]:
    """Токени зі стемінгом."""
    return [_stem_one(t) for t in tokenize(text)]

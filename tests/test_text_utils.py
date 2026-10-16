"""Тести для services.text_utils — нормалізація, стемінг, пошук слів."""
from __future__ import annotations

import pytest

from tumbleweed.services.text_utils import (
    has_all_words,
    has_any_word,
    has_word,
    normalize,
    stem,
    stem_tokens,
    tokenize,
)


# ─────────────────────────────────────────────────────────
# normalize
# ─────────────────────────────────────────────────────────

class TestNormalize:
    def test_empty(self):
        assert normalize("") == ""
        assert normalize(None) == ""  # type: ignore[arg-type]

    def test_lowercase(self):
        assert normalize("Python DEVELOPER") == "python developer"

    def test_unicode_nfkc(self):
        # ﬁ (ligature) → fi, № → No
        assert normalize("ﬁle") == "file"
        assert normalize("№1") == "no1"

    def test_ukrainian_letters(self):
        # І (U+0406) → і (U+0456) після lowercase
        assert normalize("Водій") == "водій"
        assert normalize("Їхати") == "їхати"
        assert normalize("ЄДНІСТЬ") == "єдність"

    def test_preserves_tech_symbols(self):
        # c++, c#, .net, node.js, full-stack — мають зберегтись
        # ВАЖЛИВО: / НЕ зберігається — замінюється на пробіл
        assert normalize("C++ Developer") == "c++ developer"
        assert normalize("C# / .NET") == "c# .net"
        assert normalize("Node.js") == "node.js"
        assert normalize("UI/UX дизайнер") == "ui ux дизайнер"
        assert normalize("Full-stack") == "full-stack"

    def test_strips_punctuation(self):
        assert normalize("Python, Django!") == "python django"
        assert normalize("(Senior)") == "senior"

    def test_collapses_whitespace(self):
        assert normalize("Python   \n\t  Developer") == "python developer"


# ─────────────────────────────────────────────────────────
# has_word — межа слова
# ─────────────────────────────────────────────────────────

class TestHasWord:
    def test_exact_word(self):
        assert has_word("Python Developer", "python") is True
        assert has_word("Python Developer", "developer") is True

    def test_substring_not_match(self):
        # java НЕ має матчитись у javascript
        assert has_word("JavaScript", "java") is False
        # qa НЕ має матчитись у qatar
        assert has_word("Qatar", "qa") is False

    def test_case_insensitive(self):
        assert has_word("PYTHON", "python") is True
        assert has_word("python", "PYTHON") is True

    def test_ukrainian(self):
        assert has_word("Водій категорії B", "водій") is True
        assert has_word("Водійське посвідчення", "водій") is False
        assert has_word("Вчитель математики", "вчитель") is True

    def test_phrase(self):
        assert has_word("Водій категорії B", "водій категорії b") is True
        assert has_word("Водій B", "водій категорії b") is False

    def test_empty(self):
        assert has_word("", "python") is False
        assert has_word("python", "") is False

    def test_punctuation_boundary(self):
        # "python," — кома є межею
        assert has_word("Python, Django", "python") is True
        assert has_word("Python-Django", "python") is True

    def test_prefix_match_long_term(self):
        # Довгі терміни (≥6) матчаться як префікс
        assert has_word("Агрономія та рослинництво", "агроном") is True
        assert has_word("Python-розробник", "python") is True
        # Короткі (<6) — тільки точний збіг
        assert has_word("Водійське посвідчення", "водій") is False


# ─────────────────────────────────────────────────────────
# stem
# ─────────────────────────────────────────────────────────

class TestStem:
    def test_ukrainian_noun_cases(self):
        # всі форми мають дати однаковий корінь
        assert stem("вчитель") == stem("вчителя")
        assert stem("вчитель") == stem("вчителів")
        assert stem("вчитель") == stem("вчителями")

    def test_ukrainian_водій(self):
        assert stem("водій") == stem("водія")
        assert stem("водій") == stem("водієм")

    def test_russian(self):
        assert stem("водитель") == stem("водителя")

    def test_english(self):
        assert stem("developer") == stem("developers")
        assert stem("managing") == stem("manage") or stem("managing").startswith("manag")

    def test_short_words_untouched(self):
        # <4 символів — не чіпаємо
        assert stem("qa") == "qa"
        assert stem("ios") == "ios"

    def test_tech_terms_preserved(self):
        assert "c++" in stem("C++ developer")
        assert "c#" in stem("C# developer")
        assert "node.js" in stem("Node.js developer")
        assert ".net" in stem(".NET developer")

    def test_empty(self):
        assert stem("") == ""


# ─────────────────────────────────────────────────────────
# tokenize / stem_tokens
# ─────────────────────────────────────────────────────────

class TestTokenize:
    def test_simple(self):
        assert tokenize("Python Developer") == ["python", "developer"]

    def test_with_punctuation(self):
        assert tokenize("Python, Django!") == ["python", "django"]

    def test_stem_tokens(self):
        result = stem_tokens("вчителів математики")
        assert result[0].startswith("вчител")
        assert result[1].startswith("математ")


# ─────────────────────────────────────────────────────────
# has_any_word / has_all_words
# ─────────────────────────────────────────────────────────

class TestAnyAll:
    def test_has_any(self):
        assert has_any_word("Python Developer", ["java", "python"]) is True
        assert has_any_word("Java Developer", ["java", "python"]) is True
        assert has_any_word("Ruby Developer", ["java", "python"]) is False

    def test_has_all(self):
        assert has_all_words("Python Django Developer", ["python", "django"]) is True
        assert has_all_words("Python Developer", ["python", "django"]) is False

    def test_empty_lists(self):
        assert has_any_word("Python", []) is False
        assert has_all_words("Python", []) is True  # vacuous truth


# ─────────────────────────────────────────────────────────
# Реальні кейси з вакансій
# ─────────────────────────────────────────────────────────

class TestRealVacancies:
    @pytest.mark.parametrize("title,needle,expected", [
        ("Водій категорії B", "водій", True),
        ("Водій навантажувача", "водій", True),
        ("Водійське посвідчення", "водій", False),
        ("Кур'єр на авто", "кур'єр", True),
        ("Курьер (доставка)", "курьер", True),
        ("Python Developer", "python", True),
        ("JavaScript розробник", "java", False),
        ("Senior Java Engineer", "java", True),
        ("Агроном", "агроном", True),
        ("Агрономія та рослинництво", "агроном", True),
        ("Менеджер з продажу агротехніки", "агроном", False),
        ("QA Automation Engineer", "qa", True),
        ("Qatar Airways", "qa", False),
        ("Вчитель математики", "вчитель", True),
        ("Репетитор англійської", "репетитор", True),
    ])
    def test_title_match(self, title, needle, expected):
        assert has_word(title, needle) is expected

    @pytest.mark.parametrize("a,b", [
        ("вчитель", "вчителів"),
        ("вчитель", "вчителя"),
        ("водій", "водія"),
        ("кухар", "кухарі"),
        ("лікар", "лікарі"),
        ("медсестра", "медсестри"),
    ])
    def test_ukrainian_stemming_pairs(self, a, b):
        assert stem(a) == stem(b), f"{a!r} і {b!r} мають дати однаковий стем"

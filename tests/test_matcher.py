"""Тести для services.matcher — матчинг назв вакансій по підкатегоріях."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from tumbleweed.services import matcher
from tumbleweed.services.matcher import (
    _job_type_matches,
    _load_subcategories,
    _title_matches_professions,
)


# ─────────────────────────────────────────────────────────
# Хелпер: розпаковує tuple (bool, score) → bool
# ─────────────────────────────────────────────────────────

def _matches(title: str, professions: list[str], country: str = "ua") -> bool:
    """Хелпер: розпаковує tuple і повертає bool."""
    ok, _ = _title_matches_professions(title, professions, country)
    return ok


# ─────────────────────────────────────────────────────────
# Фікстура: підсовуємо фейковий JSON, щоб не залежати від data/
# ─────────────────────────────────────────────────────────

FAKE_JSON = {
    "categories": [
        {
            "key": "it",
            "label": "IT",
            "subcategories": [
                {"key": "it_backend", "label": "Backend", "keywords": ["python", "django", "java"]},
                {"key": "it_frontend", "label": "Frontend", "keywords": ["javascript", "react", "vue"]},
                {"key": "it_qa", "label": "QA", "keywords": ["qa", "tester", "тестувальник"]},
            ],
        },
        {
            "key": "driver",
            "label": "Водій",
            "subcategories": [
                {"key": "driver_b", "label": "Кат. B", "keywords": ["водій b", "категорії b"]},
                {"key": "driver_courier", "label": "Кур'єр", "keywords": ["кур'єр", "courier"]},
            ],
        },
        {
            "key": "agro",
            "label": "Агро",
            "subcategories": [
                {"key": "agro_agronom", "label": "Агроном", "keywords": ["агроном", "agronomist"]},
                {"key": "agro_tractor", "label": "Тракторист", "keywords": ["тракторист", "tractor"]},
            ],
        },
    ]
}


@pytest.fixture(autouse=True)
def fake_data_dir(monkeypatch, tmp_path: Path):
    """Підмінюємо DATA_DIR/jobs/professions_ua.json на фейковий."""
    jobs_dir = tmp_path / "jobs"
    jobs_dir.mkdir(parents=True, exist_ok=True)
    (jobs_dir / "professions_ua.json").write_text(
        json.dumps(FAKE_JSON, ensure_ascii=False),
        encoding="utf-8",
    )

    monkeypatch.setattr(matcher, "DATA_DIR", tmp_path)
    # lru_cache очищаємо між тестами
    matcher._load_subcategories.cache_clear()
    yield
    matcher._load_subcategories.cache_clear()


# ─────────────────────────────────────────────────────────
# _load_subcategories
# ─────────────────────────────────────────────────────────

class TestLoadSubcategories:
    def test_returns_all_keys(self):
        subs = _load_subcategories("ua")
        assert set(subs.keys()) == {
            "it_backend", "it_frontend", "it_qa",
            "driver_b", "driver_courier",
            "agro_agronom", "agro_tractor",
        }

    def test_keywords_are_normalized(self):
        subs = _load_subcategories("ua")
        # всі keywords мають бути lowercase і без зайвих пробілів
        for sub in subs.values():
            for kw in sub.keywords:
                assert kw == kw.lower()
                assert kw == kw.strip()

    def test_missing_file_returns_empty(self, monkeypatch, tmp_path):
        # якщо файлу немає — порожня мапа
        monkeypatch.setattr(matcher, "DATA_DIR", tmp_path)
        matcher._load_subcategories.cache_clear()
        subs = _load_subcategories("xx")   # країни "xx" нема
        assert subs == {}


# ─────────────────────────────────────────────────────────
# _title_matches_professions
# ─────────────────────────────────────────────────────────

class TestTitleMatches:
    def test_no_professions_returns_true(self):
        assert _matches("anything", [], "ua") is True

    def test_empty_title_returns_false(self):
        assert _matches("", ["it_backend"], "ua") is False
        assert _matches("   ", ["it_backend"], "ua") is False

    def test_simple_match(self):
        assert _matches("Python Developer", ["it_backend"], "ua") is True

    def test_case_insensitive(self):
        assert _matches("PYTHON DEVELOPER", ["it_backend"], "ua") is True

    def test_ukrainian_match(self):
        assert _matches("Водій категорії B", ["driver_b"], "ua") is True

    def test_no_match(self):
        assert _matches("Python Developer", ["driver_b"], "ua") is False

    def test_multiple_professions_any_match(self):
        assert _matches("Python Developer", ["driver_b", "it_backend"], "ua") is True

    def test_unknown_profession_skipped(self):
        # ключ якого немає в JSON — пропускаємо без помилки
        assert _matches("Python", ["unknown_key"], "ua") is False

    def test_custom_profession(self):
        assert _matches("Слюсар-механік", ["custom:слюсар"], "ua") is True

    def test_custom_profession_no_match(self):
        assert _matches("Python Developer", ["custom:слюсар"], "ua") is False

    # ── Кейси, які ламали старий матчер (підрядок) ──

    def test_qa_not_in_qatar(self):
        # "qa" не має матчитись у "qatar"
        assert _matches("Qatar Airways", ["it_qa"], "ua") is False

    def test_qa_in_qa_engineer(self):
        assert _matches("QA Engineer", ["it_qa"], "ua") is True

    def test_java_not_in_javascript(self):
        # "java" не має матчитись у "javascript"
        assert _matches("JavaScript Developer", ["it_backend"], "ua") is False

    def test_agronom_matches_agronomiya(self):
        # префікс-матч для довгих термінів
        assert _matches("Агрономія", ["agro_agronom"], "ua") is True

    def test_vodiy_not_in_vodiyske(self):
        # "водій" (5) не має матчити "водійське" (префікс-порог 6)
        assert _matches("Водійське посвідчення", ["driver_b"], "ua") is False


# ─────────────────────────────────────────────────────────
# _job_type_matches
# ─────────────────────────────────────────────────────────

class TestJobTypeMatches:
    def test_no_wanted_returns_true(self):
        assert _job_type_matches("whatever", []) is True

    def test_none_job_type_returns_true(self):
        # OLX часто не вказує тип — не блокуємо
        assert _job_type_matches(None, ["full"]) is True

    def test_full_match_ukrainian(self):
        assert _job_type_matches("Повна зайнятість", ["full"]) is True

    def test_full_match_english(self):
        assert _job_type_matches("Full-time", ["full"]) is True

    def test_full_match_polish(self):
        assert _job_type_matches("Pełny etat", ["full"]) is True

    def test_remote_match(self):
        assert _job_type_matches("Віддалена робота", ["remote"]) is True
        assert _job_type_matches("Zdalna", ["remote"]) is True
        assert _job_type_matches("Remote", ["remote"]) is True

    def test_part_match(self):
        assert _job_type_matches("Часткова зайнятість", ["part"]) is True

    def test_no_match(self):
        assert _job_type_matches("Повна зайнятість", ["remote"]) is False

    def test_any_of_multiple_matches(self):
        assert _job_type_matches("Повна зайнятість", ["remote", "full"]) is True

    def test_substring_fallback(self):
        # невідомий тип — матчиться як підрядок
        assert _job_type_matches("Стажування", ["стажування"]) is True

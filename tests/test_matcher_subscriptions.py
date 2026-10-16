"""Тести для матчингу по підписках (baseline vs new)."""
from __future__ import annotations

import json
import sqlite3

import pytest

from tumbleweed.db import queries_jobs
from tumbleweed.db.queries_jobs import (
    Subscription,
    add_subscription,
)
from tumbleweed.db.schema import SCHEMA_SQL
from tumbleweed.services import matcher


# ─────────────────────────────────────────────────────────
# SQLite in-memory клієнт
# ─────────────────────────────────────────────────────────

class SQLiteClient:
    """Обгортка над sqlite3 з тим самим API, що TursoClient.

    Виконує РЕАЛЬНИЙ SQL — надійніше за FakeClient.
    """

    def __init__(self) -> None:
        self.conn = sqlite3.connect(":memory:")
        self.conn.execute("PRAGMA foreign_keys = ON")

    def execute(self, sql: str, params: list | None = None) -> list[list]:
        cur = self.conn.execute(sql, params or [])
        return [list(row) for row in cur.fetchall()]

    def execute_non_query(self, sql: str, params: list | None = None) -> int:
        cur = self.conn.execute(sql, params or [])
        self.conn.commit()
        return cur.rowcount


@pytest.fixture
def client() -> SQLiteClient:
    c = SQLiteClient()
    for sql in SCHEMA_SQL:
        c.execute_non_query(sql)
    return c


# ─────────────────────────────────────────────────────────
# Фейковий JSON з підкатегоріями
# ─────────────────────────────────────────────────────────

FAKE_JSON = {
    "categories": [
        {
            "key": "it",
            "label": "IT",
            "subcategories": [
                {"key": "it_backend", "label": "Backend",
                 "keywords": ["python", "django"]},
            ],
        },
        {
            "key": "driver",
            "label": "Водій",
            "subcategories": [
                {"key": "driver_b", "label": "Кат. B",
                 "keywords": ["водій категорії b", "категорії b"]},
                {"key": "driver_courier", "label": "Кур'єр",
                 "keywords": ["кур'єр", "courier"]},
            ],
        },
    ]
}


@pytest.fixture(autouse=True)
def fake_data_dir(monkeypatch, tmp_path):
    jobs_dir = tmp_path / "jobs"
    jobs_dir.mkdir(parents=True, exist_ok=True)
    (jobs_dir / "professions_ua.json").write_text(
        json.dumps(FAKE_JSON, ensure_ascii=False),
        encoding="utf-8",
    )
    monkeypatch.setattr(matcher, "DATA_DIR", tmp_path)
    matcher._load_subcategories.cache_clear()
    yield
    matcher._load_subcategories.cache_clear()


# ─────────────────────────────────────────────────────────
# Хелпери для наповнення БД
# ─────────────────────────────────────────────────────────

def insert_vacancy(
    client: SQLiteClient,
    *,
    vid: str,
    title: str,
    source_key: str = "olx_ua",
    city_slug: str = "kyiv",
    country: str = "ua",
    job_type: str | None = None,
    created_at: str = "2026-10-17 10:00:00",
    saved_at: str = "2026-10-17 10:00:00",
) -> None:
    client.execute_non_query(
        """
        INSERT INTO vacancies
            (id, raw_id, source_key, country, city_slug, title,
             job_type, link, created_at, saved_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [vid, vid, source_key, country, city_slug, title,
         job_type, f"http://x/{vid}", created_at, saved_at],
    )


def make_sub(
    client: SQLiteClient,
    *,
    chat_id: str = "chat1",
    country: str = "ua",
    city_slug: str = "kyiv",
    profession_key: str = "it_backend",
    job_types: list[str] | None = None,
    baseline_done: bool = False,
    last_parsed_at: str | None = None,
) -> Subscription:
    sub = add_subscription(
        client, chat_id, country, city_slug, profession_key,
        job_types=job_types or [],
    )
    assert sub is not None
    if baseline_done:
        client.execute_non_query(
            """
            UPDATE user_subscriptions
            SET baseline_done = 1, last_parsed_at = ?
            WHERE id = ?
            """,
            [last_parsed_at or "2026-10-17 09:00:00", sub.id],
        )
    # читаємо назад
    from tumbleweed.db.queries_jobs import get_subscription
    return get_subscription(client, sub.id)   # type: ignore[return-value]


# ─────────────────────────────────────────────────────────
# Baseline
# ─────────────────────────────────────────────────────────

class TestBaseline:
    def test_picks_top_5_per_source(self, client):
        # OLX: 7 вакансій, мають взяти 5 (найновіші)
        for i in range(7):
            insert_vacancy(
                client,
                vid=f"olx_{i}",
                title=f"Python Developer {i}",
                source_key="olx_ua",
                created_at=f"2026-10-17 10:0{i}:00",
                saved_at=f"2026-10-17 10:0{i}:00",
            )
        # Robota: 3 вакансії
        for i in range(3):
            insert_vacancy(
                client,
                vid=f"robota_{i}",
                title=f"Python Developer R{i}",
                source_key="robota_ua",
                created_at=f"2026-10-17 11:0{i}:00",
                saved_at=f"2026-10-17 11:0{i}:00",
            )

        sub = make_sub(client, profession_key="it_backend")
        result = matcher.find_vacancies_for_subscription(client, sub)
        assert len(result) == 5 + 3

    def test_respects_profession(self, client):
        insert_vacancy(client, vid="v1", title="Python Developer")
        insert_vacancy(client, vid="v2", title="Кур'єр на авто")
        sub = make_sub(client, profession_key="it_backend")
        result = matcher.find_vacancies_for_subscription(client, sub)
        assert len(result) == 1
        assert result[0]["id"] == "v1"

    def test_filters_by_city(self, client):
        insert_vacancy(client, vid="v1", title="Python Developer", city_slug="kyiv")
        insert_vacancy(client, vid="v2", title="Python Developer", city_slug="lviv")
        sub = make_sub(client, city_slug="kyiv", profession_key="it_backend")
        result = matcher.find_vacancies_for_subscription(client, sub)
        assert len(result) == 1

    def test_excludes_already_sent(self, client):
        insert_vacancy(client, vid="v1", title="Python Developer")
        insert_vacancy(client, vid="v2", title="Python Developer")
        # v1 вже надіслано
        client.execute_non_query(
            "INSERT INTO user_seen_vacancies (chat_id, vacancy_id) VALUES (?, ?)",
            ["chat1", "v1"],
        )
        sub = make_sub(client, profession_key="it_backend")
        result = matcher.find_vacancies_for_subscription(client, sub)
        assert len(result) == 1
        assert result[0]["id"] == "v2"

    def test_profession_empty_matches_all(self, client):
        insert_vacancy(client, vid="v1", title="Python Developer")
        insert_vacancy(client, vid="v2", title="Кур'єр на авто")
        insert_vacancy(client, vid="v3", title="Водій категорії B")
        sub = make_sub(client, profession_key="")
        result = matcher.find_vacancies_for_subscription(client, sub)
        assert len(result) == 3

    def test_job_type_filter(self, client):
        insert_vacancy(client, vid="v1", title="Python Developer", job_type="Full-time")
        insert_vacancy(client, vid="v2", title="Python Developer", job_type="Part-time")
        sub = make_sub(
            client, profession_key="it_backend", job_types=["full"],
        )
        result = matcher.find_vacancies_for_subscription(client, sub)
        assert len(result) == 1
        assert result[0]["id"] == "v1"


# ─────────────────────────────────────────────────────────
# New (після baseline)
# ─────────────────────────────────────────────────────────

class TestNew:
    def test_only_since_last_parsed(self, client):
        # стара вакансія (до last_parsed_at)
        insert_vacancy(
            client, vid="old", title="Python Developer",
            saved_at="2026-10-17 08:00:00",
        )
        # нова (після)
        insert_vacancy(
            client, vid="new", title="Python Developer",
            saved_at="2026-10-17 11:00:00",
        )
        sub = make_sub(
            client, profession_key="it_backend",
            baseline_done=True, last_parsed_at="2026-10-17 09:00:00",
        )
        result = matcher.find_vacancies_for_subscription(client, sub)
        assert len(result) == 1
        assert result[0]["id"] == "new"

    def test_returns_all_new(self, client):
        # 15 нових — маємо отримати всі 15 (без ліміту)
        for i in range(15):
            insert_vacancy(
                client, vid=f"v{i}", title=f"Python Developer {i}",
                saved_at=f"2026-10-17 11:{i:02d}:00",
            )
        sub = make_sub(
            client, profession_key="it_backend",
            baseline_done=True, last_parsed_at="2026-10-17 09:00:00",
        )
        result = matcher.find_vacancies_for_subscription(client, sub)
        assert len(result) == 15

    def test_no_baseline_flag_no_new(self, client):
        # baseline_done=0 — не має викликати _new_vacancies
        # (перевіряємо, що гілка вибирається правильно через last_parsed_at)
        insert_vacancy(
            client, vid="v1", title="Python Developer",
            saved_at="2026-10-17 11:00:00",
        )
        sub = make_sub(client, profession_key="it_backend", baseline_done=False)
        # baseline — має знайти
        result = matcher.find_vacancies_for_subscription(client, sub)
        assert len(result) == 1

    def test_no_last_parsed_at_returns_empty(self, client):
        insert_vacancy(client, vid="v1", title="Python Developer")
        sub = make_sub(
            client, profession_key="it_backend",
            baseline_done=True, last_parsed_at=None,
        )
        # Хак: baseline_done=1, але last_parsed_at=None → _new_vacancies поверне []
        sub = Subscription(
            id=sub.id, chat_id=sub.chat_id, country=sub.country,
            city_slug=sub.city_slug, profession_key=sub.profession_key,
            job_types=sub.job_types, experience=sub.experience,
            enabled=True, baseline_done=True,
            last_parsed_at=None, created_at=sub.created_at,
        )
        result = matcher.find_vacancies_for_subscription(client, sub)
        assert result == []


# ─────────────────────────────────────────────────────────
# find_matches_for_all_subscriptions
# ─────────────────────────────────────────────────────────

class TestAllSubscriptions:
    def test_empty(self, client):
        assert matcher.find_matches_for_all_subscriptions(client, []) == []

    def test_multiple_subscriptions(self, client):
        insert_vacancy(client, vid="v1", title="Python Developer", city_slug="kyiv")
        insert_vacancy(client, vid="v2", title="Кур'єр", city_slug="lviv")

        sub_kyiv = make_sub(
            client, chat_id="chat1", city_slug="kyiv",
            profession_key="it_backend",
        )
        sub_lviv = make_sub(
            client, chat_id="chat1", city_slug="lviv",
            profession_key="driver_courier",
        )

        results = matcher.find_matches_for_all_subscriptions(
            client, [sub_kyiv, sub_lviv],
        )
        assert len(results) == 2
        assert {s.id for s, _ in results} == {sub_kyiv.id, sub_lviv.id}

    def test_skips_empty(self, client):
        # підписка без матчів не потрапляє в результат
        sub = make_sub(client, profession_key="it_backend")
        results = matcher.find_matches_for_all_subscriptions(client, [sub])
        assert results == []

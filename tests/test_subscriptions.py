"""Тести для CRUD-функцій user_subscriptions."""
from __future__ import annotations

import json

import pytest

from tumbleweed.db import queries_jobs
from tumbleweed.db.queries_jobs import (
    Subscription,
    add_subscription,
    count_subscriptions,
    get_subscription,
    list_active_subscriptions,
    list_subscriptions,
    mark_baseline_done,
    remove_subscription,
    set_subscription_enabled,
    update_last_parsed_at,
)


# ─────────────────────────────────────────────────────────
# Фейковий клієнт (in-memory)
# ─────────────────────────────────────────────────────────

class FakeClient:
    """Мінімальна in-memory емуляція TursoClient для тестів.

    Підтримує лише ті SQL-операції, які використовує queries_jobs.
    """

    def __init__(self) -> None:
        self.rows: list[dict] = []
        self.next_id = 1

    def execute(self, sql: str, params: list | None = None) -> list[list]:
        params = params or []
        s = " ".join(sql.split()).lower()

        if "insert or ignore into user_subscriptions" in s:
            return []

        # ── СПОЧАТКУ: COUNT (специфічний, бо містить і "select", і "from") ──
        if "select count(*)" in s and "user_subscriptions" in s:
            chat_id = params[0]
            n = sum(
                1 for r in self.rows
                if r["chat_id"] == chat_id and r["enabled"] == 1
            )
            return [[n]]

        # ── ПОТІМ: звичайний SELECT з user_subscriptions ──
        if "select" in s and "from user_subscriptions" in s:
            return self._select(sql, params)

        return []

    def execute_non_query(self, sql: str, params: list | None = None) -> int:
        params = params or []
        s = " ".join(sql.split()).lower()

        if "insert or ignore into user_subscriptions" in s:
            (chat_id, country, city_slug, profession_key,
             job_types, experience) = params
            # UNIQUE (chat_id, city_slug, profession_key)
            for r in self.rows:
                if (r["chat_id"] == chat_id
                        and r["city_slug"] == city_slug
                        and r["profession_key"] == profession_key):
                    return 0
            self.rows.append({
                "id": self.next_id,
                "chat_id": chat_id,
                "country": country,
                "city_slug": city_slug,
                "profession_key": profession_key,
                "job_types": job_types,
                "experience": experience,
                "enabled": 1,
                "baseline_done": 0,
                "last_parsed_at": None,
                "created_at": "2026-10-17 12:00:00",
            })
            self.next_id += 1
            return 1

        if "update user_subscriptions set baseline_done = 1" in s:
            if len(params) == 1:
                sub_id = params[0]
                ts = "now"
            else:
                ts, sub_id = params
            for r in self.rows:
                if r["id"] == sub_id:
                    r["baseline_done"] = 1
                    r["last_parsed_at"] = ts
            return 1

        if "update user_subscriptions set last_parsed_at" in s:
            if len(params) == 1:
                sub_id = params[0]
                ts = "now"
            else:
                ts, sub_id = params
            for r in self.rows:
                if r["id"] == sub_id:
                    r["last_parsed_at"] = ts
            return 1

        if "update user_subscriptions set enabled" in s:
            enabled, sub_id = params
            for r in self.rows:
                if r["id"] == sub_id:
                    r["enabled"] = enabled
            return 1

        if "delete from user_subscriptions" in s:
            sub_id, chat_id = params
            before = len(self.rows)
            self.rows = [
                r for r in self.rows
                if not (r["id"] == sub_id and r["chat_id"] == chat_id)
            ]
            return before - len(self.rows)

        return 0

    def _select(self, sql: str, params: list) -> list[list]:
        s = " ".join(sql.split()).lower()
        result = self.rows

        # ── СПЕЦИФІЧНІ (перевіряємо ПЕРШИМИ, бо вони — підрядки загальних) ──

        # WHERE chat_id = ? AND city_slug = ? AND profession_key = ?
        if "where chat_id = ? and city_slug = ? and profession_key = ?" in s:
            chat_id, city_slug, prof_key = params
            result = [
                r for r in result
                if (r["chat_id"] == chat_id
                    and r["city_slug"] == city_slug
                    and r["profession_key"] == prof_key)
            ]

        # WHERE enabled = 1
        elif "where enabled = 1" in s:
            result = [r for r in result if r["enabled"] == 1]

        # WHERE id = ?
        elif "where id = ?" in s:
            sub_id = params[0]
            result = [r for r in result if r["id"] == sub_id]

        # WHERE chat_id = ? [AND enabled = 1]  ← загальний, тому ОСТАННІМ
        elif "where chat_id = ?" in s:
            chat_id = params[0]
            result = [r for r in result if r["chat_id"] == chat_id]
            if "and enabled = 1" in s:
                result = [r for r in result if r["enabled"] == 1]

        result = sorted(result, key=lambda r: r["id"])

        return [
            [
                r["id"], r["chat_id"], r["country"], r["city_slug"],
                r["profession_key"], r["job_types"], r["experience"],
                r["enabled"], r["baseline_done"],
                r["last_parsed_at"], r["created_at"],
            ]
            for r in result
        ]


@pytest.fixture
def client() -> FakeClient:
    return FakeClient()


# ─────────────────────────────────────────────────────────
# add_subscription
# ─────────────────────────────────────────────────────────

class TestAddSubscription:
    def test_new_subscription(self, client):
        sub = add_subscription(client, "chat1", "ua", "kyiv", "agro_tractor")
        assert sub is not None
        assert sub.chat_id == "chat1"
        assert sub.city_slug == "kyiv"
        assert sub.profession_key == "agro_tractor"
        assert sub.enabled is True
        assert sub.baseline_done is False
        assert sub.last_parsed_at is None

    def test_empty_profession_key_means_any(self, client):
        sub = add_subscription(client, "chat1", "ua", "kyiv", "")
        assert sub is not None
        assert sub.profession_key == ""

    def test_duplicate_returns_existing(self, client):
        sub1 = add_subscription(client, "chat1", "ua", "kyiv", "agro_tractor")
        sub2 = add_subscription(client, "chat1", "ua", "kyiv", "agro_tractor")
        assert sub1 is not None and sub2 is not None
        assert sub1.id == sub2.id
        assert len(client.rows) == 1

    def test_same_city_different_profession(self, client):
        sub1 = add_subscription(client, "chat1", "ua", "kyiv", "agro_tractor")
        sub2 = add_subscription(client, "chat1", "ua", "kyiv", "agro_agronom")
        assert sub1 is not None and sub2 is not None
        assert sub1.id != sub2.id
        assert len(client.rows) == 2

    def test_same_city_any_vs_specific(self, client):
        sub1 = add_subscription(client, "chat1", "ua", "kyiv", "")
        sub2 = add_subscription(client, "chat1", "ua", "kyiv", "agro_tractor")
        assert sub1 is not None and sub2 is not None
        assert sub1.id != sub2.id

    def test_job_types_stored(self, client):
        sub = add_subscription(
            client, "chat1", "ua", "kyiv", "agro_tractor",
            job_types=["full", "remote"],
        )
        assert sub is not None
        assert sub.job_types == ["full", "remote"]


# ─────────────────────────────────────────────────────────
# list_subscriptions / list_active_subscriptions
# ─────────────────────────────────────────────────────────

class TestListSubscriptions:
    def test_empty(self, client):
        assert list_subscriptions(client, "chat1") == []

    def test_only_chat_own(self, client):
        add_subscription(client, "chat1", "ua", "kyiv", "agro_tractor")
        add_subscription(client, "chat2", "ua", "lviv", "driver_b")
        subs = list_subscriptions(client, "chat1")
        assert len(subs) == 1
        assert subs[0].chat_id == "chat1"

    def test_only_enabled(self, client):
        sub = add_subscription(client, "chat1", "ua", "kyiv", "agro_tractor")
        assert sub is not None
        set_subscription_enabled(client, sub.id, False)
        assert list_subscriptions(client, "chat1") == []

    def test_include_disabled(self, client):
        sub = add_subscription(client, "chat1", "ua", "kyiv", "agro_tractor")
        assert sub is not None
        set_subscription_enabled(client, sub.id, False)
        subs = list_subscriptions(client, "chat1", only_enabled=False)
        assert len(subs) == 1

    def test_list_active_all_chats(self, client):
        add_subscription(client, "chat1", "ua", "kyiv", "agro_tractor")
        add_subscription(client, "chat2", "ua", "lviv", "driver_b")
        subs = list_active_subscriptions(client)
        assert len(subs) == 2
        assert {s.chat_id for s in subs} == {"chat1", "chat2"}


# ─────────────────────────────────────────────────────────
# get_subscription
# ─────────────────────────────────────────────────────────

class TestGetSubscription:
    def test_found(self, client):
        created = add_subscription(client, "chat1", "ua", "kyiv", "agro_tractor")
        assert created is not None
        sub = get_subscription(client, created.id)
        assert sub is not None
        assert sub.id == created.id

    def test_not_found(self, client):
        assert get_subscription(client, 999) is None


# ─────────────────────────────────────────────────────────
# mark_baseline_done / update_last_parsed_at
# ─────────────────────────────────────────────────────────

class TestMarkBaseline:
    def test_sets_flag_and_timestamp(self, client):
        sub = add_subscription(client, "chat1", "ua", "kyiv", "agro_tractor")
        assert sub is not None
        assert sub.baseline_done is False

        mark_baseline_done(client, sub.id, "2026-10-17 12:00:00")
        sub2 = get_subscription(client, sub.id)
        assert sub2 is not None
        assert sub2.baseline_done is True
        assert sub2.last_parsed_at == "2026-10-17 12:00:00"

    def test_default_now(self, client):
        sub = add_subscription(client, "chat1", "ua", "kyiv", "agro_tractor")
        assert sub is not None
        mark_baseline_done(client, sub.id)
        sub2 = get_subscription(client, sub.id)
        assert sub2 is not None
        assert sub2.baseline_done is True
        assert sub2.last_parsed_at is not None


class TestUpdateLastParsed:
    def test_updates_timestamp_only(self, client):
        sub = add_subscription(client, "chat1", "ua", "kyiv", "agro_tractor")
        assert sub is not None
        update_last_parsed_at(client, sub.id, "2026-10-17 15:00:00")
        sub2 = get_subscription(client, sub.id)
        assert sub2 is not None
        assert sub2.last_parsed_at == "2026-10-17 15:00:00"
        # baseline_done НЕ змінюється
        assert sub2.baseline_done is False


# ─────────────────────────────────────────────────────────
# set_subscription_enabled
# ─────────────────────────────────────────────────────────

class TestSetEnabled:
    def test_disable(self, client):
        sub = add_subscription(client, "chat1", "ua", "kyiv", "agro_tractor")
        assert sub is not None
        set_subscription_enabled(client, sub.id, False)
        sub2 = get_subscription(client, sub.id)
        assert sub2 is not None
        assert sub2.enabled is False

    def test_reenable(self, client):
        sub = add_subscription(client, "chat1", "ua", "kyiv", "agro_tractor")
        assert sub is not None
        set_subscription_enabled(client, sub.id, False)
        set_subscription_enabled(client, sub.id, True)
        sub2 = get_subscription(client, sub.id)
        assert sub2 is not None
        assert sub2.enabled is True


# ─────────────────────────────────────────────────────────
# remove_subscription
# ─────────────────────────────────────────────────────────

class TestRemove:
    def test_removes_own(self, client):
        sub = add_subscription(client, "chat1", "ua", "kyiv", "agro_tractor")
        assert sub is not None
        assert remove_subscription(client, "chat1", sub.id) is True
        assert get_subscription(client, sub.id) is None

    def test_cannot_remove_other_chat(self, client):
        sub = add_subscription(client, "chat1", "ua", "kyiv", "agro_tractor")
        assert sub is not None
        assert remove_subscription(client, "chat2", sub.id) is False
        assert get_subscription(client, sub.id) is not None

    def test_remove_nonexistent(self, client):
        assert remove_subscription(client, "chat1", 999) is False


# ─────────────────────────────────────────────────────────
# count_subscriptions
# ─────────────────────────────────────────────────────────

class TestCount:
    def test_empty(self, client):
        assert count_subscriptions(client, "chat1") == 0

    def test_counts_enabled_only(self, client):
        s1 = add_subscription(client, "chat1", "ua", "kyiv", "agro_tractor")
        add_subscription(client, "chat1", "ua", "lviv", "driver_b")
        assert s1 is not None
        assert count_subscriptions(client, "chat1") == 2

        set_subscription_enabled(client, s1.id, False)
        assert count_subscriptions(client, "chat1") == 1

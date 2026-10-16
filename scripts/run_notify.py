"""Розсилка вакансій користувачам: матч → send → mark_sent.

v2: працює з user_subscriptions, підтримує baseline vs new.
"""
from __future__ import annotations

import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tumbleweed.config import settings
from tumbleweed.db.client import TursoClient
from tumbleweed.db.queries_jobs import (
    list_active_subscriptions,
    mark_baseline_done,
    mark_sent,
    update_last_parsed_at,
)
from tumbleweed.services.matcher import find_matches_for_all_subscriptions
from tumbleweed.services.telegram_client import TelegramClient


def _now_iso() -> str:
    """Поточний час UTC у форматі 'YYYY-MM-DD HH:MM:SS' (як SQLite)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-7s | %(message)s",
        datefmt="%H:%M:%S",
    )
    log = logging.getLogger(__name__)

    client = TursoClient(settings.turso_url, settings.turso_token)
    notifier = TelegramClient(settings.bot_token)

    subs = list_active_subscriptions(client)
    print(f"Активних підписок: {len(subs)}")
    if not subs:
        print("Немає кому надсилати.")
        return

    # Фіксуємо момент старту циклу.
    # Усі вакансії, знайдені в цьому циклі, мають saved_at <= cycle_start_ts.
    # Після успішної відправки для кожної підписки ставимо last_parsed_at = cycle_start_ts,
    # щоб наступний цикл шукав ТІЛЬКИ новіші.
    cycle_start_ts = _now_iso()

    results = find_matches_for_all_subscriptions(client, subs)
    print(f"Підписок з матчами: {len(results)}\n")

    total_sent = 0
    total_failed = 0

    for sub, vacancies in results:
        print(f"→ chat_id={sub.chat_id}  "
              f"[{sub.city_slug} / {sub.profession_key or 'будь-яка'}]  "
              f"({len(vacancies)} вакансій)")

        sent_in_sub = 0
        failed_in_sub = 0

        for v in vacancies:
            ok = notifier.send_vacancy(sub.chat_id, v)
            if ok:
                mark_sent(client, sub.chat_id, v["id"])
                sent_in_sub += 1
                total_sent += 1
                print(f"    ✅ {v.get('title', '')[:60]}")
            else:
                failed_in_sub += 1
                total_failed += 1
                print(f"    ❌ {v.get('title', '')[:60]}")

        # Оновлюємо стан підписки ТІЛЬКИ після хоча б однієї успішної відправки.
        # Якщо всі впали — не оновлюємо, щоб наступний цикл спробував знову.
        if sent_in_sub > 0:
            if not sub.baseline_done:
                mark_baseline_done(client, sub.id, cycle_start_ts)
                print(f"    ℹ️  baseline завершено для sub {sub.id}")
            else:
                update_last_parsed_at(client, sub.id, cycle_start_ts)
                print(f"    ℹ️  last_parsed_at = {cycle_start_ts}")

    print(f"\n{'=' * 60}")
    print(f"✅ Надіслано: {total_sent}")
    print(f"❌ Помилок:  {total_failed}")


if __name__ == "__main__":
    main()

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
from tumbleweed.services.matcher import find_vacancies_for_subscription
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
    cycle_start_ts = _now_iso()

    total_sent = 0
    total_failed = 0
    no_vacancies = 0

    # Проходимо ВСІ підписки (а не тільки ті, що мають матчі)
    for sub in subs:
        try:
            vacancies = find_vacancies_for_subscription(client, sub)
        except Exception as e:
            log.exception("Матчинг для sub %s: %s", sub.id, e)
            continue

        # Якщо це перший парсинг і 0 вакансій — сказати "немає"
        if not vacancies and not sub.baseline_done:
            try:
                notifier.send_message(
                    sub.chat_id,
                    "😔 *На жаль, зараз на сайтах немає вакансій за твоїм запитом.*\n\n"
                    "🔍 Спробуйте змінити формат написання професії (наприклад, іншою мовою).\n\n"
                    "🔔 Я повідомлю, як тільки з'являться — просто чекай.",
                )
                mark_baseline_done(client, sub.id, cycle_start_ts)
                no_vacancies += 1
                print(f"    ℹ️  sub {sub.id}: baseline без вакансій")
            except Exception as e:
                log.warning("send_message (no vacancies): %s", e)
            continue

        # Якщо вакансій немає, але baseline вже зроблено — просто пропускаємо
        # (нічого не змінилось, не спамимо користувача)
        if not vacancies and sub.baseline_done:
            continue

        # Якщо є вакансії — надсилаємо
        print(f"→ chat_id={sub.chat_id}  "
              f"[{sub.city_slug} / {sub.profession_key or 'будь-яка'}]  "
              f"({len(vacancies)} вакансій)")

        sent_in_sub = 0
        for v in vacancies:
            ok = notifier.send_vacancy(sub.chat_id, v)
            if ok:
                mark_sent(client, sub.chat_id, v["id"])
                sent_in_sub += 1
                total_sent += 1
                print(f"    ✅ {v.get('title', '')[:60]}")
            else:
                total_failed += 1
                print(f"    ❌ {v.get('title', '')[:60]}")

        # Оновлюємо стан підписки ТІЛЬКИ після хоча б однієї успішної відправки.
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
    print(f"😔 Без вакансій: {no_vacancies}")


if __name__ == "__main__":
    main()

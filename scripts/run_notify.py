"""Розсилка вакансій користувачам: матч → send → mark_sent (sync, без PTB)."""
from __future__ import annotations

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tumbleweed.config import settings
from tumbleweed.db.client import TursoClient
from tumbleweed.db.queries_jobs import (
    list_active_profiles,
    mark_sent,
)
from tumbleweed.services.matcher import find_matches_for_all
from tumbleweed.services.telegram_client import TelegramClient


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-7s | %(message)s",
        datefmt="%H:%M:%S",
    )

    client = TursoClient(settings.turso_url, settings.turso_token)
    notifier = TelegramClient(settings.bot_token)

    profiles = list_active_profiles(client)
    print(f"Активних профілів: {len(profiles)}")
    if not profiles:
        print("Немає кому надсилати.")
        return

    results = find_matches_for_all(client, profiles, since_hours=24)
    print(f"Профілів з матчами: {len(results)}\n")

    total_sent = 0
    for r in results:
        print(f"→ chat_id={r.profile.chat_id}  ({len(r.vacancies)} вакансій)")
        for v in r.vacancies:
            ok = notifier.send_vacancy(r.profile.chat_id, v)
            if ok:
                mark_sent(client, r.profile.chat_id, v["id"])
                total_sent += 1
                print(f"    ✅ {v.get('title', '')[:60]}")
            else:
                print(f"    ❌ {v.get('title', '')[:60]}")

    print(f"\n{'=' * 60}")
    print(f"✅ Надіслано всього: {total_sent}")


if __name__ == "__main__":
    main()

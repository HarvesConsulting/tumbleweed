"""Запуск TumbleWeed-бота у режимі polling (для dev/локального тесту)."""
from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tumbleweed.bot.bot import run_polling


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )
    # Прибираємо шум від httpx
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("telegram.ext.ExtBot").setLevel(logging.WARNING)

    try:
        asyncio.run(run_polling())
    except KeyboardInterrupt:
        print("\n👋 Зупинено користувачем")


if __name__ == "__main__":
    main()
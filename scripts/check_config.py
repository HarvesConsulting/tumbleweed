"""Перевірка, що .env і config.py працюють."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tumbleweed.config import DATA_DIR, PROJECT_ROOT_PATH, settings


def mask(s: str) -> str:
    if not s:
        return "<empty>"
    return s[:6] + "..." + s[-4:] if len(s) > 12 else "<too short>"


print(f"PROJECT_ROOT : {PROJECT_ROOT_PATH}")
print(f"DATA_DIR     : {DATA_DIR}")
print(f"DATA exists  : {DATA_DIR.exists()}")
print(f"ENV          : {settings.env}")
print(f"BOT_TOKEN    : {mask(settings.bot_token)}")
print(f"TURSO_URL    : {mask(settings.turso_url)}")
print(f"TURSO_TOKEN  : {mask(settings.turso_token)}")

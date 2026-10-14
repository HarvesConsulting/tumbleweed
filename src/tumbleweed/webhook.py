"""Flask-додаток для Render.

Endpoint-и:
  POST /webhook         — Telegram webhook (для бота 24/7)
  POST /parse-workua    — Work.ua парсер (обхід Cloudflare через Render IP)
  GET  /health          — health-check
  GET  /                 — те саме
"""
from __future__ import annotations

import asyncio
import logging
import os
import threading
import time

from flask import Flask, jsonify, request
from telegram import Update

from tumbleweed.bot.bot import build_application
from tumbleweed.config import settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
)
log = logging.getLogger(__name__)

app = Flask(__name__)

# Глобальні об'єкти
_ptb_app = None
_loop: asyncio.AbstractEventLoop | None = None

# API key для захисту /parse-workua
API_KEY = os.getenv("RENDER_API_KEY", "")


# ───────────────────────────────────────────────────────
# Telegram webhook
# ───────────────────────────────────────────────────────

def _run_ptb_forever() -> None:
    """Запускає PTB Application у фоновому потоці та крутить event loop."""
    global _ptb_app, _loop

    _loop = asyncio.new_event_loop()
    asyncio.set_event_loop(_loop)

    _ptb_app = build_application()
    _loop.run_until_complete(_ptb_app.initialize())
    _loop.run_until_complete(_ptb_app.start())

    log.info("✅ PTB Application запущено і обробляє update_queue")

    # Крутимо event loop вічно
    _loop.run_forever()


def get_ptb_app():
    """Ліниво ініціалізуємо PTB Application у фоновому потоці."""
    global _ptb_app

    if _ptb_app is None:
        threading.Thread(target=_run_ptb_forever, daemon=True).start()

        # Чекаємо до 10 сек
        for _ in range(20):
            if _ptb_app is not None:
                break
            time.sleep(0.5)

        if _ptb_app is None:
            raise RuntimeError("PTB Application не запустився")

    return _ptb_app


@app.route("/")
@app.route("/health")
def health() -> tuple[str, int]:
    # Прокидаємо PTB при першому пінгу (для keep-alive cron)
    try:
        get_ptb_app()
    except Exception as e:
        log.warning("PTB init (from /health): %s", e)
    return "TumbleWeed is alive", 200


@app.route("/webhook", methods=["POST"])
def webhook() -> tuple[str, int]:
    """Отримує оновлення від Telegram."""
    try:
        data = request.get_json(force=True)
        update = Update.de_json(data, get_ptb_app().bot)
        get_ptb_app().update_queue.put_nowait(update)
        return "ok", 200
    except Exception as e:
        log.exception("Webhook error: %s", e)
        return "error", 500


# ───────────────────────────────────────────────────────
# Work.ua парсер (запускається з Render)
# ───────────────────────────────────────────────────────

@app.route("/parse-workua", methods=["POST"])
def parse_workua() -> tuple[dict, int]:
    """Запускає парсинг Work.ua і записує в Turso.

    Захищено заголовком X-API-Key.
    """
    if API_KEY:
        provided = request.headers.get("X-API-Key", "")
        if provided != API_KEY:
            log.warning("Невірний X-API-Key")
            return {"error": "unauthorized"}, 401

    try:
        result = asyncio.run(_run_workua_parse())
        return {"ok": True, "result": result}, 200
    except Exception as e:
        log.exception("/parse-workua error: %s", e)
        return {"ok": False, "error": str(e)}, 500


async def _run_workua_parse() -> dict:
    """Парсить Work.ua і повертає статистику."""
    from tumbleweed.db.client import TursoClient
    from tumbleweed.db.queries_jobs import (
        list_active_profiles,
        save_and_mark,
    )
    from tumbleweed.parsers.workua import WorkUaParser
    from tumbleweed.services.subcategory_search import get_subcategory

    client = TursoClient(settings.turso_url, settings.turso_token)
    parser = WorkUaParser()

    # Збираємо запити з активних профілів
    profiles = list_active_profiles(client)
    queries: set[tuple[str, str]] = set()

    for p in profiles:
        if not p.professions:
            continue
        cities = p.cities or [""]
        for sub_key in p.professions:
            if sub_key.startswith("custom:"):
                query = sub_key[len("custom:"):].strip()
            else:
                cat_key, _, _ = sub_key.partition("_")
                sub = get_subcategory(cat_key, sub_key)
                query = sub.keywords[0] if sub and sub.keywords else ""
            if not query:
                continue
            for city in cities:
                queries.add((city, query))

    # Cold start
    for q in ["backend", "продавець", "водій"]:
        queries.add(("kyiv", q))

    # Парсимо
    total_found = 0
    total_new = 0
    for city, query in queries:
        try:
            vacancies = await parser.fetch(
                city_slug=city or None,
                query=query,
                limit=40,
            )
        except Exception as e:
            log.warning("Work.ua %s/%s: %s", city, query, e)
            continue

        new = 0
        for v in vacancies:
            try:
                if save_and_mark(client, v):
                    new += 1
            except Exception as e:
                log.warning("Збереження: %s", e)

        total_found += len(vacancies)
        total_new += new

    return {
        "queries": len(queries),
        "found": total_found,
        "new": total_new,
    }


# ───────────────────────────────────────────────────────
# Startup (для Render/gunicorn)
# ───────────────────────────────────────────────────────

# На Render (gunicorn) — ініціалізуємо PTB одразу при старті worker,
# а не чекаємо першого запиту на /webhook.
if os.getenv("RENDER") or os.getenv("PORT"):
    log.info("🚀 Ініціалізуємо PTB при старті (Render detected)")
    threading.Thread(target=_run_ptb_forever, daemon=True).start()


# ───────────────────────────────────────────────────────
# Local dev
# ───────────────────────────────────────────────────────

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)

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

# API-ключ для захисту /parse-workua
API_KEY = os.getenv("RENDER_API_KEY", "")

# Перевірка: ми в gunicorn worker чи в master?
def _is_gunicorn_worker() -> bool:
    """True, якщо це gunicorn worker, а не master."""
    try:
        from gunicorn.arbiter import Arbiter
        return not isinstance(threading.current_thread(), threading._MainThread) \
               or os.environ.get("GUNICORN_WORKER") == "1" \
               or hasattr(threading.current_thread(), "name") and "gunicorn" in threading.current_thread().name.lower()
    except ImportError:
        return True


# Глобальні об'єкти
_ptb_app = None
_loop: asyncio.AbstractEventLoop | None = None
_ptb_lock = threading.Lock()
_ptb_started = False


def _run_ptb_forever() -> None:
    """Запускає PTB Application у фоновому потоці та крутить event loop."""
    global _ptb_app, _loop

    try:
        _loop = asyncio.new_event_loop()
        asyncio.set_event_loop(_loop)

        _ptb_app = build_application()
        _loop.run_until_complete(_ptb_app.initialize())
        _loop.run_until_complete(_ptb_app.start())

        log.info("✅ PTB Application запущено і обробляє update_queue")
        _loop.run_forever()
    except Exception as e:
        log.exception("❌ _run_ptb_forever впав: %s", e)
        _ptb_app = None  # дозволяємо повторну спробу


def get_ptb_app(timeout: float = 30.0):
    """Ліниво ініціалізуємо PTB Application у фоновому потоці (thread-safe)."""
    global _ptb_app, _ptb_started

    if _ptb_app is not None:
        return _ptb_app

    with _ptb_lock:
        if _ptb_app is not None:
            return _ptb_app

        if not _ptb_started:
            _ptb_started = True
            threading.Thread(target=_run_ptb_forever, daemon=True).start()

        deadline = time.time() + timeout
        while time.time() < deadline:
            if _ptb_app is not None:
                return _ptb_app
            time.sleep(0.5)

        _ptb_started = False  # скидаємо, щоб наступний виклик спробував знову
        raise RuntimeError("PTB Application не запустився (timeout)")


@app.route("/")
@app.route("/health")
def health() -> tuple[str, int]:
    """Простий health-check. НЕ чіпає PTB — щоб не блокувати webhook."""
    return "TumbleWeed is alive", 200


@app.route("/debug")
def debug() -> tuple[dict, int]:
    """Діагностика."""
    result = {
        "ptb_app": _ptb_app is not None,
        "loop_exists": _loop is not None,
        "loop_running": _loop.is_running() if _loop else False,
        "ptb_started": _ptb_started,
    }
    if _ptb_app is not None:
        result["handlers_count"] = len(_ptb_app.handlers[0]) if _ptb_app.handlers else 0
    return result, 200


@app.route("/webhook", methods=["POST"])
def webhook() -> tuple[str, int]:
    """Отримує оновлення від Telegram."""
    try:
        data = request.get_json(force=True)

        # Логування кожного update
        update_id = data.get("update_id", "?")
        if "message" in data:
            text = data["message"].get("text", "")[:50]
            log.info("📨 update_id=%s message=%r", update_id, text)
        elif "callback_query" in data:
            cb_data = data["callback_query"].get("data", "")[:50]
            log.info("🔘 update_id=%s callback=%r", update_id, cb_data)
        else:
            log.info("📦 update_id=%s keys=%s", update_id, list(data.keys()))
       
        # Отримуємо Application
        application = get_ptb_app()
        update = Update.de_json(data, application.bot)

        # Перевірка: event loop живий
        if _loop is None or not _loop.is_running():
            log.error("Event loop не запущено — не можу обробити update")
            return "error: loop not running", 500

        future = asyncio.run_coroutine_threadsafe(
            application.process_update(update),
            _loop,
        )

        def _log_result(fut):
            try:
                fut.result(timeout=0.1)
            except Exception as e:
                log.exception("Обробка update %s впала: %s", update_id, e)

        future.add_done_callback(_log_result)
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

if os.getenv("RENDER") or os.getenv("PORT"):
    log.info("🚀 Ініціалізуємо PTB при старті (Render detected)")
    try:
        get_ptb_app()
        log.info("✅ PTB готовий до роботи")
    except Exception as e:
        log.exception("Помилка старту PTB: %s", e)


# ───────────────────────────────────────────────────────
# SIGTERM handler (Render sends this on restart)
# ───────────────────────────────────────────────────────

import signal
import sys

def _shutdown_handler(signum, frame):
    log.info("🛑 Отримано сигнал %s — завершуємо PTB", signum)
    if _loop is not None and _loop.is_running():
        _loop.call_soon_threadsafe(_loop.stop)
    if _ptb_app is not None:
        try:
            asyncio.run_coroutine_threadsafe(
                _ptb_app.stop(),
                _loop,
            ).result(timeout=5)
        except Exception as e:
            log.warning("PTB stop: %s", e)
    sys.exit(0)

signal.signal(signal.SIGTERM, _shutdown_handler)
signal.signal(signal.SIGINT, _shutdown_handler)
# ───────────────────────────────────────────────────────
# Local dev
# ───────────────────────────────────────────────────────

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)

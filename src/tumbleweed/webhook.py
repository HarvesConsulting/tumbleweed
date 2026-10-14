"""Flask-додаток для Render.

Endpoint-и:
  POST /webhook         — Telegram webhook (для бота 24/7)
  GET  /health          — health-check (легкий, для моніторингу)
  GET  /keepalive       — важкий keep-alive (для cron-job.org)
  GET  /debug           — діагностика
  GET  /                — те саме, що /health
"""
from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys
import threading
import time

from flask import Flask, request
from telegram import Update

from tumbleweed.bot.bot import build_application
from tumbleweed.config import settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
)
log = logging.getLogger(__name__)

app = Flask(__name__)


# ───────────────────────────────────────────────────────
# Global state
# ───────────────────────────────────────────────────────

_ptb_app = None
_loop: asyncio.AbstractEventLoop | None = None
_ptb_lock = threading.Lock()
_ptb_started = False


# ───────────────────────────────────────────────────────
# Background keep-awake scheduler (backup механізм)
# ───────────────────────────────────────────────────────

def _keep_awake_scheduler() -> None:
    """Фоновий потік: робить запит до OLX кожні 4 хв.

    Backup для /keepalive + cron-job.org.
    Якщо cron не працює — цей потік не дає Render заснути.
    """
    time.sleep(60)  # чекаємо PTB старт

    iteration = 0
    while True:
        iteration += 1
        try:
            log.info("💓 keep-awake #%d: старт", iteration)

            from curl_cffi import requests as cffi_requests

            r = cffi_requests.get(
                "https://www.olx.ua/api/v1/offers/",
                params={"limit": 5, "category_id": 1800},
                headers={"Accept": "application/json"},
                impersonate="chrome124",
                timeout=15,
            )
            log.info(
                "💓 keep-awake #%d: OLX %s, %d items",
                iteration,
                r.status_code,
                len((r.json() or {}).get("data") or []),
            )
        except Exception as e:
            log.warning("💓 keep-awake #%d: %s", iteration, e)

        time.sleep(240)  # 4 хв


# ───────────────────────────────────────────────────────
# PTB Application (runs in background thread)
# ───────────────────────────────────────────────────────

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

        _ptb_started = False
        raise RuntimeError("PTB Application не запустився (timeout)")


# ───────────────────────────────────────────────────────
# HTTP routes
# ───────────────────────────────────────────────────────

@app.route("/")
@app.route("/health")
def health() -> tuple[str, int]:
    """Легкий health-check. НЕ чіпає PTB — щоб не блокувати webhook."""
    return "TumbleWeed is alive", 200


@app.route("/keepalive")
def keepalive() -> tuple[dict, int]:
    """Важкий keep-alive: робить реальний HTTP-запит до OLX.

    Використовується cron-job.org:
    - вхідний трафік → Render не вимикає контейнер
    - реальний запит до OLX → CPU активно працює
    """
    start = time.time()
    try:
        from curl_cffi import requests as cffi_requests

        r = cffi_requests.get(
            "https://www.olx.ua/api/v1/offers/",
            params={"limit": 1, "category_id": 1800},
            headers={"Accept": "application/json"},
            impersonate="chrome124",
            timeout=10,
        )
        elapsed = int((time.time() - start) * 1000)
        log.info("💓 keepalive: OLX %s за %d ms", r.status_code, elapsed)
        return {
            "ok": True,
            "olx_status": r.status_code,
            "elapsed_ms": elapsed,
        }, 200
    except Exception as e:
        elapsed = int((time.time() - start) * 1000)
        log.warning("💓 keepalive: помилка за %d ms: %s", elapsed, e)
        return {
            "ok": False,
            "error": str(e),
            "elapsed_ms": elapsed,
        }, 500


@app.route("/debug")
def debug() -> tuple[dict, int]:
    """Діагностика стану PTB."""
    result = {
        "ptb_app": _ptb_app is not None,
        "loop_exists": _loop is not None,
        "loop_running": _loop.is_running() if _loop else False,
        "ptb_started": _ptb_started,
    }
    if _ptb_app is not None:
        result["handlers_count"] = (
            len(_ptb_app.handlers[0]) if _ptb_app.handlers else 0
        )
    return result, 200


@app.route("/webhook", methods=["POST"])
def webhook() -> tuple[str, int]:
    """Отримує оновлення від Telegram."""
    try:
        data = request.get_json(force=True)

        update_id = data.get("update_id", "?")
        if "message" in data:
            text = data["message"].get("text", "")[:50]
            log.info("📨 update_id=%s message=%r", update_id, text)
        elif "callback_query" in data:
            cb_data = data["callback_query"].get("data", "")[:50]
            log.info("🔘 update_id=%s callback=%r", update_id, cb_data)
        else:
            log.info("📦 update_id=%s keys=%s", update_id, list(data.keys()))

        application = get_ptb_app()
        update = Update.de_json(data, application.bot)

        if _loop is None or not _loop.is_running():
            log.error("Event loop не запущено — не можу обробити update")
            return "error: loop not running", 500

        start = time.time()
        log.info("⏱ Старт обробки update_id=%s", update_id)

        future = asyncio.run_coroutine_threadsafe(
            application.process_update(update),
            _loop,
        )

        def _log_result(fut):
            elapsed = (time.time() - start) * 1000
            try:
                fut.result(timeout=0.1)
                log.info(
                    "✅ Обробка update_id=%s завершена за %.0f ms",
                    update_id, elapsed,
                )
            except Exception as e:
                log.exception(
                    "❌ Обробка update_id=%s впала за %.0f ms: %s",
                    update_id, elapsed, e,
                )

        future.add_done_callback(_log_result)
        return "ok", 200
    except Exception as e:
        log.exception("Webhook error: %s", e)
        return "error", 500


# ───────────────────────────────────────────────────────
# Startup (Render/gunicorn)
# ───────────────────────────────────────────────────────

if os.getenv("RENDER") or os.getenv("PORT"):
    log.info("🚀 Ініціалізуємо PTB при старті (Render detected)")
    try:
        get_ptb_app()
        log.info("✅ PTB готовий до роботи")
    except Exception as e:
        log.exception("Помилка старту PTB: %s", e)

    # Backup keep-awake (якщо cron-job.org не працює)
    threading.Thread(target=_keep_awake_scheduler, daemon=True).start()
    log.info("✅ Keep-awake scheduler запущено (backup)")


# ───────────────────────────────────────────────────────
# SIGTERM handler (Render sends on restart)
# ───────────────────────────────────────────────────────

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

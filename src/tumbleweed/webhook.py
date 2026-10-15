"""Flask-додаток для Render.

Endpoint-и:
  GET  /health          — легкий health-check
  GET  /debug           — діагностика
  GET  /keepalive       — швидкий endpoint для cron-job.org
  POST /webhook         — Telegram webhook (миттєвий return 200)
  GET  /                — те саме, що /health

Архітектура:
  - Lazy startup у worker process (gunicorn)
  - Миттєвий return 200 з /webhook (обробка у daemon-thread)
  - Немає PTB Application, event loop, ConversationHandler
  - Sync: build_context + handle_update
"""
from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any

from flask import Flask, request

from tumbleweed.bot.bot import build_context
from tumbleweed.config import settings
from tumbleweed.services.dispatcher import BotContext, handle_update

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
)
log = logging.getLogger(__name__)

app = Flask(__name__)
app.json.ensure_ascii = False


# ───────────────────────────────────────────────────────
# Global state + lazy startup
# ───────────────────────────────────────────────────────

_ctx: BotContext | None = None
_startup_lock = threading.Lock()
_startup_done = False


def _ensure_startup() -> None:
    """Lazy startup у worker process (thread-safe, idempotent).

    Гарантує, що BotContext створюється у worker gunicorn,
    а не в master, і не блокує старт додатку.
    """
    global _ctx, _startup_done

    if _ctx is not None:
        return

    with _startup_lock:
        if _ctx is not None:
            return

        log.info("🔄 Startup у worker process...")
        try:
            _ctx = build_context()
            _startup_done = True
            log.info("✅ Startup завершено")
        except Exception as e:
            log.exception("❌ Startup failed: %s", e)
            raise


# ───────────────────────────────────────────────────────
# Flask routes
# ───────────────────────────────────────────────────────

@app.route("/")
@app.route("/health")
def health() -> tuple[str, int]:
    """Легкий health-check — НЕ чіпає startup."""
    return "TumbleWeed is alive", 200


@app.route("/debug")
def debug() -> tuple[dict, int]:
    """Діагностика стану (чіпає startup)."""
    try:
        _ensure_startup()
    except Exception as e:
        return {"ready": False, "error": str(e)}, 500

    return {
        "ready": _ctx is not None,
        "startup_done": _startup_done,
        "has_client": _ctx.client is not None if _ctx else False,
        "has_notifier": _ctx.notifier is not None if _ctx else False,
    }, 200


@app.route("/keepalive")
def keepalive() -> tuple[dict, int]:
    """Швидкий endpoint для cron-job.org."""
    start = time.time()
    try:
        _ensure_startup()
        elapsed = int((time.time() - start) * 1000)
        log.info("💓 keepalive: OK за %d ms", elapsed)
        return {"ok": True, "elapsed_ms": elapsed}, 200
    except Exception as e:
        elapsed = int((time.time() - start) * 1000)
        log.warning("💓 keepalive: помилка за %d ms: %s", elapsed, e)
        return {"ok": False, "error": str(e), "elapsed_ms": elapsed}, 500


@app.route("/webhook", methods=["POST"])
def webhook() -> tuple[str, int]:
    """Telegram webhook — МИТТЄВИЙ return 200.

    Обробка update у daemon-thread,
    щоб Telegram не чекав і не робив retry.
    """
    try:
        # ── Перевірка secret від Telegram ──
        if settings.webhook_secret:
            secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
            if secret != settings.webhook_secret:
                log.warning(
                    "Webhook: невірний secret_token від %s",
                    request.remote_addr,
                )
                return "forbidden", 403

        _ensure_startup()
        if _ctx is None:
            return "not ready", 503

        data = request.get_json(force=True)
        update_id = data.get("update_id", "?")

        # Логування
        if "message" in data:
            text = (data["message"].get("text") or "")[:50]
            log.info("📨 update_id=%s message=%r", update_id, text)
        elif "callback_query" in data:
            cb_data = (data["callback_query"].get("data") or "")[:50]
            log.info("🔘 update_id=%s callback=%r", update_id, cb_data)
        else:
            log.info("📦 update_id=%s keys=%s", update_id, list(data.keys()))

        # Обробка у ФОНОВОМУ ПОТОЦІ — миттєвий return 200
        threading.Thread(
            target=_safe_handle_update,
            args=(data,),
            daemon=True,
        ).start()

        return "ok", 200
    except Exception as e:
        log.exception("Webhook error: %s", e)
        return "error", 500


def _safe_handle_update(data: dict[str, Any]) -> None:
    """Обробляє update у потоці. Не блокує webhook."""
    if _ctx is None:
        log.error("_safe_handle_update: _ctx is None")
        return

    update_id = data.get("update_id", "?")
    start = time.time()

    try:
        handle_update(data, _ctx)
        elapsed = (time.time() - start) * 1000
        log.info("✅ Обробка update_id=%s завершена за %.0f ms", update_id, elapsed)
    except Exception as e:
        elapsed = (time.time() - start) * 1000
        log.exception(
            "❌ Обробка update_id=%s впала за %.0f ms: %s",
            update_id, elapsed, e,
        )


# ───────────────────────────────────────────────────────
# Startup
# ───────────────────────────────────────────────────────

if os.getenv("RENDER") or os.getenv("PORT"):
    log.info("🚀 Render detected — startup буде ліниво (при першому /webhook)")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)

"""Telegram Bot API клієнт (sync, без PTB Application).

Надсилає повідомлення, фото, редагує повідомлення, відповідає на callback.
Прямий HTTP до api.telegram.org через curl_cffi.

Використовується у webhook.py (Render).
НЕ використовується у scripts/run_notify.py — там свій async Notifier.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any

from curl_cffi import requests as cffi_requests

log = logging.getLogger(__name__)

API_BASE = "https://api.telegram.org"


class TelegramClient:
    """Sync HTTP-клієнт Telegram Bot API.

    Приклад:
        client = TelegramClient(token)
        client.send_message("123", "Hello", keyboard={"inline_keyboard": [...]})
    """

    def __init__(self, token: str, *, timeout: int = 15) -> None:
        if not token:
            raise ValueError("Telegram token обов'язковий")
        self._token = token
        self._timeout = timeout
        self._semaphore = threading.Semaphore(5)

    # ─────────────────────────────────────────────────────
    # Public API
    # ─────────────────────────────────────────────────────

    def send_message(
        self,
        chat_id: str | int,
        text: str,
        *,
        parse_mode: str = "Markdown",
        keyboard: dict[str, Any] | None = None,
        disable_preview: bool = True,
    ) -> bool:
        """Надсилає текстове повідомлення."""
        payload: dict[str, Any] = {
            "chat_id": str(chat_id),
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": disable_preview,
        }
        if keyboard is not None:
            payload["reply_markup"] = keyboard
        return self._call("sendMessage", payload)

    def send_vacancy(self, chat_id: str | int, v: dict) -> bool:
        """Надсилає одну вакансію з кнопками.

        Args:
            chat_id: ID чату
            v: dict з полями: id, title, company, salary, city_slug, job_type, link

        Returns:
            True якщо успішно.
        """
        from tumbleweed.config import settings

        title = (v.get("title") or "").strip()
        company = v.get("company") or ""
        salary = v.get("salary") or ""
        city = v.get("city_slug") or ""
        job_type = v.get("job_type") or ""
        link = v.get("link") or ""
        vacancy_id = v.get("id", "")
        country = v.get("country") or "ua"

        # ── Переклад для PL / RO ─────────────────────
        title_display = title
        title_original = None

        if country in ("pl", "ro") and title:
            try:
                if country == "pl":
                    from tumbleweed.services.translate import translate_pl_to_uk
                    title_uk = translate_pl_to_uk(title)
                else:
                    from tumbleweed.services.translate import translate_ro_to_uk
                    title_uk = translate_ro_to_uk(title)

                if title_uk and title_uk != title:
                    title_display = title_uk
                    title_original = title
            except Exception as e:
                log.warning(
                    "send_vacancy: translate failed for %r: %s",
                    title[:40], e,
                )

        # Прапор країни
        FLAGS = {"ua": "🇺🇦", "pl": "🇵🇱", "ro": "🇷🇴"}
        flag = FLAGS.get(country, "")

        lines = [f"💼 *{title_display}*"]
        if title_original:
            lines.append(f"{flag} _{title_original}_")
        lines.append("")

        if company:
            lines.append(f"🏢 {company}")
        if salary:
            lines.append(f"💰 {salary}")
        if city:
            lines.append(f"📍 {city}")
        if job_type:
            lines.append(f"🕐 {job_type}")

        text = "\n".join(lines)

        city_slug = v.get("city_slug") or ""
        parts = ["from_tumbleweed", str(chat_id)]
        if city_slug:
            parts.append(city_slug)
        rentalert_url = f"{settings.rentalert_bot_url}?start={'_'.join(parts)}"

        buttons: list[list[dict[str, str]]] = []
        if link:
            buttons.append([{"text": "🔗 Відкрити вакансію", "url": link}])
        buttons.append([
            {"text": "🏠 Житло тут", "url": rentalert_url},
            {"text": "🚫 Ігнор", "callback_data": f"action:ignore_vacancy:{vacancy_id}"},
        ])

        return self.send_message(
            chat_id,
            text,
            keyboard={"inline_keyboard": buttons},
        )

    def send_photo(
        self,
        chat_id: str | int,
        photo_url: str,
        caption: str,
        *,
        parse_mode: str = "Markdown",
        keyboard: dict[str, Any] | None = None,
    ) -> bool:
        """Надсилає фото з підписом."""
        payload: dict[str, Any] = {
            "chat_id": str(chat_id),
            "photo": photo_url,
            "caption": caption[:1024],
            "parse_mode": parse_mode,
        }
        if keyboard is not None:
            payload["reply_markup"] = keyboard
        return self._call("sendPhoto", payload)

    def send_photo_or_message(
        self,
        chat_id: str | int,
        photo_url: str | None,
        caption: str,
        *,
        parse_mode: str = "Markdown",
        keyboard: dict[str, Any] | None = None,
    ) -> bool:
        """Якщо фото є — sendPhoto, інакше sendMessage."""
        if photo_url:
            return self.send_photo(
                chat_id, photo_url, caption,
                parse_mode=parse_mode, keyboard=keyboard,
            )
        return self.send_message(
            chat_id, caption,
            parse_mode=parse_mode, keyboard=keyboard,
        )

    def edit_message(
        self,
        chat_id: str | int,
        message_id: int,
        text: str,
        *,
        parse_mode: str = "Markdown",
        keyboard: dict[str, Any] | None = None,
    ) -> bool:
        """Редагує текстове повідомлення.

        ⚠️ Якщо текст і розмітка не змінились — Telegram поверне
        "message is not modified", і ми логуємо це як info, не error.
        """
        payload: dict[str, Any] = {
            "chat_id": str(chat_id),
            "message_id": message_id,
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": True,
        }
        payload["reply_markup"] = (
            keyboard if keyboard is not None else {"inline_keyboard": []}
        )
        return self._call("editMessageText", payload)

    def edit_reply_markup(
        self,
        chat_id: str | int,
        message_id: int,
        keyboard: dict[str, Any],
    ) -> bool:
        """Замінює inline-клавіатуру повідомлення."""
        payload: dict[str, Any] = {
            "chat_id": str(chat_id),
            "message_id": message_id,
            "reply_markup": keyboard,
        }
        return self._call("editMessageReplyMarkup", payload)

    def answer_callback(
        self,
        callback_id: str,
        text: str | None = None,
        *,
        show_alert: bool = False,
    ) -> bool:
        """Відповідає на callback (прибирає «годинник» у клієнті)."""
        payload: dict[str, Any] = {
            "callback_query_id": callback_id,
            "show_alert": show_alert,
        }
        if text:
            payload["text"] = text[:200]
        return self._call("answerCallbackQuery", payload)

    # ─────────────────────────────────────────────────────
    # Внутрішнє
    # ─────────────────────────────────────────────────────

    def _call(self, method: str, payload: dict[str, Any]) -> bool:
        """Викликає Telegram API метод з обмеженням паралелізму."""
        with self._semaphore:
            try:
                response = cffi_requests.post(
                    f"{API_BASE}/bot{self._token}/{method}",
                    data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    timeout=self._timeout,
                )
            except Exception as e:
                log.exception("Telegram %s: HTTP error: %s", method, e)
                return False

            try:
                result = response.json()
            except Exception as e:
                log.warning("Telegram %s: bad JSON: %s", method, e)
                return False

            if result.get("ok"):
                return True

            error_code = result.get("error_code")
            description = (result.get("description") or "").lower()

            # 403 — користувач заблокував бота
            if error_code == 403:
                log.info(
                    "Telegram %s: 403 (%s) for chat_id=%r",
                    method, description, payload.get("chat_id"),
                )
                return False

            # 429 — rate limit, чекаємо і один retry
            if error_code == 429:
                retry_after = result.get("parameters", {}).get("retry_after", 5)
                log.warning(
                    "Telegram %s: 429 rate limit, чекаю %ds і повторюю",
                    method, retry_after,
                )
                time.sleep(retry_after)
                return self._call(method, payload)

            # "message is not modified" — не помилка
            if error_code == 400 and "not modified" in description:
                log.debug("Telegram %s: message not modified", method)
                return True

            log.warning("Telegram %s: %s", method, result)
            return False

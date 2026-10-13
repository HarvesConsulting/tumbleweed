"""Надсилання вакансій користувачам у Telegram."""
from __future__ import annotations

import logging

from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode

from tumbleweed.config import settings

log = logging.getLogger(__name__)


def _rentalert_url(chat_id: str) -> str:
    """Посилання на RentAlert-бота з передзаповненим chat_id."""
    return f"{settings.rentalert_bot_url}?start=from_tumbleweed_{chat_id}"


def _format_vacancy(v: dict, rentalert_url: str) -> tuple[str, InlineKeyboardMarkup]:
    """Формує текст повідомлення і клавіатуру для однієї вакансії."""
    title = (v.get("title") or "").strip()
    company = v.get("company") or ""
    salary = v.get("salary") or ""
    city = v.get("city_slug") or ""
    job_type = v.get("job_type") or ""
    link = v.get("link") or ""

    lines = [f"💼 *{title}*", ""]
    if company:
        lines.append(f"🏢 {company}")
    if salary:
        lines.append(f"💰 {salary}")
    if city:
        lines.append(f"📍 {city}")
    if job_type:
        lines.append(f"🕐 {job_type}")

    text = "\n".join(lines)

    buttons = []
    if link:
        buttons.append([InlineKeyboardButton("🔗 Відкрити вакансію", url=link)])
    buttons.append([
        InlineKeyboardButton("🏠 Житло тут", url=rentalert_url),
        InlineKeyboardButton("🚫 Ігнор", callback_data=f"action:ignore:{v['id']}"),
    ])
    return text, InlineKeyboardMarkup(buttons)


class Notifier:
    """Надсилач повідомлень у Telegram."""

    def __init__(self) -> None:
        if not settings.bot_token:
            raise RuntimeError("TUMBLEWEED_BOT_TOKEN не задано")
        self._bot = Bot(token=settings.bot_token)

    async def send_vacancy(self, chat_id: str, v: dict) -> bool:
        """Надіслати одну вакансію. True, якщо успішно."""
        text, keyboard = _format_vacancy(v, _rentalert_url(chat_id))
        try:
            await self._bot.send_message(
                chat_id=chat_id,
                text=text,
                reply_markup=keyboard,
                parse_mode=ParseMode.MARKDOWN,
                disable_web_page_preview=True,
            )
            return True
        except Exception as e:
            log.warning("Не вдалось надіслати вакансію %s → %s: %s", v.get("id"), chat_id, e)
            return False

    async def send_text(self, chat_id: str, text: str) -> bool:
        """Надіслати просте текстове повідомлення."""
        try:
            await self._bot.send_message(chat_id=chat_id, text=text)
            return True
        except Exception as e:
            log.warning("Не вдалось надіслати текст → %s: %s", chat_id, e)
            return False

    async def close(self) -> None:
        """Закрити Bot. Якщо Telegram відповідає 429 — ігноруємо."""
        try:
            await self._bot.close()
        except Exception as e:
            log.debug("Не вдалось коректно закрити Bot: %s", e)

"""Ініціалізація Telegram-бота TumbleWeed."""
from __future__ import annotations

import logging

from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters as f,
)

from tumbleweed.config import settings

from .handlers import (
    # командні хендлери
    cmd_cancel,
    cmd_help,
    cmd_resume,
    cmd_settings,
    cmd_start,
    cmd_stop,
    build_conversation_handler,
    # reply-кнопки
    on_btn_help,
    on_btn_my_profile,
    on_btn_my_vacancies,
    on_btn_rent_reply,
    on_btn_toggle,
    # inline-callback (ігнор)
    on_ignore_vacancy,
)
from .keyboards import (
    BTN_CHANGE,
    BTN_HELP,
    BTN_MY_PROFILE,
    BTN_MY_VACANCIES,
    BTN_RENT,
    BTN_TOGGLE_OFF,
    BTN_TOGGLE_ON,
)

log = logging.getLogger(__name__)


def build_application() -> Application:
    """Створити Application з усіма хендлерами."""
    if not settings.bot_token:
        raise RuntimeError(
            "TUMBLEWEED_BOT_TOKEN не задано. Перевір .env"
        )

    app = Application.builder().token(settings.bot_token).build()

    # 1. ConversationHandler — основний флоу /start → ... → DONE
    app.add_handler(build_conversation_handler())

    # 2. Окремі команди на верхньому рівні (працюють поза діалогом)
    app.add_handler(CommandHandler("settings", cmd_settings))
    app.add_handler(CommandHandler("stop", cmd_stop))
    app.add_handler(CommandHandler("resume", cmd_resume))
    app.add_handler(CommandHandler("cancel", cmd_cancel))
    app.add_handler(CommandHandler("help", cmd_help))

    # 3. Кнопка «🚫 Ігнор» під вакансіями (поза діалогом)
    app.add_handler(
        CallbackQueryHandler(on_ignore_vacancy, pattern=r"^action:ignore_vacancy:")
    )

    # 4. Reply-кнопки (працюють завжди)
    # BTN_CHANGE обробляється як entry_point у ConversationHandler,
    # тому тут його НЕ реєструємо.
    app.add_handler(MessageHandler(f.Text([BTN_MY_VACANCIES]), on_btn_my_vacancies))
    app.add_handler(MessageHandler(f.Text([BTN_MY_PROFILE]), on_btn_my_profile))
    app.add_handler(MessageHandler(f.Text([BTN_RENT]), on_btn_rent_reply))
    app.add_handler(
        MessageHandler(f.Text([BTN_TOGGLE_ON, BTN_TOGGLE_OFF]), on_btn_toggle)
    )
    app.add_handler(MessageHandler(f.Text([BTN_HELP]), on_btn_help))

    log.info("✅ TumbleWeed bot побудовано: %d handlers", len(app.handlers[0]))
    return app


async def run_polling() -> None:
    """Запуск у режимі polling — для dev/локального тесту."""
    import asyncio

    app = build_application()
    log.info("🚀 Запускаємо polling...")
    await app.initialize()
    await app.start()
    await app.updater.start_polling(drop_pending_updates=True)
    log.info("✅ Бот запущений. Ctrl+C для зупинки.")
    stop_event = asyncio.Event()
    try:
        await stop_event.wait()
    finally:
        await app.updater.stop()
        await app.stop()
        await app.shutdown()

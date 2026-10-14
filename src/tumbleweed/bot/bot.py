"""Ініціалізація Telegram-бота TumbleWeed."""
from __future__ import annotations

import logging

from telegram.ext import Application, CommandHandler

from tumbleweed.config import settings

from .handlers import (
    build_conversation_handler,
    cmd_cancel,
    cmd_resume,
    cmd_settings,
    cmd_start,
    cmd_stop,
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

    # 3. Кнопка «🚫 Ігнор» під вакансіями (поза діалогом)
    from telegram.ext import CallbackQueryHandler
    from .handlers import on_ignore_vacancy
    app.add_handler(
        CallbackQueryHandler(on_ignore_vacancy, pattern=r"^action:ignore_vacancy:")
    )
    
    # 4. Reply-кнопки (працюють завжди)
    # BTN_CHANGE обробляється як entry_point у ConversationHandler,
    # тому тут його НЕ реєструємо.
    from telegram.ext import MessageHandler, filters as f
    from .handlers import (
        on_btn_my_job,
        on_btn_toggle,
        on_btn_rent,
        BTN_MY_JOB,
        BTN_TOGGLE_ON,
        BTN_TOGGLE_OFF,
        BTN_RENT,
    )
    app.add_handler(MessageHandler(f.Text([BTN_MY_JOB]), on_btn_my_job))
    app.add_handler(MessageHandler(f.Text([BTN_TOGGLE_ON, BTN_TOGGLE_OFF]), on_btn_toggle))
    app.add_handler(MessageHandler(f.Text([BTN_RENT]), on_btn_rent))

    log.info("✅ TumbleWeed bot побудовано: %d handlers", len(app.handlers[0]))
    return app


async def run_polling() -> None:
    """Запуск у режимі polling — для dev/локального тесту."""
    app = build_application()
    log.info("🚀 Запускаємо polling...")
    await app.initialize()
    await app.start()
    await app.updater.start_polling(drop_pending_updates=True)
    log.info("✅ Бот запущений. Ctrl+C для зупинки.")
    # Тримаємо процес, поки не зупинять
    import asyncio
    stop_event = asyncio.Event()
    try:
        await stop_event.wait()
    finally:
        await app.updater.stop()
        await app.stop()
        await app.shutdown()

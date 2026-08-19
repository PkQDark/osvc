"""Точка входа: init bot, storage, scheduler, run (см. BOT_DESIGN.md §6)."""

from __future__ import annotations

import asyncio
import logging

from telegram.ext import Application

from bot.config import Config, load_config
from bot.handlers import register_handlers
from bot.scheduler import send_reminders, setup_scheduler
from bot.storage import Storage

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
# httpx логирует полный URL запроса на уровне INFO, а PTB встраивает токен
# бота прямо в URL (.../bot<TOKEN>/...) — без этого токен утекал бы в логи
# при каждом запросе, что прямо запрещено §8.
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


async def _post_init(application: Application) -> None:
    """Запускается PTB внутри уже работающего event loop — здесь безопасно
    и слать первое напоминание (§4, §9.3), и стартовать AsyncIOScheduler."""
    storage: Storage = application.bot_data["storage"]
    config: Config = application.bot_data["config"]

    logger.info("Стартовый прогон рассылки напоминаний")
    await send_reminders(application, storage, config.payment_account)

    scheduler = setup_scheduler(
        application, storage, config.timezone, config.reminder_hours, config.payment_account
    )
    scheduler.start()
    application.bot_data["scheduler"] = scheduler
    logger.info("Планировщик запущен: часы=%s, TZ=%s", config.reminder_hours, config.timezone)


async def _post_shutdown(application: Application) -> None:
    """Тоже внутри ещё живого event loop — корректно гасим планировщик и БД."""
    scheduler = application.bot_data.get("scheduler")
    if scheduler is not None:
        scheduler.shutdown(wait=False)
        # AsyncIOScheduler.shutdown() defers the actual work via
        # call_soon_threadsafe — yield once so it runs before the loop closes.
        await asyncio.sleep(0)
    storage: Storage = application.bot_data["storage"]
    storage.close()


def main() -> None:
    config = load_config()
    storage = Storage(config.db_path, config.csv_path)
    storage.sync_csv(force=True)

    application = (
        Application.builder()
        .token(config.token)
        .post_init(_post_init)
        .post_shutdown(_post_shutdown)
        .build()
    )
    application.bot_data["storage"] = storage
    application.bot_data["config"] = config
    register_handlers(application)

    logger.info("Бот запускается...")
    application.run_polling()


if __name__ == "__main__":
    main()

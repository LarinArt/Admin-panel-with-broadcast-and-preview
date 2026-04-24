import sys
import os
import asyncio
import logging

# Настройка путей
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

from app.bot.i18n import I18nMiddleware
from app.database.engine import init_models
from app.config import get_settings
from app.services.scheduler import build_scheduler
from app.bot.handlers import admin_router, client_router 

def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )

async def main() -> None:
    setup_logging()
    logger = logging.getLogger(__name__)
    settings = get_settings()
    print(f"Загружен токен: {settings.bot_token[:10]}...") 
    print(f"Интервал шедулера: {settings.scheduler_poll_seconds} сек.")

    # 1. Инициализируем базу данных
    await init_models()

    # 2. Настраиваем бота и диспетчер
    bot = Bot(token=settings.bot_token)
    dp = Dispatcher(storage=MemoryStorage())
    dp.update.middleware(I18nMiddleware())

    # 3. Регистрируем роутеры
    dp.include_router(admin_router)
    dp.include_router(client_router)
    
    # 4. Запускаем планировщик напоминаний
    scheduler = build_scheduler(bot)
    scheduler.start()

    logger.info("🚀 Бот запущен и готов к работе!")

    try:
        # Пропускаем накопившиеся сообщения и запускаем пуллинг
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot)
    except Exception as e:
        logger.exception("Критическая ошибка при работе бота: %s", e)
    finally:
        # Корректное завершение
        scheduler.shutdown(wait=False)
        await bot.session.close()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.info("Бот остановлен вручную.")
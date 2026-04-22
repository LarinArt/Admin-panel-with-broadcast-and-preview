import sys
import os
import asyncio
import logging

# Настройка путей (чтобы Python видел папку app)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

# ИСПРАВЛЕННЫЕ ИМПОРТЫ
# Импортируем SessionLocal и переименовываем его в session_maker для удобства
from app.database.engine import SessionLocal as session_maker, init_models
from app.config import get_settings
from app.services.scheduler import build_scheduler
from app.bot.handlers import admin_router, client_router 

# --- ДАЛЕЕ ВЕСЬ ОСТАЛЬНОЙ КОД БЕЗ ИЗМЕНЕНИЙ ---

def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )

async def main() -> None:
    setup_logging()
    settings = get_settings()

    await init_models()

    bot = Bot(token=settings.bot_token)
    dp = Dispatcher(storage=MemoryStorage())

    # Регистрация роутера админки
    dp.include_router(admin_router)
    dp.include_router(client_router)
    
    scheduler = build_scheduler(bot)
    scheduler.start()

    print("🚀 Бот запущен! Кнопка 'Добавить услугу' теперь должна работать.")

    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot)
    finally:
        scheduler.shutdown(wait=False)
        await bot.session.close()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.info("Бот остановлен!")
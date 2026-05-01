import asyncio
import sys
sys.path.insert(0, '.')

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from app.bot.i18n import I18nMiddleware
from app.database.engine import init_models
from app.config import get_settings

async def test_bot_startup():
    print("Getting settings...")
    settings = get_settings()
    print(f"Token: {settings.bot_token[:10]}...")
    
    print("Initializing DB...")
    await init_models()
    print("DB OK")
    
    print("Creating Bot instance...")
    bot = Bot(token=settings.bot_token)
    print("Bot created OK")
    
    print("Creating Dispatcher...")
    dp = Dispatcher(storage=MemoryStorage())
    dp.update.middleware(I18nMiddleware())
    print("Dispatcher created OK")
    
    # Don't actually start polling or delete webhook - just check up to here
    print("Bot would start polling now (skipped)")
    
    await bot.session.close()

try:
    asyncio.run(test_bot_startup())
except Exception as e:
    print(f"ERROR: {e}")
    import traceback
    traceback.print_exc()

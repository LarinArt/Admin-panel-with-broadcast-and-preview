import asyncio
from aiogram import Bot

async def test():
    bot = Bot(token="8763790576:AAGz-qxmr_9ipSXKKvng2nszOwa6968PuBk")
    try:
        me = await asyncio.wait_for(bot.get_me(), timeout=5.0)
        print(f"Bot: {me.first_name} @{me.username}")
    except asyncio.TimeoutError:
        print("TIMEOUT: Telegram API not responding within 5s")
    except Exception as e:
        print(f"ERROR: {e}")
    finally:
        await bot.session.close()

asyncio.run(test())

import asyncio
from aiogram import Bot

async def test():
    token = "8763790576:AAGz-qxmr_9ipSXKKvng2nszOwa6968PuBk"
    b = Bot(token=token)
    try:
        me = await b.get_me()
        print(f"Bot OK: {me.first_name} @{me.username} (id={me.id})")
    except Exception as e:
        print(f"Error: {e}")
    finally:
        await b.session.close()

asyncio.run(test())

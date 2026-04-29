from aiogram import Router, types
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from sqlalchemy import select

from app.database.engine import SessionLocal
from app.database.models import Tenant

start_router = Router()


@start_router.message(lambda msg: msg.text and msg.text.startswith('/start'))
async def start_command(message: types.Message):
    async with SessionLocal() as session:
        # Get the bot token from the message (which is the same as the bot's token)
        bot_token = message.bot.token
        # Find the tenant by bot_token
        stmt = select(Tenant).where(Tenant.bot_token == bot_token)
        tenant = await session.scalar(stmt)
        
        if tenant:
            tenant_id = tenant.id
            # Construct the URL for the Mini App
            # Using ngrok tunnel for development
            url = f"https://silica-getup-fox.ngrok-free.dev?startapp=tenant_{tenant_id}"
            
            # Create the web app button
            web_app_info = WebAppInfo(url=url)
            button = InlineKeyboardButton(
                text="Відкрити Меню",
                web_app=web_app_info
            )
            keyboard = InlineKeyboardMarkup(inline_keyboard=[[button]])
            
            await message.answer(
                "Вітаємо! Натисніть кнопку нижче, щоб відкрити меню записів:",
                reply_markup=keyboard
            )
        else:
            await message.answer(
                "Помилка: не вдалося знайти інформацію про салон. "
                "Зверніться до администратора для настройки бота."
            )
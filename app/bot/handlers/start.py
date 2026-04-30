from aiogram import Router, types
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from sqlalchemy import select

from app.database.engine import SessionLocal
from app.database.models import Tenant
from app.bot.i18n import i18n

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


async def send_subscription_expired_message(
    event: types.Message | types.CallbackQuery,
    user_role: str,
    tenant: Tenant,
    lang: str,
    i18n_obj: object,
) -> None:
    """Send role-specific message when subscription is expired."""
    bot = event.bot if hasattr(event, 'bot') else None
    if not bot:
        # Try to get bot from event data
        bot = getattr(event, 'bot', None)
        if not bot and hasattr(event, '__dict__'):
            bot = event.__dict__.get('bot')
    if not bot:
        # For start command, we can get bot from message
        if isinstance(event, types.Message):
            bot = event.bot
    
    if not bot:
        # Last resort - try to get from global (not ideal but works in context)
        import app.bot.handlers.start as start_module
        bot = getattr(start_module, 'bot_instance', None)
    
    if not bot:
        # If we still don't have bot, we can't send message
        return

    # Get chat ID from event
    if isinstance(event, types.Message):
        chat_id = event.chat.id
    elif isinstance(event, types.CallbackQuery):
        chat_id = event.message.chat.id if event.message else None
    else:
        chat_id = None
    
    if not chat_id:
        return

    # Get localized messages
    if user_role == "super_admin":
        message_text = i18n_obj.t(
            "subscription.expired.master_admin",
            lang=lang,
            tenant_name=tenant.name,
        )
    elif user_role in ("admin", "master"):
        message_text = i18n_obj.t(
            "subscription.expired.admin_master",
            lang=lang,
            tenant_name=tenant.name,
        )
    else:  # client and other roles
        message_text = i18n_obj.t(
            "subscription.expired.client",
            lang=lang,
            tenant_name=tenant.name,
        )

    try:
        await bot.send_message(chat_id=chat_id, text=message_text)
    except Exception as e:
        # Log error but don't break the flow
        pass
    if 'button' in locals() or 'button' in globals(): # Проверка, что кнопка создана
        keyboard = InlineKeyboardMarkup(inline_keyboard=[[button]])
        await event.answer(
            "Вітаємо! Натисніть кнопку нижче, щоб відкрити меню записів:",
            reply_markup=keyboard
        )
    else:
        await event.answer(
            "Помилка: не вдалося знайти інформацію про салон. "
            "Зверніться до адміністратора для настройки бота."
        )
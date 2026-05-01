import asyncio
from app.database.engine import init_models, SessionLocal
from app.database.models import User, UserRole
from sqlalchemy import select

async def make_super_admin_by_phone():
    await init_models()
    async with SessionLocal() as session:
        # Ищем пользователя по номеру телефона
        phone = "+38(050)952-52-23"  # формат из базы: +38(0xx)xxx-xx-xx
        user = await session.scalar(select(User).where(User.phone_number == phone))
        
        if not user:
            # Попробуем другие варианты формата
            phone_variants = [
                "+38(050)952-52-23",
                "+380509525223",
                "0509525223",
                "380509525223",
            ]
            for p in phone_variants:
                user = await session.scalar(select(User).where(User.phone_number == p))
                if user:
                    print(f"Found with phone format: {p}")
                    break
        
        if user:
            print(f"Found user: id={user.id}, telegram_id={user.telegram_id}, phone={user.phone_number}, current_role={user.role}")
            user.role = UserRole.SUPER_ADMIN
            await session.commit()
            print(f"✅ Role updated to SUPER_ADMIN for user with phone {user.phone_number}")
            print(f"   You can now use /admin in Telegram bot")
        else:
            print("❌ User with that phone number not found in database")
            print("Available users:")
            result = await session.scalars(select(User))
            for u in result.all():
                print(f"  id={u.id}, telegram_id={u.telegram_id}, phone={u.phone_number}, role={u.role}")

asyncio.run(make_super_admin_by_phone())

import asyncio
from app.database.engine import init_models, SessionLocal
from app.database.models import User, UserRole
from sqlalchemy import select

async def fix_role():
    await init_models()
    async with SessionLocal() as session:
        user = await session.scalar(select(User).where(User.telegram_id == 123456789))
        if user:
            print(f"Found user: telegram_id={user.telegram_id}, current_role={user.role}")
            user.role = UserRole.SUPER_ADMIN
            await session.commit()
            print(f"Role changed to: {user.role}")
            print("SUCCESS: User is now SUPER_ADMIN")
        else:
            print("ERROR: User not found")

asyncio.run(fix_role())

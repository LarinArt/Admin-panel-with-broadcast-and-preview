import asyncio
from sqlalchemy import select
# Добавь импорт Base
from app.database.models import User, UserRole, Base
from app.database.engine import SessionLocal, engine

async def add_test_users():
    # ЭТА СТРОЧКА ПРИНУДИТЕЛЬНО СОЗДАСТ ТАБЛИЦЫ, ЕСЛИ ИХ НЕТ
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with SessionLocal() as session:
        test_ids = [123456789, 987654321, 555666777]
        
        print("🚀 Синхронизация структуры и данных...")
        
        for t_id in test_ids:
            res = await session.execute(select(User).where(User.telegram_id == t_id))
            if not res.scalar():
                new_user = User(
                    telegram_id=t_id,
                    full_name=f"Тестовый Клиент {t_id}",
                    role=UserRole.CLIENT,
                    is_active=True # Теперь колонка точно будет существовать
                )
                session.add(new_user)
                print(f"✅ Добавлен: {t_id}")
            else:
                print(f"⏺️ Уже в базе: {t_id}")
        
        await session.commit()
        print("\n✨ Теперь база полностью соответствует коду!")

if __name__ == "__main__":
    asyncio.run(add_test_users())
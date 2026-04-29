"""Простой скрипт для проверки и обновления схемы БД используя существующий async engine"""
import asyncio
from app.database.engine import engine
from sqlalchemy import text

async def check_and_update_schema():
    async with engine.connect() as conn:
        # Проверяем существование колонки plan_name в таблице tenants
        result = await conn.execute(text("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name = 'tenants' AND column_name = 'plan_name'
        """))
        plan_name_exists = result.fetchone() is not None
        
        if not plan_name_exists:
            print("Добавляем колонку plan_name в таблицу tenants...")
            await conn.execute(text("""
                ALTER TABLE tenants ADD COLUMN plan_name VARCHAR(50) DEFAULT 'base'
            """))
            await conn.commit()
            print("✅ Колонка plan_name добавлена")
        else:
            print("ℹ️ Колонка plan_name уже существует")
            
        # Проверяем существование колонки subscription_ends_at
        result = await conn.execute(text("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name = 'tenants' AND column_name = 'subscription_ends_at'
        """))
        subscription_ends_at_exists = result.fetchone() is not None
        
        if not subscription_ends_at_exists:
            print("Добавляем колонку subscription_ends_at в таблицу tenants...")
            await conn.execute(text("""
                ALTER TABLE tenants ADD COLUMN subscription_ends_at TIMESTAMP WITH TIME ZONE
            """))
            await conn.commit()
            print("✅ Колонка subscription_ends_at добавлена")
        else:
            print("ℹ️ Колонка subscription_ends_at уже существует")
            
        # Проверяем существование таблицы payments
        result = await conn.execute(text("""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_name = 'payments'
        """))
        payments_table_exists = result.fetchone() is not None
        
        if not payments_table_exists:
            print("Создаем таблицу payments...")
            await conn.execute(text("""
                CREATE TABLE payments (
                    id SERIAL PRIMARY KEY,
                    tenant_id INTEGER REFERENCES tenants(id) ON DELETE CASCADE,
                    amount INTEGER NOT NULL,
                    status VARCHAR(20) NOT NULL,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
                )
            """))
            await conn.commit()
            print("✅ Таблица payments создана")
        else:
            print("ℹ️ Таблица payments уже существует")
            
        # Проверяем существование индекса
        result = await conn.execute(text("""
            SELECT indexname 
            FROM pg_indexes 
            WHERE tablename = 'tenants' AND indexname = 'idx_tenant_subscription_ends'
        """))
        index_exists = result.fetchone() is not None
        
        if not index_exists:
            print("Создаем индекс idx_tenant_subscription_ends на таблице tenants...")
            await conn.execute(text("""
                CREATE INDEX idx_tenant_subscription_ends ON tenants (id, subscription_ends_at)
            """))
            await conn.commit()
            print("✅ Индекс idx_tenant_subscription_ends создан")
        else:
            print("ℹ️ Индекс idx_tenant_subscription_ends уже существует")

async def main():
    try:
        await check_and_update_schema()
        print("\n🎉 Проверка и обновление схемы БД завершено!")
    except Exception as e:
        print(f"\n❌ Ошибка при работе с БД: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
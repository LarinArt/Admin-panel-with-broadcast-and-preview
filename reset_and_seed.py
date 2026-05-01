import asyncio
import sys

if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

from app.database.engine import init_models, SessionLocal, engine
from app.database.models import Service, Tenant
from sqlalchemy import select, text

async def reset_db():
    # Удалим таблицы и создадим заново
    async with engine.begin() as conn:
        await conn.run_sync(lambda sync_conn: sync_conn.execute(text("DROP TABLE IF EXISTS services")))
        await conn.run_sync(lambda sync_conn: sync_conn.execute(text("DROP TABLE IF EXISTS users")))
        await conn.run_sync(lambda sync_conn: sync_conn.execute(text("DROP TABLE IF EXISTS appointments")))
        await conn.run_sync(lambda sync_conn: sync_conn.execute(text("DROP TABLE IF EXISTS schedules")))
        await conn.run_sync(lambda sync_conn: sync_conn.execute(text("DROP TABLE IF EXISTS masters")))
        await conn.run_sync(lambda sync_conn: sync_conn.execute(text("DROP TABLE IF EXISTS organizations")))
        await conn.run_sync(lambda sync_conn: sync_conn.execute(text("DROP TABLE IF EXISTS tenants")))
        print("Таблицы удалены")

    # Пересоздаем все таблицы
    await init_models()
    print("Таблицы созданы заново")

    async with SessionLocal() as session:
        tenant = await session.scalar(select(Tenant).limit(1))
        print(f"Tenant: id={tenant.id}, name={tenant.name}")

        services = [
            Service(name="Стрижка", duration_minutes=30, price=200.0, tenant_id=tenant.id),
            Service(name="Укладка", duration_minutes=45, price=300.0, tenant_id=tenant.id),
            Service(name="Окрашивание", duration_minutes=60, price=500.0, tenant_id=tenant.id),
        ]
        session.add_all(services)
        await session.commit()
        print(f"Добавлено {len(services)} услуг")

        # Проверим, что считали обратно
        result = await session.scalars(select(Service))
        for s in result.all():
            print(f"  [{s.id}] {s.name} - {s.price} uah, {s.duration_minutes} min")

if __name__ == "__main__":
    asyncio.run(reset_db())

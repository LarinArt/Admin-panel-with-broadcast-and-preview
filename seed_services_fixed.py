import asyncio
import sys

# Force UTF-8 encoding for stdout (Windows fix)
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

from app.database.engine import init_models, SessionLocal
from app.database.models import Service, Tenant
from sqlalchemy import select

async def seed_services():
    await init_models()
    print("База инициализирована")

    async with SessionLocal() as session:
        tenant = await session.scalar(select(Tenant).limit(1))
        if not tenant:
            print("ОШИБКА: Нет tenant в базе")
            return

        print(f"Найден tenant: id={tenant.id}, name='{tenant.name}'")

        existing = await session.scalars(select(Service).where(Service.tenant_id == tenant.id))
        if existing.first():
            print("Услуги уже есть")
            return

        # Unicode strings (UTF-8)
        services = [
            Service(name="Стрижка", duration_minutes=30, price=200.0, tenant_id=tenant.id),
            Service(name="Укладка", duration_minutes=45, price=300.0, tenant_id=tenant.id),
            Service(name="Окрашивание", duration_minutes=60, price=500.0, tenant_id=tenant.id),
        ]
        session.add_all(services)
        await session.commit()
        print(f"Добавлено {len(services)} услуг:")
        for s in services:
            print(f"   - {s.name}: {s.price} uah, {s.duration_minutes} min")

if __name__ == "__main__":
    asyncio.run(seed_services())

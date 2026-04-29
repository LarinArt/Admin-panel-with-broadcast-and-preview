import asyncio
from app.database.engine import SessionLocal
from app.database.models import Tenant, Service
from sqlalchemy import select

async def ensure_data():
    async with SessionLocal() as session:
        # ensure tenant exists
        tenant = await session.get(Tenant, 1)
        if not tenant:
            tenant = Tenant(id=1, name="Demo Tenant", bot_token="123456:ABC", is_active=True)
            session.add(tenant)
            await session.commit()
        # ensure some services
        result = await session.execute(select(Service).where(Service.tenant_id == 1))
        services = result.scalars().all()
        if not services:
            services = [
                Service(tenant_id=1, name="Стрижка", duration_minutes=30, price=200.0),
                Service(tenant_id=1, name="Укладка", duration_minutes=45, price=150.0),
                Service(tenant_id=1, name="Окрашивание", duration_minutes=60, price=500.0),
            ]
            session.add_all(services)
            await session.commit()
        print("Data ensured")

if __name__ == "__main__":
    asyncio.run(ensure_data())
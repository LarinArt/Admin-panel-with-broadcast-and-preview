from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings
from app.database.models import Base, Tenant

settings = get_settings()

engine = create_async_engine(settings.database_url, pool_pre_ping=True, pool_recycle=3600)
SessionLocal = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)


async def init_models() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with SessionLocal() as session:
        tenant_exists = await session.scalar(select(Tenant.id).limit(1))
        if tenant_exists:
            return

        default_tenant = Tenant(
            name="Default Tenant",
            bot_token=settings.bot_token,
            is_active=True,
        )
        session.add(default_tenant)
        await session.commit()

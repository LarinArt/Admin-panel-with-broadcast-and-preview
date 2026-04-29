import asyncio
import sys
sys.path.insert(0, '.')

from app.database.engine import SessionLocal
from app.database.models import Tenant
from app.config import get_settings

async def check_tenant():
    async with SessionLocal() as session:
        # Get the bot token from settings
        settings = get_settings()
        bot_token = settings.bot_token
        print(f'Searching for tenant with bot_token: {bot_token}')
        
        from sqlalchemy import select
        stmt = select(Tenant).where(Tenant.bot_token == bot_token)
        result = await session.execute(stmt)
        tenant = result.scalar_one_or_none()
        
        if tenant:
            print(f'Found tenant: ID={tenant.id}, Name="{tenant.name}", Bot Token={tenant.bot_token[:20]}...')
            print(f'Tenant is active: {tenant.is_active}')
        else:
            print('No tenant found with this bot token')
            # Let's see what tenants we have
            all_tenants = await session.execute(select(Tenant))
            tenants = all_tenants.scalars().all()
            print(f'Found {len(tenants)} total tenants:')
            for t in tenants:
                print(f'  - ID={t.id}, Name="{t.name}", Bot Token={t.bot_token[:20] if t.bot_token else "None"}...')

if __name__ == "__main__":
    asyncio.run(check_tenant())
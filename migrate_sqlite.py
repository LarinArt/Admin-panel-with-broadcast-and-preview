import asyncio
from app.database.engine import engine
from sqlalchemy import text

async def migrate_sqlite():
    async with engine.connect() as conn:
        # Check if plan_name column exists in tenants
        result = await conn.execute(text("PRAGMA table_info(tenants)"))
        columns = [row[1] for row in result.fetchall()]  # row[1] is column name
        if 'plan_name' not in columns:
            print("Adding column plan_name to tenants...")
            await conn.execute(text("ALTER TABLE tenants ADD COLUMN plan_name VARCHAR(50) DEFAULT 'base'"))
            await conn.commit()
            print("Added plan_name")
        else:
            print("plan_name already exists")
        
        # Check subscription_ends_at
        if 'subscription_ends_at' not in columns:
            print("Adding column subscription_ends_at to tenants...")
            await conn.execute(text("ALTER TABLE tenants ADD COLUMN subscription_ends_at TIMESTAMP"))
            await conn.commit()
            print("Added subscription_ends_at")
        else:
            print("subscription_ends_at already exists")
        
        # Check if payments table exists
        result = await conn.execute(text("SELECT name FROM sqlite_master WHERE type='table' AND name='payments'"))
        if not result.fetchone():
            print("Creating payments table...")
            await conn.execute(text("""
                CREATE TABLE payments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tenant_id INTEGER NOT NULL,
                    amount INTEGER NOT NULL,
                    status VARCHAR(20) NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (tenant_id) REFERENCES tenants (id) ON DELETE CASCADE
                )
            """))
            await conn.commit()
            print("Created payments table")
        else:
            print("Payments table already exists")
        
        # Check index on tenants (id, subscription_ends_at)
        try:
            await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_tenant_subscription_ends ON tenants (id, subscription_ends_at)"))
            await conn.commit()
            print("Ensured index idx_tenant_subscription_ends exists")
        except Exception as e:
            print(f"Index creation skipped or already exists: {e}")

async def main():
    await migrate_sqlite()
    print("Migration completed")

if __name__ == "__main__":
    asyncio.run(main())
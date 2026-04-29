"""Migration script to add billing-related columns and tables"""
import sys
from sqlalchemy import create_engine, text
from app.config import get_settings

def get_sync_engine():
    """Create a synchronous engine from the async database URL"""
    settings = get_settings()
    # Convert postgresql+asyncpg:// to postgresql://
    url = settings.database_url
    if url.startswith("postgresql+asyncpg"):
        url = url.replace("postgresql+asyncpg", "postgresql")
    return create_engine(url)

def migrate():
    engine = get_sync_engine()
    with engine.connect() as conn:
        # Add plan_name column to tenants table if it doesn't exist
        try:
            conn.execute(text(
                "ALTER TABLE tenants ADD COLUMN plan_name VARCHAR(50) DEFAULT 'base'"
            ))
            print("✅ Added column 'plan_name' to tenants table")
        except Exception as e:
            if "already exists" in str(e):
                print("ℹ️ Column 'plan_name' already exists in tenants table")
            else:
                raise e

        # Add subscription_ends_at column to tenants table if it doesn't exist
        try:
            conn.execute(text(
                "ALTER TABLE tenants ADD COLUMN subscription_ends_at TIMESTAMP WITH TIME ZONE"
            ))
            print("✅ Added column 'subscription_ends_at' to tenants table")
        except Exception as e:
            if "already exists" in str(e):
                print("ℹ️ Column 'subscription_ends_at' already exists in tenants table")
            else:
                raise e

        # Create payments table if it doesn't exist
        try:
            conn.execute(text("""
                CREATE TABLE payments (
                    id SERIAL PRIMARY KEY,
                    tenant_id INTEGER REFERENCES tenants(id) ON DELETE CASCADE,
                    amount INTEGER NOT NULL,
                    status VARCHAR(20) NOT NULL,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
                )
            """))
            print("✅ Created payments table")
        except Exception as e:
            if "already exists" in str(e):
                print("ℹ️ Payments table already exists")
            else:
                raise e

        # Create index on tenants (id, subscription_ends_at) if it doesn't exist
        try:
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS idx_tenant_subscription_ends ON tenants (id, subscription_ends_at)"
            ))
            print("✅ Created index 'idx_tenant_subscription_ends' on tenants table")
        except Exception as e:
            if "already exists" in str(e):
                print("ℹ️ Index 'idx_tenant_subscription_ends' already exists")
            else:
                raise e

        conn.commit()

if __name__ == "__main__":
    try:
        migrate()
        print("\n🎉 Database migration completed successfully!")
    except Exception as e:
        print(f"\n❌ Migration failed: {e}")
        sys.exit(1)
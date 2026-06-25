from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from app.core.config import settings

engine = create_async_engine(settings.DATABASE_URL, echo=False, pool_size=10)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        yield session


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # ── Schema migrations (idempotent ALTER TABLE for existing DBs) ──────
        migrations = [
            # T85: segment columns added to products and users
            "ALTER TABLE products ADD COLUMN IF NOT EXISTS segment VARCHAR DEFAULT 'ss'",
            "ALTER TABLE users    ADD COLUMN IF NOT EXISTS segment VARCHAR DEFAULT 'ss'",
        ]
        for sql in migrations:
            await conn.execute(__import__("sqlalchemy").text(sql))

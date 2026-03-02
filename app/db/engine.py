"""
Async SQLAlchemy engine.

Vercel serverless functions are ephemeral — each invocation may spin up a new
process.  We therefore keep the pool very small (pool_size=2, max_overflow=3)
so we don't exhaust the upstream PgBouncer / Neon connection limit.
"""
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import get_settings

settings = get_settings()

engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
    pool_size=2,        # keep footprint tiny on serverless
    max_overflow=3,
    pool_pre_ping=True, # validate connections before checkout
    pool_recycle=300,   # recycle stale connections every 5 min
)

AsyncSessionFactory = async_sessionmaker(
    bind=engine,
    expire_on_commit=False,
    class_=AsyncSession,
)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncSession:  # FastAPI dependency
    async with AsyncSessionFactory() as session:
        yield session
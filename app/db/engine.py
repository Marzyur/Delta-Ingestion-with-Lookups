"""
Async SQLAlchemy engine.

Vercel serverless functions are ephemeral — each invocation may spin up a new
process.  We therefore keep the pool very small (pool_size=2, max_overflow=3)
so we don't exhaust the upstream PgBouncer / Neon connection limit.
"""
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from urllib.parse import urlparse, parse_qsl, urlencode, urlunparse

from app.core.config import get_settings

settings = get_settings()

# Ensure async driver is used even if DATABASE_URL is sync-style
database_url = settings.DATABASE_URL
if database_url.startswith("postgresql://") and "+asyncpg" not in database_url:
    database_url = database_url.replace("postgresql://", "postgresql+asyncpg://", 1)

# asyncpg does not accept libpq's sslmode parameter; translate if present
parsed = urlparse(database_url)
if parsed.query:
    query = dict(parse_qsl(parsed.query))
    if "sslmode" in query and "ssl" not in query:
        if query["sslmode"] in {"require", "verify-ca", "verify-full"}:
            query["ssl"] = "require"
        query.pop("sslmode", None)
        parsed = parsed._replace(query=urlencode(query))
        database_url = urlunparse(parsed)

engine = create_async_engine(
    database_url,
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

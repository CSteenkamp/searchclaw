"""Database connection and session management."""

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy import text
from typing import Optional, AsyncGenerator

from api.models.user import Base

_engine = None
_session_factory: Optional[async_sessionmaker] = None


async def init_db(database_url: str):
    """Initialize database engine and create tables."""
    global _engine, _session_factory
    _engine = create_async_engine(database_url, echo=False, pool_size=10, max_overflow=20)
    _session_factory = async_sessionmaker(_engine, expire_on_commit=False)

    # Schema is managed by Alembic migrations (see migrations/)
    # Run: alembic upgrade head


async def close_db():
    """Close database engine."""
    global _engine
    if _engine:
        await _engine.dispose()
        _engine = None


async def ping_db() -> bool:
    """Check PostgreSQL connectivity."""
    if not _engine:
        return False
    try:
        async with _engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Get an async database session."""
    if not _session_factory:
        raise RuntimeError("Database not initialized")
    async with _session_factory() as session:
        yield session

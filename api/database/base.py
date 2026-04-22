# ABOUTME: SQLAlchemy async engine and session factory for the TempleHE API.
# ABOUTME: All database access uses async sessions; pool is configured explicitly.
from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from config import settings

engine = create_async_engine(
    settings.database_url,
    echo=settings.environment == "development",
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
    pool_timeout=30,
    pool_recycle=1800,
)

# Use NullPool for test environments to avoid connection sharing across event loops
test_engine = create_async_engine(
    settings.test_database_url or settings.database_url,
    echo=False,
    poolclass=NullPool,
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

TestAsyncSessionLocal = async_sessionmaker(
    test_engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency — yields an async DB session and commits on success.

    One transaction per request. Services that need multiple transaction
    boundaries (commit → emit event → open new tx) must manage sessions
    explicitly via AsyncSessionLocal() rather than relying on this dep,
    per ADR-012. Kept this shape because it's the right default for
    simple CRUD; the explicit pattern is available where it's needed.
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise

# ABOUTME: Pytest fixtures for integration and unit tests.
# ABOUTME: Provides test database (templehe_test), async session, and FastAPI test client.
from __future__ import annotations

import asyncio
import os
import subprocess
from collections.abc import AsyncGenerator

# Set required env vars before any project imports so Settings() can instantiate.
# These are test-only values — never used in production.
_TEST_DB = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://templehe:devpassword@localhost:5432/templehe_test",
)
os.environ.setdefault("DATABASE_URL", _TEST_DB)
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret-key-minimum-32-chars-long-xx")
os.environ.setdefault("JWT_REFRESH_SECRET", "test-jwt-refresh-secret-min-32-chars-xx")
os.environ.setdefault(
    "TOTP_ENCRYPTION_KEY",
    "dGVzdC10b3RwLWtleS1mb3ItdGVzdGluZy1vbmx5eA==",  # base64, not a real Fernet key
)

import pytest  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy.ext.asyncio import (  # noqa: E402
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool  # noqa: E402

from database.base import get_db  # noqa: E402
from main import app  # noqa: E402

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://templehe:devpassword@localhost:5432/templehe_test",
)


@pytest.fixture(scope="session")
def event_loop_policy():
    return asyncio.DefaultEventLoopPolicy()


@pytest.fixture(scope="session")
async def setup_test_db():
    """Create the test database and run all migrations once per test session."""
    # Run alembic migrations against the test database
    env = {**os.environ, "DATABASE_URL": TEST_DATABASE_URL}
    result = subprocess.run(
        ["uv", "run", "alembic", "upgrade", "head"],
        env=env,
        capture_output=True,
        text=True,
        cwd=os.path.dirname(os.path.dirname(__file__)),
    )
    if result.returncode != 0:
        pytest.fail(f"Alembic migration failed:\n{result.stdout}\n{result.stderr}")
    yield
    # Teardown: downgrade to base to clean up after the session
    result = subprocess.run(
        ["uv", "run", "alembic", "downgrade", "base"],
        env=env,
        capture_output=True,
        text=True,
        cwd=os.path.dirname(os.path.dirname(__file__)),
    )


@pytest.fixture(scope="session")
def test_engine(setup_test_db):
    engine = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool, echo=False)
    yield engine
    asyncio.get_event_loop().run_until_complete(engine.dispose())


@pytest.fixture
async def db_session(test_engine) -> AsyncGenerator[AsyncSession, None]:
    """Async session that rolls back all changes after each test."""
    session_factory = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    async with test_engine.connect() as conn:
        await conn.begin()
        async with session_factory(bind=conn) as session:
            yield session
        await conn.rollback()


@pytest.fixture
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """FastAPI async test client with the test DB injected."""
    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()

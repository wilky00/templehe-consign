# ABOUTME: Alembic migration environment — connects to the target DB and runs migrations.
# ABOUTME: Uses asyncpg driver via SQLAlchemy async; DATABASE_URL is read from the environment.
from __future__ import annotations

import asyncio
import os
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Migrations use DATABASE_DIRECT_URL when set (bypasses PgBouncer on Neon).
# Falls back to DATABASE_URL for local Docker dev where no pooler is involved.
database_url = os.environ.get("DATABASE_DIRECT_URL") or os.environ.get("DATABASE_URL", "")
if not database_url:
    raise RuntimeError("DATABASE_URL environment variable is not set")
config.set_main_option("sqlalchemy.url", database_url)

# Import Base so Alembic can see the metadata for --autogenerate (optional)
from database.models import Base  # noqa: E402

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection):
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

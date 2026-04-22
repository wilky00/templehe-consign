# ABOUTME: Hourly retention sweeper — invoked by the temple-sweeper Fly Machine.
# ABOUTME: Calls fn_sweep_retention() and fn_ensure_audit_partitions() via DATABASE_URL.
from __future__ import annotations

import asyncio
import logging
import os
import sys
from typing import cast

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("retention_sweeper")

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    sys.exit("DATABASE_URL is required.")


async def _sweep(session: AsyncSession) -> None:
    # Ensure monthly partitions for audit_logs exist before deletes run.
    result = await session.execute(text("SELECT fn_ensure_audit_partitions()"))
    created = cast(int, result.scalar_one())
    logger.info("audit_partitions_created count=%d", created)

    # Sweep stale rate-limit counters, expired webhook dedup rows, and old sessions.
    result = await session.execute(text("SELECT * FROM fn_sweep_retention()"))
    for row in result.all():
        table_name, rows_deleted = row
        logger.info("swept table=%s rows_deleted=%d", table_name, rows_deleted)

    await session.commit()


async def main() -> None:
    engine = create_async_engine(DATABASE_URL, poolclass=NullPool, echo=False)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with session_factory() as session:
            await _sweep(session)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())

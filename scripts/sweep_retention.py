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

    # Apply right-to-erasure on accounts past their 30-day grace window.
    result = await session.execute(text("SELECT fn_delete_expired_accounts()"))
    deleted_accounts = cast(int, result.scalar_one())
    logger.info("accounts_scrubbed count=%d", deleted_accounts)

    # PII scrub on audit_logs rows older than the admin-configurable window.
    # Retention is stored as {"days": N, ...} JSONB in app_config; default 30.
    cfg = await session.execute(
        text(
            "SELECT (value->>'days')::int AS days FROM app_config "
            "WHERE key = 'audit_pii_retention_days'"
        )
    )
    days_row = cfg.scalar_one_or_none()
    retention_days = int(days_row) if days_row is not None else 30
    result = await session.execute(
        text("SELECT fn_scrub_audit_pii(:days)"), {"days": retention_days}
    )
    scrubbed = cast(int, result.scalar_one())
    logger.info("audit_pii_scrubbed count=%d retention_days=%d", scrubbed, retention_days)

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

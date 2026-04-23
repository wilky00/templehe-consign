# ABOUTME: Ad-hoc PII scrub on audit_logs — runs fn_scrub_audit_pii(days).
# ABOUTME: The hourly temple-sweeper already does this; use this script only for ad-hoc backfills.
"""Ad-hoc audit_logs PII scrub.

Usage:

    DATABASE_URL=... uv run python scripts/scrub_audit_pii.py [--days N]

``--days`` overrides ``app_config.audit_pii_retention_days`` for this run
(must be in 30..120). Without the flag, uses the configured value.
"""

from __future__ import annotations

import argparse
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
logger = logging.getLogger("audit_pii_scrub")

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    sys.exit("DATABASE_URL is required.")


async def _resolve_days(session: AsyncSession, override: int | None) -> int:
    if override is not None:
        return override
    cfg = await session.execute(
        text(
            "SELECT (value->>'days')::int FROM app_config "
            "WHERE key = 'audit_pii_retention_days'"
        )
    )
    days = cfg.scalar_one_or_none()
    return int(days) if days is not None else 30


async def main(days_override: int | None) -> None:
    engine = create_async_engine(DATABASE_URL, poolclass=NullPool, echo=False)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with session_factory() as session:
            days = await _resolve_days(session, days_override)
            result = await session.execute(
                text("SELECT fn_scrub_audit_pii(:days)"), {"days": days}
            )
            scrubbed = cast(int, result.scalar_one())
            await session.commit()
            logger.info("audit_pii_scrubbed count=%d retention_days=%d", scrubbed, days)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Scrub PII from old audit_logs rows.")
    parser.add_argument(
        "--days",
        type=int,
        default=None,
        help="Override retention days (30..120). Defaults to app_config value.",
    )
    args = parser.parse_args()
    asyncio.run(main(args.days))

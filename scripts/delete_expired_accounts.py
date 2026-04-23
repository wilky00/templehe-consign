# ABOUTME: Ad-hoc trigger for the account-deletion sweep — runs fn_delete_expired_accounts().
# ABOUTME: The hourly temple-sweeper already does this; use this script only for ad-hoc flushes.
"""Finalize accounts whose 30-day grace window has elapsed.

Usage:

    DATABASE_URL=... uv run python scripts/delete_expired_accounts.py
"""

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
logger = logging.getLogger("account_deletion")

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    sys.exit("DATABASE_URL is required.")


async def main() -> None:
    engine = create_async_engine(DATABASE_URL, poolclass=NullPool, echo=False)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with session_factory() as session:
            result = await session.execute(text("SELECT fn_delete_expired_accounts()"))
            deleted = cast(int, result.scalar_one())
            await session.commit()
            logger.info("accounts_scrubbed count=%d", deleted)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())

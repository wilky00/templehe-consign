# ABOUTME: Long-running poller that runs the health probe every 30s.
# ABOUTME: Runs as the temple-health-poller Fly Machine in prod.
"""Health poller — Phase 4 Sprint 7.

Wakes every ``HEALTH_POLL_INTERVAL`` (default 30s), runs
``health_check_service.run_all`` against a fresh DB session, commits.
Writes one row per service to ``service_health_state``; dispatches
admin alerts when a row flips green→red (rate-limited 1/15min).

Environment:
    DATABASE_URL                 (required)
    HEALTH_POLL_INTERVAL         (default: 30) — seconds between probes
    HEALTH_POLLER_SINGLE_PASS    (default: empty) — run one pass + exit
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys
from typing import Any

_HERE = os.path.dirname(os.path.abspath(__file__))
_API_DIR = os.path.join(os.path.dirname(_HERE), "api")
if _API_DIR not in sys.path:
    sys.path.insert(0, _API_DIR)

from sqlalchemy.ext.asyncio import (  # noqa: E402
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool  # noqa: E402

from services import health_check_service  # noqa: E402

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("health_poller")

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    sys.exit("DATABASE_URL is required.")

POLL_INTERVAL = float(os.environ.get("HEALTH_POLL_INTERVAL", "30"))
SINGLE_PASS = bool(os.environ.get("HEALTH_POLLER_SINGLE_PASS"))

_shutdown = asyncio.Event()


def _handle_signal(signum: int, _frame: Any) -> None:
    logger.info("health_poller_shutdown_requested signal=%d", signum)
    _shutdown.set()


async def _run_pass(session_factory: Any) -> None:
    async with session_factory() as session:
        session: AsyncSession = session
        rows = await health_check_service.run_all(session)
        await session.commit()
    logger.info("health_pass_complete count=%d", len(rows))


async def main() -> None:
    engine = create_async_engine(DATABASE_URL, poolclass=NullPool, echo=False)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _handle_signal, sig, None)

    try:
        while not _shutdown.is_set():
            try:
                await _run_pass(session_factory)
            except Exception:
                logger.exception("health_pass_failed")
            if SINGLE_PASS:
                return
            try:
                await asyncio.wait_for(_shutdown.wait(), timeout=POLL_INTERVAL)
            except TimeoutError:
                pass
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())

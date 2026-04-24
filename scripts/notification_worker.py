# ABOUTME: Long-running worker that drains notification_jobs and dispatches email/SMS.
# ABOUTME: Runs as the temple-notifications Fly Machine in prod; can run locally for dev.
"""NotificationService worker loop.

Pulls batches of pending jobs via ``SELECT ... FOR UPDATE SKIP LOCKED``
and dispatches them. Runs until signaled. Multiple instances are safe
to run in parallel — the SKIP LOCKED claim avoids duplicate dispatch.

Environment:
    DATABASE_URL            (required)
    WORKER_POLL_INTERVAL    (default: 5)  — seconds to sleep when the
                                            queue was empty on last poll
    WORKER_BATCH_SIZE       (default: 10)
    WORKER_SINGLE_PASS      (default: empty) — if set, process one batch
                                               and exit (for tests / ad-hoc).
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys
from typing import Any

# Make the api package importable when run from the repo root.
_HERE = os.path.dirname(os.path.abspath(__file__))
_API_DIR = os.path.join(os.path.dirname(_HERE), "api")
if _API_DIR not in sys.path:
    sys.path.insert(0, _API_DIR)

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine  # noqa: E402
from sqlalchemy.pool import NullPool  # noqa: E402

from services import notification_service  # noqa: E402

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("notification_worker")

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    sys.exit("DATABASE_URL is required.")

POLL_INTERVAL = float(os.environ.get("WORKER_POLL_INTERVAL", "5"))
BATCH_SIZE = int(os.environ.get("WORKER_BATCH_SIZE", "10"))
SINGLE_PASS = bool(os.environ.get("WORKER_SINGLE_PASS"))

_shutdown = asyncio.Event()


def _handle_signal(signum: int, frame: Any) -> None:
    logger.info("worker_shutdown_requested signal=%d", signum)
    _shutdown.set()


async def _process_batch(session_factory: Any) -> int:
    """Claim and process a batch. Returns the number of jobs processed."""
    async with session_factory() as session:
        session: AsyncSession = session
        jobs = await notification_service.claim_next_batch(session, limit=BATCH_SIZE)
        if not jobs:
            await session.commit()
            return 0
        # Commit the claim before dispatch so a crash can't dead-lock rows
        # forever — worst case the row stays 'processing' and a human
        # unsticks it (tracked as a known operational concern).
        await session.commit()

    # Dispatch each claimed job in its own session so one slow send doesn't
    # block the others' state transitions.
    processed = 0
    for job in jobs:
        async with session_factory() as session:
            session: AsyncSession = session
            status = await notification_service.process_job(session, job)
            await session.commit()
        logger.info(
            "job_processed id=%s template=%s channel=%s status=%s attempts=%d",
            job.id,
            job.template,
            job.channel,
            status,
            job.attempts,
        )
        processed += 1
    return processed


async def main() -> None:
    engine = create_async_engine(DATABASE_URL, poolclass=NullPool, echo=False)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _handle_signal, sig, None)

    try:
        while not _shutdown.is_set():
            try:
                processed = await _process_batch(session_factory)
            except Exception:
                logger.exception("worker_batch_failed")
                processed = 0
            if SINGLE_PASS:
                return
            if processed == 0:
                try:
                    await asyncio.wait_for(_shutdown.wait(), timeout=POLL_INTERVAL)
                except TimeoutError:
                    pass
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())

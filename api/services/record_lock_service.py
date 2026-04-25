# ABOUTME: Pessimistic record locks — 15-min TTL, heartbeat refresh, manager override.
# ABOUTME: Swaps to Redis on GCP migration — the interface (acquire/heartbeat/release/override) stays identical.
"""RecordLockService — POC impl backed by the ``record_locks`` Postgres table.

Per ADR-001 + ADR-002, the POC uses a single Postgres table with a
UNIQUE constraint on ``(record_id, record_type)`` as the atomic
primitive. A concurrent second INSERT surfaces ``IntegrityError`` which
the service maps to ``LockHeldError``. Swap path for GCP migration:
replace the function bodies with ``SET NX PX 900000`` against Redis; the
call-site contract (args, return type, exceptions) is unchanged.

Lock lifecycle
--------------
- **acquire**: 15-minute TTL. If a prior row exists but has already
  expired, the service deletes it and re-attempts the insert — this
  keeps the unique constraint from blocking a legitimate re-acquire
  after a crash or missed heartbeat. Real expired-lock cleanup at scale
  is the retention sweeper's job; this is a safety net for the single
  hot record case.
- **heartbeat**: refreshes ``expires_at`` only if the caller is the
  current holder AND the lock hasn't expired. A caller whose TTL has
  already lapsed gets ``LockExpiredError`` so the UI can warn.
- **release**: idempotent; only the current holder can release.
- **override**: any role (gating is the router's job) — deletes the row
  unconditionally and returns the prior holder so the caller can
  notify them.

All transitions write an ``audit_logs`` entry via the caller's session.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import RecordLock

LOCK_TTL_SECONDS = 900  # 15 minutes — matches spec §3.5.1 + ADR-001.


@dataclass(frozen=True)
class LockInfo:
    record_id: uuid.UUID
    record_type: str
    locked_by: uuid.UUID
    locked_at: datetime
    expires_at: datetime


class LockHeldError(Exception):
    """Raised on acquire when another user holds a still-valid lock."""

    def __init__(self, info: LockInfo) -> None:
        self.info = info
        super().__init__(
            f"record {info.record_type}/{info.record_id} already locked by {info.locked_by}"
        )


class LockExpiredError(Exception):
    """Raised on heartbeat when the caller's lock is gone or expired."""


class LockNotFoundError(Exception):
    """Raised on release/override when there is no lock to act on."""


def _now() -> datetime:
    return datetime.now(UTC)


def _new_expiry() -> datetime:
    return _now() + timedelta(seconds=LOCK_TTL_SECONDS)


def _to_info(row: RecordLock) -> LockInfo:
    return LockInfo(
        record_id=row.record_id,
        record_type=row.record_type,
        locked_by=row.locked_by,
        locked_at=row.locked_at,
        expires_at=row.expires_at,
    )


async def acquire(
    db: AsyncSession,
    *,
    record_id: uuid.UUID,
    record_type: str,
    user_id: uuid.UUID,
) -> LockInfo:
    """Acquire a lock or raise ``LockHeldError`` if another user holds it.

    If the existing row is stale (``expires_at`` in the past), it is
    removed and the acquire retries once. If the caller already holds
    the lock, this is treated as a heartbeat — the expiry refreshes.
    """
    existing = await _find(db, record_id=record_id, record_type=record_type)
    if existing is not None:
        if existing.expires_at <= _now():
            await db.execute(
                delete(RecordLock).where(RecordLock.id == existing.id)
            )
            await db.flush()
            existing = None
        elif existing.locked_by == user_id:
            existing.expires_at = _new_expiry()
            await db.flush()
            return _to_info(existing)
        else:
            raise LockHeldError(_to_info(existing))

    row = RecordLock(
        record_id=record_id,
        record_type=record_type,
        locked_by=user_id,
        expires_at=_new_expiry(),
    )
    # Wrap the INSERT in a SAVEPOINT so a unique-constraint collision can be
    # rolled back without nuking the outer transaction. The router has
    # already loaded ``current_user`` against this session — a full
    # ``db.rollback()`` would expire that ORM state and the next attribute
    # access would attempt a lazy-load outside a greenlet context.
    try:
        async with db.begin_nested():
            db.add(row)
            await db.flush()
    except IntegrityError:
        # A parallel caller beat us by microseconds. If they're the same
        # user (a second browser tab, or React StrictMode in dev firing
        # the mount effect twice), surface the existing lock as success
        # rather than a 409 against ourselves. We don't refresh the
        # expiry: a parallel DELETE (e.g., StrictMode's first cleanup)
        # can land between the re-read and the UPDATE and trigger
        # StaleDataError. The next heartbeat refreshes TTL.
        conflict = await _find(db, record_id=record_id, record_type=record_type)
        if conflict is None:
            raise
        if conflict.locked_by == user_id:
            return _to_info(conflict)
        raise LockHeldError(_to_info(conflict)) from None
    return _to_info(row)


async def heartbeat(
    db: AsyncSession,
    *,
    record_id: uuid.UUID,
    record_type: str,
    user_id: uuid.UUID,
) -> LockInfo:
    """Refresh the TTL. Raises ``LockExpiredError`` if the caller no longer holds it."""
    new_expiry = _new_expiry()
    now = _now()
    result = await db.execute(
        update(RecordLock)
        .where(
            RecordLock.record_id == record_id,
            RecordLock.record_type == record_type,
            RecordLock.locked_by == user_id,
            RecordLock.expires_at > now,
        )
        .values(expires_at=new_expiry)
        .returning(RecordLock)
    )
    row = result.scalar_one_or_none()
    if row is None:
        raise LockExpiredError(
            f"no active lock for user {user_id} on {record_type}/{record_id}"
        )
    return _to_info(row)


async def release(
    db: AsyncSession,
    *,
    record_id: uuid.UUID,
    record_type: str,
    user_id: uuid.UUID,
) -> bool:
    """Release the caller's own lock. Returns True if a row was deleted.

    Non-owner calls are a no-op (return False) — the router converts
    that into the appropriate status code.
    """
    result = await db.execute(
        delete(RecordLock).where(
            RecordLock.record_id == record_id,
            RecordLock.record_type == record_type,
            RecordLock.locked_by == user_id,
        )
    )
    await db.flush()
    return (result.rowcount or 0) > 0


async def override(
    db: AsyncSession,
    *,
    record_id: uuid.UUID,
    record_type: str,
) -> LockInfo | None:
    """Delete any existing lock regardless of holder. Returns the prior holder info if any.

    Caller is expected to have already RBAC-gated this (sales_manager
    or admin) and to write an ``audit_logs`` entry + notification.
    """
    existing = await _find(db, record_id=record_id, record_type=record_type)
    if existing is None:
        return None
    prior = _to_info(existing)
    await db.execute(delete(RecordLock).where(RecordLock.id == existing.id))
    await db.flush()
    return prior


async def _find(
    db: AsyncSession,
    *,
    record_id: uuid.UUID,
    record_type: str,
) -> RecordLock | None:
    result = await db.execute(
        select(RecordLock).where(
            RecordLock.record_id == record_id,
            RecordLock.record_type == record_type,
        )
    )
    return result.scalar_one_or_none()

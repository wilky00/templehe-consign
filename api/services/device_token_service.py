# ABOUTME: Phase 5 Sprint 1 — APNs/FCM device-token registration + revocation service.
# ABOUTME: Sprint 2's APNs dispatcher reads tokens_for_user(user, 'ios') and fans out per token.
"""Device-token service — Phase 5 Sprint 1.

Single source of truth for the ``device_tokens`` table. The router
hands raw input here; this module enforces the upsert semantics and
soft-delete pattern.

Public surface:

- :func:`register` — upsert on ``(user_id, token)``. Idempotent: same
  user re-registering the same token touches ``last_seen_at`` + clears
  any soft-delete flag without rewriting the row.
- :func:`revoke` — soft-delete one token for one user (set
  ``deleted_at = NOW()``). Cross-user revocation is impossible by
  construction — the predicate is ``(user_id, token)``.
- :func:`tokens_for_user` — list active tokens (optionally filtered by
  platform) for a user. Sprint 2 dispatch reads this.
- :func:`revoke_all_for_user` — used on logout-from-everywhere flows
  in later sprints; soft-deletes every active row for the user.

Why upsert over INSERT-then-catch-IntegrityError: re-registration is
the common case (every iOS launch fetches a possibly-rotated APNs
token), and the upsert path lets us bump ``last_seen_at`` cheaply for
freshness tracking without an extra round-trip.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import structlog
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import DeviceToken, User

logger = structlog.get_logger(__name__)


_ALLOWED_PLATFORMS = ("ios", "android")
_ALLOWED_ENVIRONMENTS = ("development", "production")


async def register(
    db: AsyncSession,
    *,
    user: User,
    platform: str,
    token: str,
    environment: str,
) -> DeviceToken:
    """Upsert a device token.

    Validates ``platform`` and ``environment`` against the same CHECK
    constraint the migration enforces; failing fast here surfaces a
    400 instead of a 500-class IntegrityError. The DB still has the
    last word — service-layer validation is for nicer error messages,
    not safety.
    """
    if platform not in _ALLOWED_PLATFORMS:
        raise ValueError(f"platform must be one of {_ALLOWED_PLATFORMS}, got {platform!r}")
    if environment not in _ALLOWED_ENVIRONMENTS:
        raise ValueError(f"environment must be one of {_ALLOWED_ENVIRONMENTS}, got {environment!r}")
    if not token:
        raise ValueError("token must not be empty")

    stmt = (
        pg_insert(DeviceToken)
        .values(
            user_id=user.id,
            platform=platform,
            token=token,
            environment=environment,
        )
        .on_conflict_do_update(
            constraint="uq_device_tokens_user_token",
            set_={
                # Touching last_seen_at on every register lets the
                # dispatcher reason about token staleness without a
                # separate heartbeat call.
                "last_seen_at": datetime.now(UTC),
                # Re-registering an old soft-deleted row revives it.
                # Common after a manual /me/device-token DELETE
                # followed by an automatic re-register on next launch.
                "deleted_at": None,
                # Environment can flip between debug + release builds.
                "environment": environment,
            },
        )
        .returning(DeviceToken)
    )
    result = await db.execute(stmt)
    row = result.scalar_one()
    await db.flush()
    logger.info(
        "device_token_registered",
        user_id=str(user.id),
        platform=platform,
        environment=environment,
    )
    return row


async def revoke(db: AsyncSession, *, user: User, token: str) -> bool:
    """Soft-delete one device token.

    Returns ``True`` if a row was flipped, ``False`` if no matching
    active row existed (idempotent — re-revoking is a no-op). The
    predicate pins to the caller's ``user_id`` so a token belonging
    to another user can't be revoked through this path.
    """
    stmt = (
        update(DeviceToken)
        .where(
            DeviceToken.user_id == user.id,
            DeviceToken.token == token,
            DeviceToken.deleted_at.is_(None),
        )
        .values(deleted_at=datetime.now(UTC))
    )
    result = await db.execute(stmt)
    await db.flush()
    affected = (result.rowcount or 0) > 0
    if affected:
        logger.info("device_token_revoked", user_id=str(user.id))
    return affected


async def tokens_for_user(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    platform: str | None = None,
) -> list[DeviceToken]:
    """List active device tokens for a user.

    Accepts ``user_id`` rather than the full ``User`` so Sprint 2's
    dispatcher can call this with just the user id from the
    ``notification_jobs.recipient_user_id`` column without a User
    fetch. Filters out soft-deleted rows.
    """
    stmt = select(DeviceToken).where(
        DeviceToken.user_id == user_id,
        DeviceToken.deleted_at.is_(None),
    )
    if platform is not None:
        stmt = stmt.where(DeviceToken.platform == platform)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def revoke_all_for_user(db: AsyncSession, *, user: User) -> int:
    """Soft-delete every active device token for a user.

    Used by logout-from-everywhere / account-deletion flows in later
    sprints. Returns the number of rows flipped."""
    stmt = (
        update(DeviceToken)
        .where(
            DeviceToken.user_id == user.id,
            DeviceToken.deleted_at.is_(None),
        )
        .values(deleted_at=datetime.now(UTC))
    )
    result = await db.execute(stmt)
    await db.flush()
    count = result.rowcount or 0
    if count:
        logger.info("device_token_revoke_all", user_id=str(user.id), count=count)
    return count

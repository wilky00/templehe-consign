# ABOUTME: Refresh token management using the user_sessions Postgres table.
# ABOUTME: Swaps to Redis on GCP migration — the interface (issue/validate/revoke) stays identical.
from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database.models import UserSession


def _hash_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode()).hexdigest()


async def issue_refresh_token(
    user_id: uuid.UUID,
    db: AsyncSession,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> str:
    """Generate an opaque refresh token, store its hash, and return the raw token."""
    raw_token = secrets.token_hex(64)
    expires_at = datetime.now(UTC) + timedelta(days=settings.refresh_token_expire_days)
    session = UserSession(
        user_id=user_id,
        token_hash=_hash_token(raw_token),
        expires_at=expires_at,
        ip_address=ip_address,
        user_agent=user_agent,
    )
    db.add(session)
    await db.flush()
    return raw_token


async def validate_and_rotate(
    raw_token: str,
    db: AsyncSession,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> tuple[uuid.UUID, str] | None:
    """Validate a refresh token, revoke it, issue a new one.

    Returns (user_id, new_token) or None if invalid/expired.
    """
    token_hash = _hash_token(raw_token)
    now = datetime.now(UTC)

    result = await db.execute(
        select(UserSession).where(
            UserSession.token_hash == token_hash,
            UserSession.revoked_at.is_(None),
            UserSession.expires_at > now,
        )
    )
    session = result.scalar_one_or_none()
    if session is None:
        return None

    # Revoke old session
    session.revoked_at = now
    db.add(session)

    # Issue a new one
    new_token = await issue_refresh_token(session.user_id, db, ip_address, user_agent)
    return session.user_id, new_token


async def revoke_token(raw_token: str, db: AsyncSession) -> None:
    """Revoke a refresh token on logout."""
    token_hash = _hash_token(raw_token)
    result = await db.execute(
        select(UserSession).where(
            UserSession.token_hash == token_hash,
            UserSession.revoked_at.is_(None),
        )
    )
    session = result.scalar_one_or_none()
    if session:
        session.revoked_at = datetime.now(UTC)
        db.add(session)
        await db.flush()


async def revoke_all_for_user(user_id: uuid.UUID, db: AsyncSession) -> None:
    """Revoke all active sessions for a user — called on password reset."""
    now = datetime.now(UTC)
    result = await db.execute(
        select(UserSession).where(
            UserSession.user_id == user_id,
            UserSession.revoked_at.is_(None),
        )
    )
    for session in result.scalars().all():
        session.revoked_at = now
        db.add(session)
    await db.flush()

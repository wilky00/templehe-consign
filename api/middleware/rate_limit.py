# ABOUTME: Postgres-backed fixed-window rate limiter (per ADR-010, no Redis in POC).
# ABOUTME: Use as a FastAPI dependency; raises 429 when the limit is exceeded.
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import Depends, HTTPException, Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from database.base import get_db


async def _check_rate_limit(
    key: str,
    limit: int,
    window_seconds: int,
    db: AsyncSession,
) -> None:
    """
    Increment the counter for `key` in the current fixed window.
    Raises 429 if the count exceeds `limit`.
    """
    # Truncate now to the window boundary
    now = datetime.now(UTC)
    window_start = (
        now.replace(
            second=(now.second // window_seconds) * window_seconds,
            microsecond=0,
        )
        if window_seconds < 60
        else now.replace(
            minute=(now.minute // (window_seconds // 60)) * (window_seconds // 60),
            second=0,
            microsecond=0,
        )
    )

    row_id = str(uuid.uuid4())
    result = await db.execute(
        text(
            "INSERT INTO rate_limit_counters (id, key, window_start, count) "
            "VALUES (:id, :key, :window_start, 1) "
            "ON CONFLICT (key, window_start) "
            "DO UPDATE SET count = rate_limit_counters.count + 1 "
            "RETURNING count"
        ),
        {"id": row_id, "key": key, "window_start": window_start},
    )
    count = result.scalar_one()
    await db.flush()

    if count > limit:
        retry_after = int((window_start + timedelta(seconds=window_seconds) - now).total_seconds())
        raise HTTPException(
            status_code=429,
            detail="Too many requests. Please try again later.",
            headers={"Retry-After": str(max(retry_after, 1))},
        )


# ---------------------------------------------------------------------------
# Per-endpoint dependency factories
# ---------------------------------------------------------------------------


def rate_limit_by_ip(limit: int, window_seconds: int, endpoint: str):
    """Dependency: limit requests per IP address."""

    async def _dep(request: Request, db: AsyncSession = Depends(get_db)) -> None:
        ip = request.client.host if request.client else "unknown"
        await _check_rate_limit(f"{endpoint}_ip:{ip}", limit, window_seconds, db)

    return _dep


def rate_limit_by_email(limit: int, window_seconds: int, endpoint: str):
    """Dependency: limit requests per email in the request body."""

    async def _dep(request: Request, db: AsyncSession = Depends(get_db)) -> None:
        try:
            body = await request.json()
            email = str(body.get("email", "")).lower()
        except Exception:
            email = "unknown"
        if email:
            await _check_rate_limit(f"{endpoint}_email:{email}", limit, window_seconds, db)

    return _dep


# ---------------------------------------------------------------------------
# Pre-configured limiters for auth endpoints (per security baseline §2)
# ---------------------------------------------------------------------------

# POST /auth/login: 10/min per IP, 10 per 15 min per email
# Email limit is 10 (not 5) so account lockout fires at attempt 6 before rate limit kicks in.
login_ip_limiter = rate_limit_by_ip(limit=10, window_seconds=60, endpoint="login")
login_email_limiter = rate_limit_by_email(limit=10, window_seconds=900, endpoint="login")

# POST /auth/register: 5/hour per IP
register_ip_limiter = rate_limit_by_ip(limit=5, window_seconds=3600, endpoint="register")

# POST /auth/password-reset-request: 10/hour per IP, 3/hour per email
reset_ip_limiter = rate_limit_by_ip(limit=10, window_seconds=3600, endpoint="password_reset")
reset_email_limiter = rate_limit_by_email(limit=3, window_seconds=3600, endpoint="password_reset")

# POST /auth/2fa/verify: 10/min per IP, 5 per 15 min per... we use IP only (no email in body)
totp_ip_limiter = rate_limit_by_ip(limit=10, window_seconds=60, endpoint="2fa_verify")

# POST /auth/refresh: 60/min per IP
refresh_ip_limiter = rate_limit_by_ip(limit=60, window_seconds=60, endpoint="refresh")

# POST /auth/resend-verification: 3/hour per email
resend_email_limiter = rate_limit_by_email(
    limit=3, window_seconds=3600, endpoint="resend_verification"
)

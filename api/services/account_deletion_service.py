# ABOUTME: GDPR right-to-erasure — 30-day grace, then PII scrub + soft delete.
# ABOUTME: Finalization runs via fn_delete_expired_accounts() in the retention sweeper.
"""Account deletion service.

Flow:

1. ``POST /me/account/delete`` — ``request_deletion`` sets
   ``deletion_requested_at``, ``deletion_grace_until = now + 30d``,
   flips status to ``pending_deletion``. All active sessions are
   revoked so the user must re-auth to cancel.
2. During the grace window the user can log in normally (their status
   is ``pending_deletion``, which the auth middleware accepts) and
   cancel via ``POST /me/account/delete/cancel`` — ``cancel_deletion``
   clears the grace fields and restores status to ``active``.
3. Once ``deletion_grace_until`` passes, the retention sweeper's
   ``fn_delete_expired_accounts()`` PL/pgSQL function pseudonymizes
   both ``users`` and ``customers`` and flips status to ``deleted``.
   ``finalize_deletion_for_user`` exists here so tests + ad-hoc admin
   flows can trigger the same scrub on a specific user without waiting
   for the sweep cycle.

Equipment records and consignment history are preserved — once the
identifying rows are scrubbed, those rows are business facts rather
than personal data.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import structlog
from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import Customer, User, UserSession
from services import notification_service

logger = structlog.get_logger(__name__)

_GRACE_PERIOD_DAYS = 30


async def request_deletion(db: AsyncSession, user: User) -> User:
    """Start the grace window. Safe to call while already pending_deletion —
    the existing grace window is preserved so a double-click doesn't
    unexpectedly extend it.
    """
    if user.status == "deleted":
        raise HTTPException(
            status_code=410,
            detail="This account has already been deleted.",
        )
    if user.status == "pending_deletion" and user.deletion_grace_until is not None:
        # Idempotent — don't reset the clock if one is already running.
        return user

    now = datetime.now(UTC)
    user.status = "pending_deletion"
    user.deletion_requested_at = now
    user.deletion_grace_until = now + timedelta(days=_GRACE_PERIOD_DAYS)
    db.add(user)
    await db.flush()

    # Kick the user out of every other session; they can sign back in to
    # cancel. The current request's access token stays valid to finish
    # the roundtrip (token expiry handles it naturally).
    await db.execute(
        update(UserSession)
        .where(UserSession.user_id == user.id, UserSession.revoked_at.is_(None))
        .values(revoked_at=now)
    )

    await notification_service.enqueue(
        db,
        idempotency_key=f"account_deletion_requested:{user.id}:{now.date().isoformat()}",
        user_id=user.id,
        channel="email",
        template="account_deletion_requested",
        payload={
            "to_email": user.email,
            "subject": "Your account deletion request was received",
            "html_body": (
                f"<p>Hi {user.first_name},</p>"
                "<p>We received your request to delete your Temple Heavy Equipment account.</p>"
                f"<p>Your account is scheduled for deletion on "
                f"<strong>{user.deletion_grace_until.date().isoformat()}</strong>. "
                "You can cancel this request from your portal any time before that date.</p>"
                "<p>If you did not request this, sign in and cancel — "
                "then change your password.</p>"
                "<p>— The Temple Heavy Equipment team</p>"
            ),
            "grace_until": user.deletion_grace_until.isoformat(),
        },
    )
    return user


async def cancel_deletion(db: AsyncSession, user: User) -> User:
    if user.status != "pending_deletion":
        raise HTTPException(
            status_code=409,
            detail="This account is not pending deletion.",
        )
    user.status = "active"
    user.deletion_requested_at = None
    user.deletion_grace_until = None
    db.add(user)
    await db.flush()

    await notification_service.enqueue(
        db,
        idempotency_key=f"account_deletion_cancelled:{user.id}:{datetime.now(UTC).isoformat()}",
        user_id=user.id,
        channel="email",
        template="account_deletion_cancelled",
        payload={
            "to_email": user.email,
            "subject": "Account deletion cancelled",
            "html_body": (
                f"<p>Hi {user.first_name},</p>"
                "<p>Your pending account deletion has been cancelled. "
                "Your account is active and your data remains intact.</p>"
                "<p>— The Temple Heavy Equipment team</p>"
            ),
        },
    )
    return user


async def finalize_deletion_for_user(db: AsyncSession, user: User) -> User:
    """Apply the PII scrub immediately. Used by admin tooling and tests;
    the production path is the hourly retention sweeper.
    """
    if user.status == "deleted":
        return user

    customer_result = await db.execute(select(Customer).where(Customer.user_id == user.id))
    customer = customer_result.scalar_one_or_none()
    if customer is not None:
        customer.submitter_name = "[deleted]"
        customer.business_name = None
        customer.title = None
        customer.address_street = None
        customer.address_city = None
        customer.address_state = None
        customer.address_zip = None
        customer.business_phone = None
        customer.business_phone_ext = None
        customer.cell_phone = None
        customer.communication_prefs = None
        customer.deleted_at = datetime.now(UTC)
        db.add(customer)

    user.email = f"deleted-{user.id}@deleted.invalid"
    user.first_name = "[deleted]"
    user.last_name = ""
    user.password_hash = None
    user.totp_secret_enc = None
    user.totp_enabled = False
    user.google_id = None
    user.profile_photo_url = None
    user.status = "deleted"
    user.deletion_grace_until = None
    db.add(user)
    await db.flush()
    return user

# ABOUTME: Phase 4 Sprint 5 — merged read of customer comms prefs + employee channel prefs.
# ABOUTME: Architectural Debt #5 — admin sees "what + how" without reading two tables.
"""Unified notification preferences read service.

Two preference tables exist for historical reasons:

- ``customers.communication_prefs`` (JSONB) — per-event opt-in flags
  the customer sets in their portal: intake confirmations, status
  updates, marketing, sms_opt_in. "Whether to send."
- ``notification_preferences`` (one row per user) — the user's
  preferred channel (email / sms / slack) + destination (phone, slack
  user id). "Where to send."

Phase 4 admin needs to render a single "notifications for this user"
panel that combines both. This service owns the read-side merge so
the admin endpoint stays a thin pass-through and the merge logic
isn't duplicated across callers.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from database.models import Customer, NotificationPreference, User


@dataclass(frozen=True)
class UnifiedNotificationView:
    user_id: uuid.UUID
    email: str
    role_slug: str | None
    # Channel side (notification_preferences row).
    channel: str
    phone_number: str | None
    slack_user_id: str | None
    # Customer-event opt-ins (customers.communication_prefs). None when
    # the user has no Customer profile (sales reps, admins, etc.).
    intake_confirmations: bool | None
    status_updates: bool | None
    marketing: bool | None
    sms_opt_in: bool | None


_DEFAULT_PREFS = {
    "intake_confirmations": True,
    "status_updates": True,
    "marketing": False,
    "sms_opt_in": False,
}


async def for_user(db: AsyncSession, *, user_id: uuid.UUID) -> UnifiedNotificationView:
    """Merged notification view for one user.

    - Channel defaults to "email" when no notification_preferences row
      exists (matches the pre-Sprint-3 default applied by
      notification_preferences_service.resolve_channel).
    - Customer-event opt-ins return None when the user has no
      Customer profile — admin UI should hide that section for
      employees.
    """
    user = (
        await db.execute(
            select(User)
            .where(User.id == user_id)
            .options(selectinload(User.role), selectinload(User.notification_preference))
        )
    ).scalar_one()
    customer = (
        await db.execute(select(Customer).where(Customer.user_id == user_id))
    ).scalar_one_or_none()
    pref: NotificationPreference | None = user.notification_preference

    return UnifiedNotificationView(
        user_id=user.id,
        email=user.email,
        role_slug=user.role.slug if user.role is not None else None,
        channel=pref.channel if pref else "email",
        phone_number=pref.phone_number if pref else None,
        slack_user_id=pref.slack_user_id if pref else None,
        intake_confirmations=_pref_lookup(customer, "intake_confirmations"),
        status_updates=_pref_lookup(customer, "status_updates"),
        marketing=_pref_lookup(customer, "marketing"),
        sms_opt_in=_pref_lookup(customer, "sms_opt_in"),
    )


def _pref_lookup(customer: Customer | None, key: str) -> bool | None:
    """Customer comms prefs lookup with the per-key default applied.
    Returns None when the user has no Customer profile (employee)."""
    if customer is None:
        return None
    raw = customer.communication_prefs or {}
    if not isinstance(raw, dict):
        return _DEFAULT_PREFS[key]
    value = raw.get(key)
    if not isinstance(value, bool):
        return _DEFAULT_PREFS[key]
    return value

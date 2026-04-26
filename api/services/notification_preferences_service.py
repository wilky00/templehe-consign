# ABOUTME: Per-user preferred notification channel — read/write + role-based visibility/edit gates.
# ABOUTME: Slack→email fallback lives here so callers get one resolved channel + destination.
"""Notification preferences service.

Spec: Phase 3 Sprint 5 — every employee gets a single preferred channel
(email | sms | slack). Callers that need to enqueue an off-band message
(e.g. status transitions, lock override) ask ``resolve_channel`` for the
channel string and the matching destination (email address, phone, or
Slack user ID).

Slack dispatch is not yet wired in ``notification_service`` — Phase 4/8
adds the integration. For Sprint 5 we *accept* a slack preference but
``resolve_channel`` collapses it back to email so the user still gets the
notification through the existing email path. Same pattern lets us flip
to real Slack delivery later without a schema migration.

The two role-based gates are intentionally split:

- ``is_hidden_for_role`` — driven by ``app_config`` key
  ``notification_preferences_hidden_roles``. An admin can hide the page
  from any role entirely; the router 404s on both GET and PUT.
- ``is_read_only_for_role`` — pure-function policy: customers see the
  page (read-only) by default. Future configurability lives next to the
  hidden-roles flag, but Sprint 5 keeps customer-RO hardcoded so the
  default is obvious from reading the code.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import NotificationPreference, User
from services import app_config_registry

ALLOWED_CHANNELS: frozenset[str] = frozenset({"email", "sms", "slack"})
DEFAULT_CHANNEL = "email"

_READ_ONLY_ROLES: frozenset[str] = frozenset({"customer"})


@dataclass(frozen=True)
class ResolvedChannel:
    """The channel a notification will actually use, after fallbacks.

    ``destination`` is the raw routing value — an email address for
    email, an E.164 phone for SMS. Slack preferences collapse to email,
    so the destination is the user's email address in that case too.
    """

    channel: str
    destination: str | None


async def get_for_user(db: AsyncSession, *, user_id: uuid.UUID) -> NotificationPreference | None:
    result = await db.execute(
        select(NotificationPreference).where(NotificationPreference.user_id == user_id)
    )
    return result.scalar_one_or_none()


async def upsert_for_user(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    channel: str,
    phone_number: str | None,
    slack_user_id: str | None,
) -> NotificationPreference:
    """Create or update the user's preferred channel.

    INSERT ... ON CONFLICT (user_id) DO UPDATE — relies on the unique
    constraint added in migration 012.
    """
    if channel not in ALLOWED_CHANNELS:
        raise ValueError(f"channel must be one of {sorted(ALLOWED_CHANNELS)}")

    stmt = (
        pg_insert(NotificationPreference)
        .values(
            user_id=user_id,
            channel=channel,
            phone_number=phone_number,
            slack_user_id=slack_user_id,
        )
        .on_conflict_do_update(
            index_elements=["user_id"],
            set_={
                "channel": channel,
                "phone_number": phone_number,
                "slack_user_id": slack_user_id,
            },
        )
        .returning(NotificationPreference)
    )
    result = await db.execute(stmt)
    await db.flush()
    row = result.scalar_one()
    # Re-select via ORM so subsequent reads see the merged identity-map row.
    await db.refresh(row)
    return row


async def resolve_channel(db: AsyncSession, *, user: User) -> ResolvedChannel:
    """Pick the channel to dispatch on for ``user``.

    Returns ``("email", user.email)`` if no preference row exists, the SMS
    pref is missing a phone number, or the SMS dispatch path is the only
    one wired. Slack preferences fall back to email per the Sprint 5
    note above.
    """
    pref = await get_for_user(db, user_id=user.id)
    if pref is None:
        return ResolvedChannel(channel="email", destination=user.email)
    if pref.channel == "sms":
        # Without a phone number, SMS can't dispatch — fall back rather
        # than enqueue a guaranteed-fail row.
        if not pref.phone_number:
            return ResolvedChannel(channel="email", destination=user.email)
        return ResolvedChannel(channel="sms", destination=pref.phone_number)
    if pref.channel == "slack":
        # Slack dispatch not wired yet — collapse to email so the user
        # still gets the message. Phase 4/8 swaps this branch.
        return ResolvedChannel(channel="email", destination=user.email)
    return ResolvedChannel(channel="email", destination=user.email)


async def is_hidden_for_role(db: AsyncSession, *, role_slug: str) -> bool:
    """Phase 4 admin can flip the AppConfig key to hide the page from
    a role outright. Read through the registry so the parsed shape +
    default handling stay in one place."""
    roles = await app_config_registry.get_typed(
        db, app_config_registry.NOTIFICATION_PREFERENCES_HIDDEN_ROLES.name
    )
    return role_slug in (roles or [])


def is_read_only_for_role(role_slug: str) -> bool:
    return role_slug in _READ_ONLY_ROLES

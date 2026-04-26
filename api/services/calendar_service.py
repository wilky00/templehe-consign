# ABOUTME: Phase 3 Sprint 4 — appraisal calendar: list/create/update/cancel + atomic conflict.
# ABOUTME: SELECT … FOR UPDATE over the appraiser's day; drive-time buffer via Google Maps.
"""Shared calendar + scheduling service.

The conflict-detection contract:

1. ``create_event`` and ``update_event`` open a row-level lock over the
   appraiser's ``calendar_events`` rows in the candidate day window. Two
   concurrent schedule-attempts serialize on that lock; only the first
   wins, the second sees the conflict.
2. The drive-time buffer is added on both sides of an existing event:
   the new event must start ``buffer`` after the previous event ends
   AND end ``buffer`` before the next event starts. The buffer comes
   from Google Distance Matrix (cached), or — when the API is
   unavailable / unconfigured — from the AppConfig fallback minutes.
3. A 409 conflict response always includes a "next available" hint so
   the UI can offer a one-click reschedule.

Status transitions:

- ``new_request → appraisal_scheduled`` on create
- cancel reverts to ``new_request`` (Feature 3.4.4)
- ``record_transition`` is the single status entry point (ADR-013)

Audit:

- Every mutation writes an ``audit_logs`` row with actor + before/after.
  Sales reps can author edits per spec line 179, and managers / admin
  can review them after the fact via the audit trail.

Notifications:

- Customer status emails come for free via ``record_transition`` (the
  ``appraisal_scheduled`` template lives in ``equipment_status_service``).
- Appraiser-side scheduled / cancelled emails are enqueued here via the
  ``appraisal_scheduled_appraiser`` and ``appraisal_cancelled_appraiser``
  templates with idempotency keys keyed on event_id + transition.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import structlog
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from database.models import (
    AuditLog,
    CalendarEvent,
    Customer,
    EquipmentRecord,
    Role,
    User,
)
from services import equipment_status_service, google_maps_service, notification_service
from services.equipment_status_machine import Status

logger = structlog.get_logger(__name__)

_SCHEDULABLE_FROM_STATUSES = frozenset({Status.NEW_REQUEST.value})
_DEFAULT_DURATION_MINUTES = 60


@dataclass(frozen=True)
class CalendarConflict:
    """Returned to the router when a scheduling attempt collides.

    The router maps this to a 409 with the message + suggested next slot.
    """

    message: str
    next_available_at: datetime | None
    conflicting_event_id: uuid.UUID | None


# --------------------------------------------------------------------------- #
# Read
# --------------------------------------------------------------------------- #


async def list_events(
    db: AsyncSession,
    *,
    start: datetime,
    end: datetime,
    appraiser_id: uuid.UUID | None = None,
) -> list[CalendarEvent]:
    """Return events whose ``scheduled_at`` falls inside ``[start, end)``.

    Cancelled events are filtered out so the calendar view doesn't show ghosts.
    Caller decides whether to load the linked equipment record / customer.
    """
    stmt = (
        select(CalendarEvent)
        .options(
            selectinload(CalendarEvent.equipment_record).selectinload(EquipmentRecord.customer),
        )
        .where(
            CalendarEvent.scheduled_at >= start,
            CalendarEvent.scheduled_at < end,
            CalendarEvent.cancelled_at.is_(None),
        )
        .order_by(CalendarEvent.scheduled_at.asc())
    )
    if appraiser_id is not None:
        stmt = stmt.where(CalendarEvent.appraiser_id == appraiser_id)
    result = await db.execute(stmt)
    return list(result.scalars().all())


# --------------------------------------------------------------------------- #
# Create
# --------------------------------------------------------------------------- #


async def create_event(
    db: AsyncSession,
    *,
    actor: User,
    actor_role: str,
    record_id: uuid.UUID,
    appraiser_id: uuid.UUID,
    scheduled_at: datetime,
    duration_minutes: int | None,
    site_address: str | None,
) -> CalendarEvent | CalendarConflict:
    """Create a calendar event after validating the conflict window.

    Returns either the persisted ``CalendarEvent`` or a ``CalendarConflict``
    that the router surfaces as 409.
    """
    duration = duration_minutes or _DEFAULT_DURATION_MINUTES
    end_at = scheduled_at + timedelta(minutes=duration)

    record = await _load_record_or_404(db, record_id)
    if record.status not in _SCHEDULABLE_FROM_STATUSES:
        raise HTTPException(
            status_code=422,
            detail=f"Cannot schedule from status '{record.status}'. "
            "Only new_request records may be scheduled.",
        )
    appraiser = await _require_appraiser(db, appraiser_id)
    address = (site_address or record.customer_location_text or "").strip() or None

    conflict = await _check_conflict(
        db,
        appraiser_id=appraiser_id,
        proposed_start=scheduled_at,
        proposed_end=end_at,
        proposed_address=address,
        ignore_event_id=None,
    )
    if conflict is not None:
        return conflict

    event = CalendarEvent(
        equipment_record_id=record.id,
        appraiser_id=appraiser_id,
        scheduled_at=scheduled_at,
        duration_minutes=duration,
        site_address=address,
    )
    db.add(event)
    await db.flush()

    db.add(
        AuditLog(
            event_type="calendar_event.created",
            actor_id=actor.id,
            actor_role=actor_role,
            target_type="calendar_event",
            target_id=event.id,
            before_state=None,
            after_state=_event_state(event),
        )
    )

    await equipment_status_service.record_transition(
        db,
        record=record,
        to_status=Status.APPRAISAL_SCHEDULED.value,
        changed_by=actor,
        customer=record.customer.user if record.customer is not None else None,
    )
    await _enqueue_appraiser_email(
        db,
        appraiser=appraiser,
        record=record,
        event=event,
        kind="scheduled",
    )
    return event


# --------------------------------------------------------------------------- #
# Update
# --------------------------------------------------------------------------- #


async def update_event(
    db: AsyncSession,
    *,
    actor: User,
    actor_role: str,
    event_id: uuid.UUID,
    appraiser_id: uuid.UUID | None,
    scheduled_at: datetime | None,
    duration_minutes: int | None,
    site_address: str | None,
    set_site_address: bool,
) -> CalendarEvent | CalendarConflict:
    """Re-run the conflict check on any time/appraiser change."""
    event = await _get_event_or_404(db, event_id)
    if event.cancelled_at is not None:
        raise HTTPException(status_code=409, detail="Cannot edit a cancelled appointment.")

    before = _event_state(event)

    new_appraiser_id = appraiser_id or event.appraiser_id
    new_start = scheduled_at or event.scheduled_at
    new_duration = duration_minutes or event.duration_minutes
    new_end = new_start + timedelta(minutes=new_duration)
    new_address = site_address if set_site_address else event.site_address

    if new_appraiser_id != event.appraiser_id:
        await _require_appraiser(db, new_appraiser_id)

    schedule_changed = (
        new_appraiser_id != event.appraiser_id
        or new_start != event.scheduled_at
        or new_duration != event.duration_minutes
    )
    if schedule_changed:
        conflict = await _check_conflict(
            db,
            appraiser_id=new_appraiser_id,
            proposed_start=new_start,
            proposed_end=new_end,
            proposed_address=new_address,
            ignore_event_id=event.id,
        )
        if conflict is not None:
            return conflict

    event.appraiser_id = new_appraiser_id
    event.scheduled_at = new_start
    event.duration_minutes = new_duration
    if set_site_address:
        event.site_address = new_address
    db.add(event)
    await db.flush()

    db.add(
        AuditLog(
            event_type="calendar_event.updated",
            actor_id=actor.id,
            actor_role=actor_role,
            target_type="calendar_event",
            target_id=event.id,
            before_state=before,
            after_state=_event_state(event),
        )
    )
    return event


# --------------------------------------------------------------------------- #
# Cancel
# --------------------------------------------------------------------------- #


async def cancel_event(
    db: AsyncSession,
    *,
    actor: User,
    actor_role: str,
    event_id: uuid.UUID,
) -> CalendarEvent:
    event = await _get_event_or_404(db, event_id)
    if event.cancelled_at is not None:
        # Idempotent — return as-is.
        return event

    before = _event_state(event)
    event.cancelled_at = datetime.now(UTC)
    db.add(event)
    await db.flush()

    db.add(
        AuditLog(
            event_type="calendar_event.cancelled",
            actor_id=actor.id,
            actor_role=actor_role,
            target_type="calendar_event",
            target_id=event.id,
            before_state=before,
            after_state=_event_state(event),
        )
    )

    record = await _load_record_or_404(db, event.equipment_record_id)
    if record.status == Status.APPRAISAL_SCHEDULED.value:
        # Spec Feature 3.4.4: revert to new_request on cancel. No customer
        # status email — the customer notification is the cancellation
        # email below, not a status flip notification.
        record.status = Status.NEW_REQUEST.value
        db.add(record)
        await db.flush()

    appraiser = (
        await db.execute(select(User).where(User.id == event.appraiser_id))
    ).scalar_one_or_none()
    if appraiser is not None:
        await _enqueue_appraiser_email(
            db,
            appraiser=appraiser,
            record=record,
            event=event,
            kind="cancelled",
        )
    if record.customer is not None and record.customer.user is not None:
        await _enqueue_customer_cancellation_email(
            db,
            customer_user=record.customer.user,
            record=record,
            event=event,
        )
    return event


# --------------------------------------------------------------------------- #
# Conflict detection
# --------------------------------------------------------------------------- #


async def _check_conflict(
    db: AsyncSession,
    *,
    appraiser_id: uuid.UUID,
    proposed_start: datetime,
    proposed_end: datetime,
    proposed_address: str | None,
    ignore_event_id: uuid.UUID | None,
) -> CalendarConflict | None:
    """Return a ``CalendarConflict`` if the slot is taken, else ``None``.

    The lock is taken over the appraiser's events on the same calendar day
    (UTC). That window is small and bounded — a row-level lock here is
    cheaper than locking the whole table and serializes only the threads
    competing for the same day.
    """
    day_start = proposed_start.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = day_start + timedelta(days=1)

    overlap_stmt = (
        select(CalendarEvent)
        .where(
            CalendarEvent.appraiser_id == appraiser_id,
            CalendarEvent.cancelled_at.is_(None),
            CalendarEvent.scheduled_at >= day_start,
            CalendarEvent.scheduled_at < day_end,
        )
        .with_for_update()
        .order_by(CalendarEvent.scheduled_at.asc())
    )
    if ignore_event_id is not None:
        overlap_stmt = overlap_stmt.where(CalendarEvent.id != ignore_event_id)
    same_day_events = (await db.execute(overlap_stmt)).scalars().all()

    fallback_minutes = await google_maps_service.read_drive_time_fallback_minutes(db)

    for existing in same_day_events:
        existing_end = existing.scheduled_at + timedelta(minutes=existing.duration_minutes)

        # Direct overlap (no buffer needed).
        if _ranges_overlap(proposed_start, proposed_end, existing.scheduled_at, existing_end):
            return CalendarConflict(
                message=(
                    f"Appraiser is already scheduled "
                    f"{existing.scheduled_at.isoformat()}–{existing_end.isoformat()}."
                ),
                next_available_at=existing_end,
                conflicting_event_id=existing.id,
            )

        # Drive-time buffer either side.
        if existing_end <= proposed_start:
            buffer_seconds = await _resolve_buffer_seconds(
                db,
                origin=existing.site_address,
                destination=proposed_address,
                fallback_minutes=fallback_minutes,
            )
            earliest_arrival = existing_end + timedelta(seconds=buffer_seconds)
            if proposed_start < earliest_arrival:
                return CalendarConflict(
                    message=(
                        "Drive time from the prior appointment would not "
                        f"allow arrival until {earliest_arrival.isoformat()}."
                    ),
                    next_available_at=earliest_arrival,
                    conflicting_event_id=existing.id,
                )
        elif proposed_end <= existing.scheduled_at:
            buffer_seconds = await _resolve_buffer_seconds(
                db,
                origin=proposed_address,
                destination=existing.site_address,
                fallback_minutes=fallback_minutes,
            )
            must_end_by = existing.scheduled_at - timedelta(seconds=buffer_seconds)
            if proposed_end > must_end_by:
                return CalendarConflict(
                    message=(
                        f"This appointment would not leave enough drive time "
                        f"to reach the next stop at {existing.scheduled_at.isoformat()}."
                    ),
                    next_available_at=None,
                    conflicting_event_id=existing.id,
                )
    return None


def _ranges_overlap(a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime) -> bool:
    return a_start < b_end and b_start < a_end


async def _resolve_buffer_seconds(
    db: AsyncSession,
    *,
    origin: str | None,
    destination: str | None,
    fallback_minutes: int,
) -> int:
    """Drive-time in seconds, or the fallback when we can't compute one."""
    if not origin or not destination:
        return fallback_minutes * 60
    seconds = await google_maps_service.get_drive_time_seconds(
        db, origin=origin, destination=destination
    )
    if seconds is None:
        return fallback_minutes * 60
    return seconds


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


async def _load_record_or_404(db: AsyncSession, record_id: uuid.UUID) -> EquipmentRecord:
    record = (
        await db.execute(
            select(EquipmentRecord)
            .options(
                selectinload(EquipmentRecord.customer).selectinload(Customer.user),
            )
            .where(EquipmentRecord.id == record_id)
        )
    ).scalar_one_or_none()
    if record is None:
        raise HTTPException(status_code=404, detail="equipment record not found")
    return record


async def _get_event_or_404(db: AsyncSession, event_id: uuid.UUID) -> CalendarEvent:
    event = (
        await db.execute(select(CalendarEvent).where(CalendarEvent.id == event_id))
    ).scalar_one_or_none()
    if event is None:
        raise HTTPException(status_code=404, detail="calendar event not found")
    return event


async def _require_appraiser(db: AsyncSession, user_id: uuid.UUID) -> User:
    row = (
        await db.execute(
            select(User, Role.slug).join(Role, Role.id == User.role_id).where(User.id == user_id)
        )
    ).first()
    if row is None:
        raise HTTPException(status_code=422, detail=f"appraiser {user_id} not found")
    user, slug = row
    if slug != "appraiser":
        raise HTTPException(
            status_code=422,
            detail=f"user {user_id} has role '{slug}', expected 'appraiser'",
        )
    return user


def _event_state(event: CalendarEvent) -> dict:
    return {
        "id": str(event.id),
        "equipment_record_id": str(event.equipment_record_id),
        "appraiser_id": str(event.appraiser_id),
        "scheduled_at": event.scheduled_at.isoformat() if event.scheduled_at else None,
        "duration_minutes": event.duration_minutes,
        "site_address": event.site_address,
        "cancelled_at": event.cancelled_at.isoformat() if event.cancelled_at else None,
    }


async def _enqueue_appraiser_email(
    db: AsyncSession,
    *,
    appraiser: User,
    record: EquipmentRecord,
    event: CalendarEvent,
    kind: str,
) -> None:
    if not appraiser.email or appraiser.status != "active":
        return
    ref = record.reference_number or str(record.id)
    when = event.scheduled_at.isoformat()
    if kind == "scheduled":
        subject = f"Appraisal scheduled — {ref}"
        body = (
            f"<p>Hi {appraiser.first_name or 'team'},</p>"
            f"<p>You have been scheduled for an appraisal of "
            f"<strong>{ref}</strong> at <strong>{when}</strong>.</p>"
            f"<p>Site: {event.site_address or '(none provided)'}.</p>"
        )
        template = "appraisal_scheduled_appraiser"
        idem = f"appraisal_scheduled:{event.id}:{appraiser.id}"
    elif kind == "cancelled":
        subject = f"Appraisal cancelled — {ref}"
        body = (
            f"<p>Hi {appraiser.first_name or 'team'},</p>"
            f"<p>Your appraisal for <strong>{ref}</strong> previously "
            f"scheduled at <strong>{when}</strong> has been cancelled.</p>"
        )
        template = "appraisal_cancelled_appraiser"
        idem = f"appraisal_cancelled:{event.id}:{appraiser.id}"
    else:
        return
    await notification_service.enqueue(
        db,
        idempotency_key=idem,
        user_id=appraiser.id,
        channel="email",
        template=template,
        payload={
            "to_email": appraiser.email,
            "subject": subject,
            "html_body": body,
            "reference_number": ref,
            "scheduled_at": when,
            "site_address": event.site_address,
        },
    )


async def _enqueue_customer_cancellation_email(
    db: AsyncSession,
    *,
    customer_user: User,
    record: EquipmentRecord,
    event: CalendarEvent,
) -> None:
    if not customer_user.email:
        return
    ref = record.reference_number or str(record.id)
    when = event.scheduled_at.isoformat()
    subject = f"Your appraisal has been rescheduled — {ref}"
    body = (
        f"<p>Hi {customer_user.first_name},</p>"
        f"<p>The appraisal for your equipment submission "
        f"(<strong>{ref}</strong>) previously scheduled at "
        f"<strong>{when}</strong> has been cancelled. A sales rep "
        "will follow up to find a new time.</p>"
    )
    await notification_service.enqueue(
        db,
        idempotency_key=f"appraisal_cancelled_customer:{event.id}",
        user_id=customer_user.id,
        channel="email",
        template="appraisal_cancelled_customer",
        payload={
            "to_email": customer_user.email,
            "subject": subject,
            "html_body": body,
            "reference_number": ref,
        },
    )


__all__ = [
    "CalendarConflict",
    "cancel_event",
    "create_event",
    "list_events",
    "update_event",
]

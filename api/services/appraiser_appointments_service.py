# ABOUTME: Phase 5 Sprint 2 — list upcoming appointments for an appraiser.
# ABOUTME: Joins calendar_events → equipment_records → customer + sales rep for the iOS dashboard.
"""Appraiser appointments service — Phase 5 Sprint 2.

Provides ``list_for_appraiser`` — the data layer behind
``GET /api/v1/me/appointments``. Returns upcoming, non-cancelled
calendar events the calling appraiser is assigned to, enriched with
customer contact info and sales rep contact info for the iOS dashboard
card actions (Call Rep, Call Customer, Navigate).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from database.models import CalendarEvent, Customer, EquipmentRecord, User
from schemas.appraiser import AppointmentDetail


async def list_for_appraiser(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    days_ahead: int = 30,
) -> list[AppointmentDetail]:
    """Return upcoming non-cancelled appointments for the given appraiser.

    Results are ordered by ``scheduled_at`` ascending (soonest first).
    Soft-deleted equipment records are excluded. Cancelled events
    (``cancelled_at IS NOT NULL``) are excluded.
    """
    now = datetime.now(UTC)
    cutoff = now + timedelta(days=days_ahead)

    result = await db.execute(
        select(CalendarEvent)
        .where(
            CalendarEvent.appraiser_id == user_id,
            CalendarEvent.cancelled_at.is_(None),
            CalendarEvent.scheduled_at >= now,
            CalendarEvent.scheduled_at <= cutoff,
        )
        .options(
            selectinload(CalendarEvent.equipment_record).selectinload(EquipmentRecord.customer),
        )
        .order_by(CalendarEvent.scheduled_at)
    )
    events = list(result.scalars().all())

    # Batch-load assigned sales reps in a single query to avoid N+1.
    rep_ids = {
        e.equipment_record.assigned_sales_rep_id
        for e in events
        if e.equipment_record and e.equipment_record.assigned_sales_rep_id
    }
    reps: dict[uuid.UUID, User] = {}
    if rep_ids:
        rep_rows = await db.execute(select(User).where(User.id.in_(rep_ids)))
        reps = {u.id: u for u in rep_rows.scalars().all()}

    appointments: list[AppointmentDetail] = []
    for event in events:
        record = event.equipment_record
        if record is None or record.deleted_at is not None:
            continue
        customer = record.customer
        rep = reps.get(record.assigned_sales_rep_id) if record.assigned_sales_rep_id else None

        appointments.append(
            AppointmentDetail(
                calendar_event_id=event.id,
                equipment_record_id=record.id,
                reference_number=record.reference_number,
                scheduled_at=event.scheduled_at,
                duration_minutes=event.duration_minutes,
                site_address=event.site_address,
                record_status=record.status,
                customer_make=record.customer_make,
                customer_model=record.customer_model,
                customer_year=record.customer_year,
                customer_name=customer.submitter_name if customer else None,
                customer_phone=_best_phone(customer),
                sales_rep_name=_full_name(rep),
                sales_rep_phone=None,  # User model has no phone field yet
                sales_rep_email=rep.email if rep else None,
            )
        )
    return appointments


def _best_phone(customer: Customer | None) -> str | None:
    if customer is None:
        return None
    return customer.cell_phone or customer.business_phone


def _full_name(user: User | None) -> str | None:
    if user is None:
        return None
    parts = [user.first_name, user.last_name]
    name = " ".join(p for p in parts if p)
    return name or None

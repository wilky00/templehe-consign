# ABOUTME: Phase 4 Sprint 5 — calendar_event_attendees mirror invariant + backfill.
# ABOUTME: Confirms appraiser_id INSERTs + UPDATEs are auto-mirrored as role='primary' rows.
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import (
    CalendarEvent,
    CalendarEventAttendee,
    EquipmentRecord,
    Role,
    User,
)

_VALID_PASSWORD = "TestPassword1!"


async def _user_with_role(
    client: AsyncClient, db: AsyncSession, email: str, role_slug: str
) -> dict:
    with patch("services.email_service.send_email", new_callable=AsyncMock):
        await client.post(
            "/api/v1/auth/register",
            json={
                "email": email,
                "password": _VALID_PASSWORD,
                "first_name": "MA",
                "last_name": "User",
                "tos_version": "1",
                "privacy_version": "1",
            },
        )
    user = (await db.execute(select(User).where(User.email == email.lower()))).scalar_one()
    role = (await db.execute(select(Role).where(Role.slug == role_slug))).scalar_one()
    user.status = "active"
    user.role_id = role.id
    await db.flush()
    return {"user_id": str(user.id), "user": user}


async def _customer_id(db: AsyncSession, *, user_id: str) -> uuid.UUID:
    from database.models import Customer

    existing = (
        await db.execute(select(Customer).where(Customer.user_id == user_id))
    ).scalar_one_or_none()
    if existing:
        return existing.id
    cust = Customer(user_id=uuid.UUID(user_id), submitter_name="Cust")
    db.add(cust)
    await db.flush()
    return cust.id


@pytest.mark.asyncio
async def test_creating_event_mirrors_appraiser_into_attendees(
    client: AsyncClient, db_session: AsyncSession
):
    appr = await _user_with_role(client, db_session, "ma_appr1@example.com", "appraiser")
    cust = await _user_with_role(client, db_session, "ma_cust1@example.com", "customer")
    customer_id = await _customer_id(db_session, user_id=cust["user_id"])
    record = EquipmentRecord(customer_id=customer_id, status="appraisal_scheduled")
    db_session.add(record)
    await db_session.flush()

    event = CalendarEvent(
        equipment_record_id=record.id,
        appraiser_id=uuid.UUID(appr["user_id"]),
        scheduled_at=datetime.now(UTC) + timedelta(days=1),
        duration_minutes=60,
    )
    db_session.add(event)
    await db_session.flush()

    attendees = (
        (
            await db_session.execute(
                select(CalendarEventAttendee).where(CalendarEventAttendee.event_id == event.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(attendees) == 1
    assert attendees[0].user_id == uuid.UUID(appr["user_id"])
    assert attendees[0].role == "primary"


@pytest.mark.asyncio
async def test_changing_appraiser_id_adds_new_primary_attendee(
    client: AsyncClient, db_session: AsyncSession
):
    a1 = await _user_with_role(client, db_session, "ma_appr2a@example.com", "appraiser")
    a2 = await _user_with_role(client, db_session, "ma_appr2b@example.com", "appraiser")
    cust = await _user_with_role(client, db_session, "ma_cust2@example.com", "customer")
    customer_id = await _customer_id(db_session, user_id=cust["user_id"])
    record = EquipmentRecord(customer_id=customer_id, status="appraisal_scheduled")
    db_session.add(record)
    await db_session.flush()

    event = CalendarEvent(
        equipment_record_id=record.id,
        appraiser_id=uuid.UUID(a1["user_id"]),
        scheduled_at=datetime.now(UTC) + timedelta(days=1),
        duration_minutes=60,
    )
    db_session.add(event)
    await db_session.flush()

    # Reassign to a2 — listener mirrors the new appraiser into the join table.
    event.appraiser_id = uuid.UUID(a2["user_id"])
    db_session.add(event)
    await db_session.flush()

    attendees = (
        (
            await db_session.execute(
                select(CalendarEventAttendee)
                .where(CalendarEventAttendee.event_id == event.id)
                .order_by(CalendarEventAttendee.added_at)
            )
        )
        .scalars()
        .all()
    )
    user_ids = {att.user_id for att in attendees}
    assert uuid.UUID(a1["user_id"]) in user_ids
    assert uuid.UUID(a2["user_id"]) in user_ids
    # Both rows are role='primary' because the mirror invariant doesn't
    # demote the old appraiser. That's fine — the join table is the
    # historical record; the live "primary" is calendar_events.appraiser_id.


@pytest.mark.asyncio
async def test_idempotent_mirror_on_no_op_save(client: AsyncClient, db_session: AsyncSession):
    appr = await _user_with_role(client, db_session, "ma_appr3@example.com", "appraiser")
    cust = await _user_with_role(client, db_session, "ma_cust3@example.com", "customer")
    customer_id = await _customer_id(db_session, user_id=cust["user_id"])
    record = EquipmentRecord(customer_id=customer_id, status="appraisal_scheduled")
    db_session.add(record)
    await db_session.flush()

    event = CalendarEvent(
        equipment_record_id=record.id,
        appraiser_id=uuid.UUID(appr["user_id"]),
        scheduled_at=datetime.now(UTC) + timedelta(days=1),
        duration_minutes=60,
    )
    db_session.add(event)
    await db_session.flush()

    # Re-touch + flush without changing appraiser_id. The listener
    # should NOT insert a duplicate row.
    event.duration_minutes = 90
    db_session.add(event)
    await db_session.flush()

    attendees = (
        (
            await db_session.execute(
                select(CalendarEventAttendee).where(CalendarEventAttendee.event_id == event.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(attendees) == 1

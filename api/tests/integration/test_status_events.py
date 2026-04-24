# ABOUTME: Phase 2 Sprint 3 tests for equipment_status_service.
# ABOUTME: Covers transitions, customer-email enqueue, timeline, and the append-only trigger.
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import EquipmentRecord, NotificationJob, StatusEvent, User
from services import equipment_status_service

_VALID_PASSWORD = "TestPassword1!"


def _register_payload(email: str) -> dict:
    return {
        "email": email,
        "password": _VALID_PASSWORD,
        "first_name": "Status",
        "last_name": "Customer",
        "tos_version": "1",
        "privacy_version": "1",
    }


async def _login_customer(client: AsyncClient, db: AsyncSession, email: str) -> tuple[str, User]:
    with patch("services.email_service.send_email", new_callable=AsyncMock):
        await client.post("/api/v1/auth/register", json=_register_payload(email))
    result = await db.execute(select(User).where(User.email == email.lower()))
    user = result.scalar_one()
    user.status = "active"
    await db.flush()
    with patch("services.email_service.send_email", new_callable=AsyncMock):
        login = await client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": _VALID_PASSWORD},
        )
    return login.json()["access_token"], user


async def _create_record(client: AsyncClient, token: str, db: AsyncSession) -> EquipmentRecord:
    resp = await client.post(
        "/api/v1/me/equipment",
        json={"photos": []},
        headers={"Authorization": f"Bearer {token}"},
    )
    record_id = uuid.UUID(resp.json()["id"])
    row = await db.execute(select(EquipmentRecord).where(EquipmentRecord.id == record_id))
    return row.scalar_one()


# ---------------------------------------------------------------------------
# Transitions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_transition_writes_event_and_updates_status(
    client: AsyncClient, db_session: AsyncSession
):
    token, user = await _login_customer(client, db_session, "tx_basic@example.com")
    record = await _create_record(client, token, db_session)
    assert record.status == "new_request"

    event = await equipment_status_service.record_transition(
        db_session,
        record=record,
        to_status="appraisal_scheduled",
        changed_by=None,
        note="Tech assigned for Tuesday.",
        customer=user,
    )
    assert event.from_status == "new_request"
    assert event.to_status == "appraisal_scheduled"
    assert record.status == "appraisal_scheduled"

    stored = await db_session.execute(
        select(StatusEvent).where(StatusEvent.equipment_record_id == record.id)
    )
    rows = list(stored.scalars().all())
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_transition_enqueues_email_on_customer_facing_status(
    client: AsyncClient, db_session: AsyncSession
):
    token, user = await _login_customer(client, db_session, "tx_email@example.com")
    record = await _create_record(client, token, db_session)

    await equipment_status_service.record_transition(
        db_session,
        record=record,
        to_status="appraisal_complete",
        changed_by=None,
        customer=user,
    )
    jobs = await db_session.execute(
        select(NotificationJob).where(NotificationJob.template == "status_appraisal_complete")
    )
    queued = list(jobs.scalars().all())
    assert len(queued) == 1
    assert queued[0].payload["to_email"] == "tx_email@example.com"
    assert record.reference_number in queued[0].payload["subject"]


@pytest.mark.asyncio
async def test_transition_skips_email_for_internal_statuses(
    client: AsyncClient, db_session: AsyncSession
):
    """Moving to 'in_progress' (an internal bookkeeping status) must not
    spam the customer with an email."""
    token, user = await _login_customer(client, db_session, "tx_internal@example.com")
    record = await _create_record(client, token, db_session)

    await equipment_status_service.record_transition(
        db_session,
        record=record,
        to_status="appraiser_assigned",  # not in _CUSTOMER_EMAIL_STATUSES
        changed_by=None,
        customer=user,
    )
    jobs = await db_session.execute(
        select(NotificationJob).where(NotificationJob.template.startswith("status_"))
    )
    assert list(jobs.scalars().all()) == []


@pytest.mark.asyncio
async def test_transition_email_is_idempotent_by_destination(
    client: AsyncClient, db_session: AsyncSession
):
    """Same-destination transition rejected → only one email ever queued."""
    token, user = await _login_customer(client, db_session, "tx_idem@example.com")
    record = await _create_record(client, token, db_session)

    await equipment_status_service.record_transition(
        db_session,
        record=record,
        to_status="listed",
        changed_by=None,
        customer=user,
    )
    # Trying to transition to the same status must 409 — a safety on top
    # of the notification idempotency key.
    from fastapi import HTTPException

    with pytest.raises(HTTPException):
        await equipment_status_service.record_transition(
            db_session,
            record=record,
            to_status="listed",
            changed_by=None,
            customer=user,
        )
    jobs = await db_session.execute(
        select(NotificationJob).where(NotificationJob.template == "status_listed")
    )
    assert len(list(jobs.scalars().all())) == 1


@pytest.mark.asyncio
async def test_transition_rejects_forbidden_edge(client: AsyncClient, db_session: AsyncSession):
    token, user = await _login_customer(client, db_session, "tx_bad@example.com")
    record = await _create_record(client, token, db_session)
    record.status = "sold"
    db_session.add(record)
    await db_session.flush()

    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc_info:
        await equipment_status_service.record_transition(
            db_session,
            record=record,
            to_status="new_request",
            changed_by=None,
            customer=user,
        )
    assert exc_info.value.status_code == 409


# ---------------------------------------------------------------------------
# Timeline visible in detail endpoint
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_detail_endpoint_includes_status_timeline(
    client: AsyncClient, db_session: AsyncSession
):
    token, user = await _login_customer(client, db_session, "tx_detail@example.com")
    record = await _create_record(client, token, db_session)

    await equipment_status_service.record_transition(
        db_session,
        record=record,
        to_status="appraisal_scheduled",
        changed_by=None,
        note="Tuesday 10am",
        customer=user,
    )
    await equipment_status_service.record_transition(
        db_session,
        record=record,
        to_status="appraisal_complete",
        changed_by=None,
        customer=user,
    )

    detail = await client.get(
        f"/api/v1/me/equipment/{record.id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert detail.status_code == 200
    events = detail.json()["status_events"]
    order = [e["to_status"] for e in events]
    assert order == ["appraisal_scheduled", "appraisal_complete"]
    # The note survived the round trip.
    assert events[0]["note"] == "Tuesday 10am"


# ---------------------------------------------------------------------------
# Append-only DB trigger
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_status_events_are_append_only(client: AsyncClient, db_session: AsyncSession):
    """Postgres trigger must block UPDATEs on status_events rows."""
    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError

    token, user = await _login_customer(client, db_session, "tx_immutable@example.com")
    record = await _create_record(client, token, db_session)
    await equipment_status_service.record_transition(
        db_session,
        record=record,
        to_status="offer_ready",
        changed_by=None,
        customer=user,
    )

    with pytest.raises(DBAPIError, match="append-only"):
        await db_session.execute(text("UPDATE status_events SET note = 'tampered'"))

# ABOUTME: Phase 5 Sprint 2 — GET /api/v1/me/appointments integration tests.
# ABOUTME: Covers happy path, RBAC, days filter, sort order, cancelled/soft-deleted exclusion.
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import CalendarEvent, Customer, EquipmentRecord, Role, User

_VALID_PASSWORD = "TestPassword1!"


async def _create_user(
    client: AsyncClient,
    db: AsyncSession,
    email: str,
    role_slug: str,
) -> dict:
    with patch("services.email_service.send_email", new_callable=AsyncMock):
        await client.post(
            "/api/v1/auth/register",
            json={
                "email": email,
                "password": _VALID_PASSWORD,
                "first_name": "Field",
                "last_name": "User",
                "tos_version": "1",
                "privacy_version": "1",
            },
        )
    user = (await db.execute(select(User).where(User.email == email.lower()))).scalar_one()
    role = (await db.execute(select(Role).where(Role.slug == role_slug))).scalar_one()
    user.status = "active"
    user.role_id = role.id
    db.add(user)
    await db.flush()
    from services import user_roles_service

    await user_roles_service.grant(db, user=user, role_slug=role_slug, granted_by=None)
    with patch("services.email_service.send_email", new_callable=AsyncMock):
        resp = await client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": _VALID_PASSWORD},
        )
    assert resp.status_code == 200
    return resp.json()


async def _make_customer(db: AsyncSession) -> Customer:
    customer = Customer(
        submitter_name="Test Owner",
        cell_phone="555-111-2222",
        invite_email="owner@example.com",
    )
    db.add(customer)
    await db.flush()
    return customer


async def _make_record(
    db: AsyncSession,
    customer: Customer,
    *,
    appraiser_id=None,
    sales_rep_id=None,
) -> EquipmentRecord:
    record = EquipmentRecord(
        customer_id=customer.id,
        status="appraisal_scheduled",
        reference_number=f"THE-TEST{customer.id.hex[:6].upper()}",
        customer_make="Caterpillar",
        customer_model="320",
        customer_year=2019,
        assigned_appraiser_id=appraiser_id,
        assigned_sales_rep_id=sales_rep_id,
    )
    db.add(record)
    await db.flush()
    return record


async def _make_event(
    db: AsyncSession,
    record: EquipmentRecord,
    appraiser_id,
    *,
    offset_days: int = 1,
    cancelled: bool = False,
    site_address: str = "123 Test St, Denver CO",
) -> CalendarEvent:
    event = CalendarEvent(
        equipment_record_id=record.id,
        appraiser_id=appraiser_id,
        scheduled_at=datetime.now(UTC) + timedelta(days=offset_days),
        duration_minutes=90,
        site_address=site_address,
        cancelled_at=datetime.now(UTC) if cancelled else None,
    )
    db.add(event)
    await db.flush()
    return event


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _email(tag: str) -> str:
    import uuid

    return f"{tag}-{uuid.uuid4().hex[:6]}@example.com"


@pytest.mark.asyncio
async def test_happy_path_returns_appointments(client: AsyncClient, db_session: AsyncSession):
    appraiser = await _create_user(client, db_session, _email("apr"), "appraiser")
    appraiser_row = (
        (
            await db_session.execute(
                select(User).where(User.email.ilike("%apr%")).order_by(User.created_at.desc())
            )
        )
        .scalars()
        .first()
    )

    customer = await _make_customer(db_session)
    record = await _make_record(db_session, customer, appraiser_id=appraiser_row.id)
    await _make_event(db_session, record, appraiser_row.id, offset_days=3)

    resp = await client.get("/api/v1/me/appointments", headers=_auth(appraiser["access_token"]))
    assert resp.status_code == 200
    data = resp.json()
    assert data["days_ahead"] == 30
    assert len(data["appointments"]) == 1
    appt = data["appointments"][0]
    assert appt["customer_make"] == "Caterpillar"
    assert appt["customer_model"] == "320"
    assert appt["customer_name"] == "Test Owner"
    assert appt["customer_phone"] == "555-111-2222"
    assert appt["site_address"] == "123 Test St, Denver CO"


@pytest.mark.asyncio
async def test_cancelled_events_excluded(client: AsyncClient, db_session: AsyncSession):
    appraiser = await _create_user(client, db_session, _email("apr"), "appraiser")
    appraiser_row = (
        (
            await db_session.execute(
                select(User).where(User.email.ilike("%apr%")).order_by(User.created_at.desc())
            )
        )
        .scalars()
        .first()
    )

    customer = await _make_customer(db_session)
    record = await _make_record(db_session, customer, appraiser_id=appraiser_row.id)
    await _make_event(db_session, record, appraiser_row.id, cancelled=True)

    resp = await client.get("/api/v1/me/appointments", headers=_auth(appraiser["access_token"]))
    assert resp.status_code == 200
    assert resp.json()["appointments"] == []


@pytest.mark.asyncio
async def test_days_filter_limits_window(client: AsyncClient, db_session: AsyncSession):
    appraiser = await _create_user(client, db_session, _email("apr"), "appraiser")
    appraiser_row = (
        (
            await db_session.execute(
                select(User).where(User.email.ilike("%apr%")).order_by(User.created_at.desc())
            )
        )
        .scalars()
        .first()
    )

    customer = await _make_customer(db_session)
    record = await _make_record(db_session, customer, appraiser_id=appraiser_row.id)
    # One event within 7 days, one outside.
    await _make_event(db_session, record, appraiser_row.id, offset_days=3, site_address="Near")
    await _make_event(db_session, record, appraiser_row.id, offset_days=14, site_address="Far")

    resp = await client.get(
        "/api/v1/me/appointments?days=7", headers=_auth(appraiser["access_token"])
    )
    assert resp.status_code == 200
    appts = resp.json()["appointments"]
    assert len(appts) == 1
    assert appts[0]["site_address"] == "Near"


@pytest.mark.asyncio
async def test_results_ordered_by_scheduled_at(client: AsyncClient, db_session: AsyncSession):
    appraiser = await _create_user(client, db_session, _email("apr"), "appraiser")
    appraiser_row = (
        (
            await db_session.execute(
                select(User).where(User.email.ilike("%apr%")).order_by(User.created_at.desc())
            )
        )
        .scalars()
        .first()
    )

    customer = await _make_customer(db_session)
    record = await _make_record(db_session, customer, appraiser_id=appraiser_row.id)
    await _make_event(db_session, record, appraiser_row.id, offset_days=5, site_address="Second")
    await _make_event(db_session, record, appraiser_row.id, offset_days=2, site_address="First")

    resp = await client.get("/api/v1/me/appointments", headers=_auth(appraiser["access_token"]))
    appts = resp.json()["appointments"]
    assert len(appts) == 2
    assert appts[0]["site_address"] == "First"
    assert appts[1]["site_address"] == "Second"


@pytest.mark.asyncio
async def test_other_appraiser_events_not_returned(client: AsyncClient, db_session: AsyncSession):
    appraiser_a = await _create_user(client, db_session, _email("apr-a"), "appraiser")
    await _create_user(client, db_session, _email("apr-b"), "appraiser")
    row_b = (
        (
            await db_session.execute(
                select(User).where(User.email.ilike("%apr-b%")).order_by(User.created_at.desc())
            )
        )
        .scalars()
        .first()
    )

    customer = await _make_customer(db_session)
    record = await _make_record(db_session, customer, appraiser_id=row_b.id)
    await _make_event(db_session, record, row_b.id)

    resp = await client.get("/api/v1/me/appointments", headers=_auth(appraiser_a["access_token"]))
    assert resp.json()["appointments"] == []


@pytest.mark.asyncio
async def test_soft_deleted_record_excluded(client: AsyncClient, db_session: AsyncSession):
    appraiser = await _create_user(client, db_session, _email("apr"), "appraiser")
    appraiser_row = (
        (
            await db_session.execute(
                select(User).where(User.email.ilike("%apr%")).order_by(User.created_at.desc())
            )
        )
        .scalars()
        .first()
    )

    customer = await _make_customer(db_session)
    record = await _make_record(db_session, customer, appraiser_id=appraiser_row.id)
    record.deleted_at = datetime.now(UTC)
    db_session.add(record)
    await db_session.flush()  # Flush the UPDATE before adding the CalendarEvent.
    await _make_event(db_session, record, appraiser_row.id)

    resp = await client.get("/api/v1/me/appointments", headers=_auth(appraiser["access_token"]))
    assert resp.json()["appointments"] == []


@pytest.mark.asyncio
async def test_customer_role_blocked(client: AsyncClient, db_session: AsyncSession):
    customer_user = await _create_user(client, db_session, _email("cust"), "customer")
    resp = await client.get("/api/v1/me/appointments", headers=_auth(customer_user["access_token"]))
    assert resp.status_code == 403

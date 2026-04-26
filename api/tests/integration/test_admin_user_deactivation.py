# ABOUTME: Phase 4 Sprint 2 — admin deactivates a user; reassigns open records + future events.
# ABOUTME: Verifies 409 when no reassign target, role-overlap guard, audit log + notify per record.
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import (
    AuditLog,
    CalendarEvent,
    EquipmentRecord,
    NotificationJob,
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
                "first_name": "Deact",
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
    with patch("services.email_service.send_email", new_callable=AsyncMock):
        login = await client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": _VALID_PASSWORD},
        )
    body = login.json()
    body["user_id"] = str(user.id)
    body["user"] = user
    return body


def _auth(tok: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {tok}"}


async def _create_assigned_record(
    db: AsyncSession,
    *,
    customer_id: uuid.UUID,
    sales_rep_id: uuid.UUID | None = None,
    appraiser_id: uuid.UUID | None = None,
    status: str = "appraisal_scheduled",
) -> EquipmentRecord:
    record = EquipmentRecord(
        customer_id=customer_id,
        status=status,
        assigned_sales_rep_id=sales_rep_id,
        assigned_appraiser_id=appraiser_id,
    )
    db.add(record)
    await db.flush()
    return record


async def _customer_id_for(db: AsyncSession, *, user_id: str) -> uuid.UUID:
    """Get or create a Customer profile bound to the given user."""
    from database.models import Customer

    existing = (
        await db.execute(select(Customer).where(Customer.user_id == user_id))
    ).scalar_one_or_none()
    if existing is not None:
        return existing.id
    customer = Customer(user_id=uuid.UUID(user_id), submitter_name="Customer")
    db.add(customer)
    await db.flush()
    return customer.id


# --- 409 paths ----------------------------------------------------------- #


@pytest.mark.asyncio
async def test_deactivate_blocks_when_user_has_open_records_no_reassign(
    client: AsyncClient, db_session: AsyncSession
):
    admin = await _user_with_role(client, db_session, "deact_admin1@example.com", "admin")
    rep = await _user_with_role(client, db_session, "deact_rep1@example.com", "sales")
    cust = await _user_with_role(client, db_session, "deact_cust1@example.com", "customer")
    customer_id = await _customer_id_for(db_session, user_id=cust["user_id"])
    await _create_assigned_record(
        db_session, customer_id=customer_id, sales_rep_id=uuid.UUID(rep["user_id"])
    )

    resp = await client.post(
        f"/api/v1/admin/users/{rep['user_id']}/deactivate",
        json={},
        headers=_auth(admin["access_token"]),
    )
    assert resp.status_code == 409
    detail = resp.json()["detail"]
    assert detail["open_record_count"] == 1
    assert detail["future_event_count"] == 0


@pytest.mark.asyncio
async def test_deactivate_blocks_when_appraiser_has_future_event(
    client: AsyncClient, db_session: AsyncSession
):
    admin = await _user_with_role(client, db_session, "deact_admin2@example.com", "admin")
    appr = await _user_with_role(client, db_session, "deact_appr2@example.com", "appraiser")
    cust = await _user_with_role(client, db_session, "deact_cust2@example.com", "customer")
    customer_id = await _customer_id_for(db_session, user_id=cust["user_id"])
    rec = await _create_assigned_record(
        db_session,
        customer_id=customer_id,
        appraiser_id=uuid.UUID(appr["user_id"]),
        status="appraisal_scheduled",
    )
    db_session.add(
        CalendarEvent(
            equipment_record_id=rec.id,
            appraiser_id=uuid.UUID(appr["user_id"]),
            scheduled_at=datetime.now(UTC) + timedelta(days=2),
            duration_minutes=60,
        )
    )
    await db_session.flush()

    resp = await client.post(
        f"/api/v1/admin/users/{appr['user_id']}/deactivate",
        json={},
        headers=_auth(admin["access_token"]),
    )
    assert resp.status_code == 409
    assert resp.json()["detail"]["future_event_count"] >= 1


# --- happy path: reassign + notify ----------------------------------------- #


@pytest.mark.asyncio
async def test_deactivate_reassigns_records_and_writes_audit_and_notifies(
    client: AsyncClient, db_session: AsyncSession
):
    admin = await _user_with_role(client, db_session, "deact_admin3@example.com", "admin")
    leaving = await _user_with_role(client, db_session, "deact_leaving3@example.com", "sales")
    joining = await _user_with_role(client, db_session, "deact_joining3@example.com", "sales")
    cust = await _user_with_role(client, db_session, "deact_cust3@example.com", "customer")
    customer_id = await _customer_id_for(db_session, user_id=cust["user_id"])
    rec = await _create_assigned_record(
        db_session, customer_id=customer_id, sales_rep_id=uuid.UUID(leaving["user_id"])
    )

    resp = await client.post(
        f"/api/v1/admin/users/{leaving['user_id']}/deactivate",
        json={"reassign_to_id": joining["user_id"]},
        headers=_auth(admin["access_token"]),
    )
    assert resp.status_code == 200, resp.json()
    body = resp.json()
    assert body["new_status"] == "deactivated"
    assert str(rec.id) in body["reassigned_records"]

    refreshed = (
        await db_session.execute(select(EquipmentRecord).where(EquipmentRecord.id == rec.id))
    ).scalar_one()
    assert str(refreshed.assigned_sales_rep_id) == joining["user_id"]

    audit = (
        await db_session.execute(
            select(AuditLog)
            .where(AuditLog.event_type == "equipment_record.deactivation_reassigned")
            .where(AuditLog.target_id == rec.id)
        )
    ).scalar_one()
    assert audit.actor_role == "admin"
    assert audit.before_state["assigned_sales_rep_id"] == leaving["user_id"]
    assert audit.after_state["assigned_sales_rep_id"] == joining["user_id"]
    assert audit.after_state["trigger_user_id"] == leaving["user_id"]

    # New assignee gets the email.
    notif = (
        (
            await db_session.execute(
                select(NotificationJob).where(NotificationJob.template == "record_assigned")
            )
        )
        .scalars()
        .all()
    )
    assert any(j.user_id == uuid.UUID(joining["user_id"]) for j in notif)


@pytest.mark.asyncio
async def test_deactivate_with_no_open_work_succeeds_without_reassign(
    client: AsyncClient, db_session: AsyncSession
):
    admin = await _user_with_role(client, db_session, "deact_admin4@example.com", "admin")
    leaving = await _user_with_role(client, db_session, "deact_leaving4@example.com", "sales")

    resp = await client.post(
        f"/api/v1/admin/users/{leaving['user_id']}/deactivate",
        json={},
        headers=_auth(admin["access_token"]),
    )
    assert resp.status_code == 200, resp.json()
    assert resp.json()["new_status"] == "deactivated"
    refreshed = (
        await db_session.execute(select(User).where(User.id == leaving["user_id"]))
    ).scalar_one()
    assert refreshed.status == "deactivated"


@pytest.mark.asyncio
async def test_deactivate_reassigns_future_calendar_events(
    client: AsyncClient, db_session: AsyncSession
):
    admin = await _user_with_role(client, db_session, "deact_admin5@example.com", "admin")
    leaving = await _user_with_role(client, db_session, "deact_leaving5@example.com", "appraiser")
    joining = await _user_with_role(client, db_session, "deact_joining5@example.com", "appraiser")
    cust = await _user_with_role(client, db_session, "deact_cust5@example.com", "customer")
    customer_id = await _customer_id_for(db_session, user_id=cust["user_id"])
    rec = await _create_assigned_record(
        db_session,
        customer_id=customer_id,
        appraiser_id=uuid.UUID(leaving["user_id"]),
    )
    event = CalendarEvent(
        equipment_record_id=rec.id,
        appraiser_id=uuid.UUID(leaving["user_id"]),
        scheduled_at=datetime.now(UTC) + timedelta(days=3),
        duration_minutes=60,
    )
    db_session.add(event)
    await db_session.flush()

    resp = await client.post(
        f"/api/v1/admin/users/{leaving['user_id']}/deactivate",
        json={"reassign_to_id": joining["user_id"]},
        headers=_auth(admin["access_token"]),
    )
    assert resp.status_code == 200, resp.json()
    assert str(event.id) in resp.json()["reassigned_events"]

    refreshed = (
        await db_session.execute(select(CalendarEvent).where(CalendarEvent.id == event.id))
    ).scalar_one()
    assert str(refreshed.appraiser_id) == joining["user_id"]


# --- guard: role overlap + self-deactivation ------------------------------ #


@pytest.mark.asyncio
async def test_deactivate_rejects_reassignee_without_role_overlap(
    client: AsyncClient, db_session: AsyncSession
):
    admin = await _user_with_role(client, db_session, "deact_admin6@example.com", "admin")
    leaving = await _user_with_role(client, db_session, "deact_leaving6@example.com", "sales")
    bad_target = await _user_with_role(client, db_session, "deact_bad6@example.com", "customer")
    cust = await _user_with_role(client, db_session, "deact_cust6@example.com", "customer")
    customer_id = await _customer_id_for(db_session, user_id=cust["user_id"])
    await _create_assigned_record(
        db_session, customer_id=customer_id, sales_rep_id=uuid.UUID(leaving["user_id"])
    )

    resp = await client.post(
        f"/api/v1/admin/users/{leaving['user_id']}/deactivate",
        json={"reassign_to_id": bad_target["user_id"]},
        headers=_auth(admin["access_token"]),
    )
    assert resp.status_code == 422
    assert "role" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_admin_cannot_self_deactivate(client: AsyncClient, db_session: AsyncSession):
    admin = await _user_with_role(client, db_session, "deact_admin7@example.com", "admin")
    resp = await client.post(
        f"/api/v1/admin/users/{admin['user_id']}/deactivate",
        json={},
        headers=_auth(admin["access_token"]),
    )
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_deactivate_blocked_for_sales_role(client: AsyncClient, db_session: AsyncSession):
    sales = await _user_with_role(client, db_session, "deact_sales@example.com", "sales")
    other = await _user_with_role(client, db_session, "deact_other@example.com", "appraiser")
    resp = await client.post(
        f"/api/v1/admin/users/{other['user_id']}/deactivate",
        json={},
        headers=_auth(sales["access_token"]),
    )
    assert resp.status_code == 403

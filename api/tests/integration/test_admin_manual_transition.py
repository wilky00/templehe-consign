# ABOUTME: Phase 4 Sprint 1 — admin override of equipment_records.status w/ notify toggle.
# ABOUTME: Verifies notify_override, audit_log actor_role/reason, forbidden-transition guard.
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import (
    AuditLog,
    EquipmentRecord,
    NotificationJob,
    Role,
    StatusEvent,
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
                "first_name": "Trans",
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
    return body


def _auth(tok: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {tok}"}


async def _create_record_for(client: AsyncClient, token: str) -> str:
    resp = await client.post(
        "/api/v1/me/equipment",
        json={"photos": []},
        headers=_auth(token),
    )
    assert resp.status_code in (200, 201), resp.json()
    return resp.json()["id"]


@pytest.mark.asyncio
async def test_admin_transition_writes_status_event_audit_log_and_notifies(
    client: AsyncClient, db_session: AsyncSession
):
    admin = await _user_with_role(client, db_session, "mt_admin1@example.com", "admin")
    customer = await _user_with_role(client, db_session, "mt_cust1@example.com", "customer")
    rec_id = await _create_record_for(client, customer["access_token"])

    resp = await client.post(
        f"/api/v1/admin/equipment/{rec_id}/transition",
        json={
            "to_status": "appraisal_scheduled",
            "reason": "Manual schedule pull-in for VIP customer.",
        },
        headers=_auth(admin["access_token"]),
    )
    assert resp.status_code == 200, resp.json()
    body = resp.json()
    assert body["from_status"] == "new_request"
    assert body["to_status"] == "appraisal_scheduled"
    assert body["notifications_dispatched"] is True

    # StatusEvent timeline updated.
    events = (
        (
            await db_session.execute(
                select(StatusEvent)
                .where(StatusEvent.equipment_record_id == rec_id)
                .where(StatusEvent.to_status == "appraisal_scheduled")
            )
        )
        .scalars()
        .all()
    )
    assert len(events) == 1
    assert events[0].note == "Manual schedule pull-in for VIP customer."

    # AuditLog records the admin override + reason + dispatch flag.
    audit = (
        await db_session.execute(
            select(AuditLog)
            .where(AuditLog.event_type == "equipment_record.status_admin_override")
            .where(AuditLog.target_id == uuid.UUID(rec_id))
        )
    ).scalar_one()
    assert audit.actor_role == "admin"
    assert audit.before_state == {"status": "new_request"}
    assert audit.after_state["status"] == "appraisal_scheduled"
    assert audit.after_state["reason"] == "Manual schedule pull-in for VIP customer."
    assert audit.after_state["notifications_dispatched"] is True

    # Customer email enqueued (appraisal_scheduled is customer-facing).
    jobs = (
        (
            await db_session.execute(
                select(NotificationJob).where(
                    NotificationJob.template == "status_appraisal_scheduled"
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(jobs) == 1


@pytest.mark.asyncio
async def test_admin_transition_with_send_notifications_false_suppresses_dispatch(
    client: AsyncClient, db_session: AsyncSession
):
    admin = await _user_with_role(client, db_session, "mt_admin2@example.com", "admin")
    customer = await _user_with_role(client, db_session, "mt_cust2@example.com", "customer")
    rec_id = await _create_record_for(client, customer["access_token"])

    resp = await client.post(
        f"/api/v1/admin/equipment/{rec_id}/transition",
        json={
            "to_status": "appraisal_scheduled",
            "reason": "Back-fill — customer was already notified by phone.",
            "send_notifications": False,
        },
        headers=_auth(admin["access_token"]),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["notifications_dispatched"] is False

    # No notification job for this record's customer.
    jobs = (
        (
            await db_session.execute(
                select(NotificationJob).where(
                    NotificationJob.template == "status_appraisal_scheduled"
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(jobs) == 0

    # AuditLog still written.
    audit = (
        await db_session.execute(
            select(AuditLog)
            .where(AuditLog.event_type == "equipment_record.status_admin_override")
            .where(AuditLog.target_id == uuid.UUID(rec_id))
        )
    ).scalar_one()
    assert audit.after_state["notifications_dispatched"] is False


@pytest.mark.asyncio
async def test_admin_transition_force_send_on_internal_status(
    client: AsyncClient, db_session: AsyncSession
):
    """new_request → appraiser_assigned is a non-customer-facing transition.
    With send_notifications=True the admin force-dispatches anyway (rare,
    but the override is the whole point of the toggle)."""
    admin = await _user_with_role(client, db_session, "mt_admin3@example.com", "admin")
    customer = await _user_with_role(client, db_session, "mt_cust3@example.com", "customer")
    rec_id = await _create_record_for(client, customer["access_token"])

    resp = await client.post(
        f"/api/v1/admin/equipment/{rec_id}/transition",
        json={
            "to_status": "appraiser_assigned",
            "reason": "Manual route assignment override.",
            "send_notifications": True,
        },
        headers=_auth(admin["access_token"]),
    )
    assert resp.status_code == 200
    assert resp.json()["notifications_dispatched"] is True

    # Customer gets the email even though the registry default is silent.
    jobs = (
        (
            await db_session.execute(
                select(NotificationJob).where(
                    NotificationJob.template == "status_appraiser_assigned"
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(jobs) == 1


@pytest.mark.asyncio
async def test_admin_transition_rejects_forbidden_edge(
    client: AsyncClient, db_session: AsyncSession
):
    admin = await _user_with_role(client, db_session, "mt_admin4@example.com", "admin")
    customer = await _user_with_role(client, db_session, "mt_cust4@example.com", "customer")
    rec_id = await _create_record_for(client, customer["access_token"])

    # Promote to a terminal state, then attempt to walk back.
    rec = (
        await db_session.execute(select(EquipmentRecord).where(EquipmentRecord.id == rec_id))
    ).scalar_one()
    rec.status = "sold"
    await db_session.flush()

    resp = await client.post(
        f"/api/v1/admin/equipment/{rec_id}/transition",
        json={
            "to_status": "new_request",
            "reason": "fat-fingered",
        },
        headers=_auth(admin["access_token"]),
    )
    assert resp.status_code == 409
    assert "cannot transition" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_admin_transition_rejects_unknown_status(
    client: AsyncClient, db_session: AsyncSession
):
    admin = await _user_with_role(client, db_session, "mt_admin5@example.com", "admin")
    customer = await _user_with_role(client, db_session, "mt_cust5@example.com", "customer")
    rec_id = await _create_record_for(client, customer["access_token"])

    resp = await client.post(
        f"/api/v1/admin/equipment/{rec_id}/transition",
        json={"to_status": "definitely_not_a_status", "reason": "test"},
        headers=_auth(admin["access_token"]),
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_admin_transition_404_when_record_missing(
    client: AsyncClient, db_session: AsyncSession
):
    admin = await _user_with_role(client, db_session, "mt_admin6@example.com", "admin")
    fake_id = uuid.uuid4()
    resp = await client.post(
        f"/api/v1/admin/equipment/{fake_id}/transition",
        json={"to_status": "appraisal_scheduled", "reason": "test"},
        headers=_auth(admin["access_token"]),
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_admin_transition_blocked_for_sales_role(
    client: AsyncClient, db_session: AsyncSession
):
    sales = await _user_with_role(client, db_session, "mt_sales@example.com", "sales")
    customer = await _user_with_role(client, db_session, "mt_sales_cust@example.com", "customer")
    rec_id = await _create_record_for(client, customer["access_token"])

    resp = await client.post(
        f"/api/v1/admin/equipment/{rec_id}/transition",
        json={"to_status": "appraisal_scheduled", "reason": "trying"},
        headers=_auth(sales["access_token"]),
    )
    assert resp.status_code == 403

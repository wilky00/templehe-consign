# ABOUTME: Phase 3 Sprint 2 — PATCH /sales/change-requests/{id} (Phase 2 Feature 2.4.3 carry-over).
# ABOUTME: Withdraw on resolve flips record.status; every path sends customer resolution email.
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import (
    AuditLog,
    ChangeRequest,
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
        reg = await client.post(
            "/api/v1/auth/register",
            json={
                "email": email,
                "password": _VALID_PASSWORD,
                "first_name": "T",
                "last_name": "U",
                "tos_version": "1",
                "privacy_version": "1",
            },
        )
    assert reg.status_code == 201
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


async def _customer_with_change_request(
    client: AsyncClient, db: AsyncSession, cust_email: str, request_type: str
) -> tuple[uuid.UUID, uuid.UUID]:
    """Returns (equipment_record_id, change_request_id)."""
    with patch("services.email_service.send_email", new_callable=AsyncMock):
        reg = await client.post(
            "/api/v1/auth/register",
            json={
                "email": cust_email,
                "password": _VALID_PASSWORD,
                "first_name": "C",
                "last_name": "U",
                "tos_version": "1",
                "privacy_version": "1",
            },
        )
    assert reg.status_code == 201
    u = (await db.execute(select(User).where(User.email == cust_email.lower()))).scalar_one()
    u.status = "active"
    await db.flush()
    with patch("services.email_service.send_email", new_callable=AsyncMock):
        login = await client.post(
            "/api/v1/auth/login",
            json={"email": cust_email, "password": _VALID_PASSWORD},
        )
    tok = login.json()["access_token"]
    rec = await client.post(
        "/api/v1/me/equipment",
        json={"photos": []},
        headers={"Authorization": f"Bearer {tok}"},
    )
    rec_id = uuid.UUID(rec.json()["id"])
    cr = await client.post(
        f"/api/v1/me/equipment/{rec_id}/change-requests",
        json={"request_type": request_type, "customer_notes": "test notes"},
        headers={"Authorization": f"Bearer {tok}"},
    )
    assert cr.status_code == 201, cr.json()
    return rec_id, uuid.UUID(cr.json()["id"])


def _auth(tok: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {tok}"}


@pytest.mark.asyncio
async def test_resolve_happy_path_persists_and_emails_customer(
    client: AsyncClient, db_session: AsyncSession
):
    mgr = await _user_with_role(client, db_session, "crres_m@example.com", "sales_manager")
    rec_id, cr_id = await _customer_with_change_request(
        client, db_session, "crres_c@example.com", "edit_details"
    )

    resp = await client.patch(
        f"/api/v1/sales/change-requests/{cr_id}",
        json={"status": "resolved", "resolution_notes": "Description corrected by rep."},
        headers=_auth(mgr["access_token"]),
    )
    assert resp.status_code == 200, resp.json()
    body = resp.json()
    assert body["status"] == "resolved"
    assert body["resolved_by"] == mgr["user_id"]
    assert body["equipment_record_status"] == "new_request"  # non-withdraw path keeps status

    cr = (
        await db_session.execute(select(ChangeRequest).where(ChangeRequest.id == cr_id))
    ).scalar_one()
    assert cr.resolution_notes == "Description corrected by rep."
    assert cr.resolved_at is not None

    emails = (
        (
            await db_session.execute(
                select(NotificationJob).where(
                    NotificationJob.template == "customer_change_request_resolution"
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(emails) == 1
    assert "resolved" in emails[0].payload["subject"].lower()


@pytest.mark.asyncio
async def test_resolve_withdraw_flips_record_to_withdrawn(
    client: AsyncClient, db_session: AsyncSession
):
    mgr = await _user_with_role(client, db_session, "crres_w_m@example.com", "sales_manager")
    rec_id, cr_id = await _customer_with_change_request(
        client, db_session, "crres_w_c@example.com", "withdraw"
    )

    resp = await client.patch(
        f"/api/v1/sales/change-requests/{cr_id}",
        json={"status": "resolved", "resolution_notes": "Customer asked to remove."},
        headers=_auth(mgr["access_token"]),
    )
    assert resp.status_code == 200
    assert resp.json()["equipment_record_status"] == "withdrawn"

    rec = (
        await db_session.execute(select(EquipmentRecord).where(EquipmentRecord.id == rec_id))
    ).scalar_one()
    assert rec.status == "withdrawn"


@pytest.mark.asyncio
async def test_resolve_rejected_does_not_flip_status(client: AsyncClient, db_session: AsyncSession):
    mgr = await _user_with_role(client, db_session, "crres_rej_m@example.com", "sales_manager")
    rec_id, cr_id = await _customer_with_change_request(
        client, db_session, "crres_rej_c@example.com", "withdraw"
    )

    resp = await client.patch(
        f"/api/v1/sales/change-requests/{cr_id}",
        json={"status": "rejected", "resolution_notes": "Customer already shipped it."},
        headers=_auth(mgr["access_token"]),
    )
    assert resp.status_code == 200
    assert resp.json()["equipment_record_status"] == "new_request"  # untouched


@pytest.mark.asyncio
async def test_resolve_already_resolved_returns_409(client: AsyncClient, db_session: AsyncSession):
    mgr = await _user_with_role(client, db_session, "crres_dup_m@example.com", "sales_manager")
    _rec_id, cr_id = await _customer_with_change_request(
        client, db_session, "crres_dup_c@example.com", "edit_details"
    )

    first = await client.patch(
        f"/api/v1/sales/change-requests/{cr_id}",
        json={"status": "resolved", "resolution_notes": "Done."},
        headers=_auth(mgr["access_token"]),
    )
    assert first.status_code == 200

    again = await client.patch(
        f"/api/v1/sales/change-requests/{cr_id}",
        json={"status": "rejected", "resolution_notes": "Changed my mind."},
        headers=_auth(mgr["access_token"]),
    )
    assert again.status_code == 409


@pytest.mark.asyncio
async def test_resolve_writes_audit_event(client: AsyncClient, db_session: AsyncSession):
    mgr = await _user_with_role(client, db_session, "crres_aud_m@example.com", "sales_manager")
    _rec_id, cr_id = await _customer_with_change_request(
        client, db_session, "crres_aud_c@example.com", "edit_details"
    )

    await client.patch(
        f"/api/v1/sales/change-requests/{cr_id}",
        json={"status": "resolved", "resolution_notes": "Fixed."},
        headers=_auth(mgr["access_token"]),
    )
    events = (
        (
            await db_session.execute(
                select(AuditLog).where(AuditLog.event_type == "change_request.resolved")
            )
        )
        .scalars()
        .all()
    )
    assert any(e.target_id == cr_id for e in events)


@pytest.mark.asyncio
async def test_customer_cannot_resolve_change_request(
    client: AsyncClient, db_session: AsyncSession
):
    _rec_id, cr_id = await _customer_with_change_request(
        client, db_session, "crres_forbid_c@example.com", "edit_details"
    )
    cust2 = await _user_with_role(client, db_session, "crres_forbid_other@example.com", "customer")
    resp = await client.patch(
        f"/api/v1/sales/change-requests/{cr_id}",
        json={"status": "resolved"},
        headers=_auth(cust2["access_token"]),
    )
    assert resp.status_code == 403

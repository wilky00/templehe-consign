# ABOUTME: Phase 3 Sprint 2 — PATCH /sales/equipment/{id} with lock requirement.
# ABOUTME: Exercises lock-held guard, role validation on assigned user, audit trail.
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import AuditLog, EquipmentRecord, Role, User

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
    assert reg.status_code == 201, reg.json()
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


async def _customer_record(client: AsyncClient, db: AsyncSession, email: str) -> uuid.UUID:
    with patch("services.email_service.send_email", new_callable=AsyncMock):
        reg = await client.post(
            "/api/v1/auth/register",
            json={
                "email": email,
                "password": _VALID_PASSWORD,
                "first_name": "C",
                "last_name": "U",
                "tos_version": "1",
                "privacy_version": "1",
            },
        )
    assert reg.status_code == 201
    u = (await db.execute(select(User).where(User.email == email.lower()))).scalar_one()
    u.status = "active"
    await db.flush()
    with patch("services.email_service.send_email", new_callable=AsyncMock):
        login = await client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": _VALID_PASSWORD},
        )
    tok = login.json()["access_token"]
    resp = await client.post(
        "/api/v1/me/equipment",
        json={"photos": []},
        headers={"Authorization": f"Bearer {tok}"},
    )
    return uuid.UUID(resp.json()["id"])


def _auth(tok: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {tok}"}


@pytest.mark.asyncio
async def test_patch_without_lock_returns_409(client: AsyncClient, db_session: AsyncSession):
    mgr = await _user_with_role(client, db_session, "pat_nolock@example.com", "sales_manager")
    rec_id = await _customer_record(client, db_session, "pat_nolock_c@example.com")

    resp = await client.patch(
        f"/api/v1/sales/equipment/{rec_id}",
        json={"assigned_sales_rep_id": mgr["user_id"]},
        headers=_auth(mgr["access_token"]),
    )
    assert resp.status_code == 409
    assert "lock" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_patch_sales_rep_assignment_writes_audit_event(
    client: AsyncClient, db_session: AsyncSession
):
    mgr = await _user_with_role(client, db_session, "pat_ok_mgr@example.com", "sales_manager")
    rep = await _user_with_role(client, db_session, "pat_ok_rep@example.com", "sales")
    rec_id = await _customer_record(client, db_session, "pat_ok_c@example.com")

    # Acquire lock first.
    lock = await client.post(
        "/api/v1/record-locks",
        json={"record_id": str(rec_id)},
        headers=_auth(mgr["access_token"]),
    )
    assert lock.status_code == 200

    resp = await client.patch(
        f"/api/v1/sales/equipment/{rec_id}",
        json={"assigned_sales_rep_id": rep["user_id"]},
        headers=_auth(mgr["access_token"]),
    )
    assert resp.status_code == 200
    assert resp.json()["assigned_sales_rep_id"] == rep["user_id"]

    events = (
        (
            await db_session.execute(
                select(AuditLog).where(AuditLog.event_type == "equipment_record.assignment_changed")
            )
        )
        .scalars()
        .all()
    )
    match = next((e for e in events if e.target_id == rec_id), None)
    assert match is not None
    assert match.actor_id == uuid.UUID(mgr["user_id"])
    assert match.after_state["assigned_sales_rep_id"] == rep["user_id"]
    assert match.before_state["assigned_sales_rep_id"] is None


@pytest.mark.asyncio
async def test_patch_rejects_assigning_customer_as_sales_rep(
    client: AsyncClient, db_session: AsyncSession
):
    mgr = await _user_with_role(client, db_session, "pat_badrole_m@example.com", "sales_manager")
    rec_id = await _customer_record(client, db_session, "pat_badrole_c@example.com")
    wrong = await _user_with_role(client, db_session, "pat_badrole_x@example.com", "customer")

    await client.post(
        "/api/v1/record-locks",
        json={"record_id": str(rec_id)},
        headers=_auth(mgr["access_token"]),
    )

    resp = await client.patch(
        f"/api/v1/sales/equipment/{rec_id}",
        json={"assigned_sales_rep_id": wrong["user_id"]},
        headers=_auth(mgr["access_token"]),
    )
    assert resp.status_code == 422
    assert "expected" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_patch_clearing_assignment_is_allowed(client: AsyncClient, db_session: AsyncSession):
    mgr = await _user_with_role(client, db_session, "pat_clear_m@example.com", "sales_manager")
    rep = await _user_with_role(client, db_session, "pat_clear_r@example.com", "sales")
    rec_id = await _customer_record(client, db_session, "pat_clear_c@example.com")

    # Pre-assign in the DB
    rec = (
        await db_session.execute(select(EquipmentRecord).where(EquipmentRecord.id == rec_id))
    ).scalar_one()
    rec.assigned_sales_rep_id = uuid.UUID(rep["user_id"])
    await db_session.flush()

    await client.post(
        "/api/v1/record-locks",
        json={"record_id": str(rec_id)},
        headers=_auth(mgr["access_token"]),
    )
    resp = await client.patch(
        f"/api/v1/sales/equipment/{rec_id}",
        json={"assigned_sales_rep_id": None},
        headers=_auth(mgr["access_token"]),
    )
    assert resp.status_code == 200
    assert resp.json()["assigned_sales_rep_id"] is None


@pytest.mark.asyncio
async def test_patch_missing_fields_returns_422(client: AsyncClient, db_session: AsyncSession):
    mgr = await _user_with_role(client, db_session, "pat_empty_m@example.com", "sales_manager")
    rec_id = await _customer_record(client, db_session, "pat_empty_c@example.com")

    await client.post(
        "/api/v1/record-locks",
        json={"record_id": str(rec_id)},
        headers=_auth(mgr["access_token"]),
    )
    resp = await client.patch(
        f"/api/v1/sales/equipment/{rec_id}",
        json={},
        headers=_auth(mgr["access_token"]),
    )
    assert resp.status_code == 422

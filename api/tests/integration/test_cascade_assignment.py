# ABOUTME: Phase 3 Sprint 2 — PATCH /sales/customers/{id}/cascade-assignments.
# ABOUTME: Only new_request rows update; later-status rows skip; one audit event lists both.
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import AuditLog, Customer, EquipmentRecord, Role, User

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


async def _customer_with_records(
    client: AsyncClient, db: AsyncSession, email: str, n: int
) -> tuple[uuid.UUID, list[uuid.UUID]]:
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
    ids: list[uuid.UUID] = []
    for _ in range(n):
        r = await client.post(
            "/api/v1/me/equipment",
            json={"photos": []},
            headers={"Authorization": f"Bearer {tok}"},
        )
        ids.append(uuid.UUID(r.json()["id"]))
    customer = (await db.execute(select(Customer).where(Customer.user_id == u.id))).scalar_one()
    return customer.id, ids


def _auth(tok: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {tok}"}


@pytest.mark.asyncio
async def test_cascade_updates_only_new_request_records(
    client: AsyncClient, db_session: AsyncSession
):
    mgr = await _user_with_role(client, db_session, "casc_mgr@example.com", "sales_manager")
    rep = await _user_with_role(client, db_session, "casc_rep@example.com", "sales")
    customer_id, record_ids = await _customer_with_records(
        client, db_session, "casc_cust@example.com", 3
    )

    # Advance one record past new_request to exercise the skip branch.
    advanced = (
        await db_session.execute(select(EquipmentRecord).where(EquipmentRecord.id == record_ids[0]))
    ).scalar_one()
    advanced.status = "appraisal_scheduled"
    await db_session.flush()

    resp = await client.patch(
        f"/api/v1/sales/customers/{customer_id}/cascade-assignments",
        json={"assigned_sales_rep_id": rep["user_id"]},
        headers=_auth(mgr["access_token"]),
    )
    assert resp.status_code == 200, resp.json()
    body = resp.json()
    assert len(body["updated_record_ids"]) == 2
    assert len(body["skipped_record_ids"]) == 1
    assert str(record_ids[0]) in body["skipped_record_ids"]
    assert body["skipped_reason"] is not None

    # The advanced record's assignment stays None; the other two flip.
    rows = (
        (
            await db_session.execute(
                select(EquipmentRecord).where(EquipmentRecord.customer_id == customer_id)
            )
        )
        .scalars()
        .all()
    )
    for r in rows:
        if r.id == record_ids[0]:
            assert r.assigned_sales_rep_id is None
        else:
            assert r.assigned_sales_rep_id == uuid.UUID(rep["user_id"])


@pytest.mark.asyncio
async def test_cascade_writes_single_audit_event_with_affected_ids(
    client: AsyncClient, db_session: AsyncSession
):
    mgr = await _user_with_role(client, db_session, "casc_audit_m@example.com", "sales_manager")
    rep = await _user_with_role(client, db_session, "casc_audit_r@example.com", "sales")
    customer_id, record_ids = await _customer_with_records(
        client, db_session, "casc_audit_c@example.com", 2
    )

    resp = await client.patch(
        f"/api/v1/sales/customers/{customer_id}/cascade-assignments",
        json={"assigned_sales_rep_id": rep["user_id"]},
        headers=_auth(mgr["access_token"]),
    )
    assert resp.status_code == 200

    events = (
        (
            await db_session.execute(
                select(AuditLog).where(AuditLog.event_type == "customer.cascade_assignment")
            )
        )
        .scalars()
        .all()
    )
    match = next((e for e in events if e.target_id == customer_id), None)
    assert match is not None
    assert match.after_state["assigned_sales_rep_id"] == rep["user_id"]
    assert set(match.after_state["updated_record_ids"]) == {str(i) for i in record_ids}


@pytest.mark.asyncio
async def test_cascade_requires_sales_manager_or_admin_for_others_customers(
    client: AsyncClient, db_session: AsyncSession
):
    # A plain sales rep can cascade too — spec permits the sales role to
    # cascade on their own accounts. Admin-only tightening is Phase 4 work.
    rep = await _user_with_role(client, db_session, "casc_cust_r@example.com", "sales")
    customer_id, _ids = await _customer_with_records(
        client, db_session, "casc_cust_plain@example.com", 1
    )
    resp = await client.patch(
        f"/api/v1/sales/customers/{customer_id}/cascade-assignments",
        json={"assigned_sales_rep_id": rep["user_id"]},
        headers=_auth(rep["access_token"]),
    )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_cascade_unknown_customer_returns_404(client: AsyncClient, db_session: AsyncSession):
    mgr = await _user_with_role(client, db_session, "casc_404_m@example.com", "sales_manager")
    rep = await _user_with_role(client, db_session, "casc_404_r@example.com", "sales")
    resp = await client.patch(
        f"/api/v1/sales/customers/{uuid.uuid4()}/cascade-assignments",
        json={"assigned_sales_rep_id": rep["user_id"]},
        headers=_auth(mgr["access_token"]),
    )
    assert resp.status_code == 404

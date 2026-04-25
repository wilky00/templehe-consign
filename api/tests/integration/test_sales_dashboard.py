# ABOUTME: Phase 3 Sprint 2 — sales rep dashboard (grouped by customer, filter, RBAC).
# ABOUTME: Covers scope=mine default, scope=all manager-only, status filter, empty-state.
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import EquipmentRecord, Role, User

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
                "first_name": "Test",
                "last_name": "User",
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


async def _customer_with_records(
    client: AsyncClient, db: AsyncSession, email: str, n_records: int
) -> list[uuid.UUID]:
    """Register a customer, activate, submit N intakes. Returns record IDs."""
    with patch("services.email_service.send_email", new_callable=AsyncMock):
        reg = await client.post(
            "/api/v1/auth/register",
            json={
                "email": email,
                "password": _VALID_PASSWORD,
                "first_name": "Cust",
                "last_name": "Omer",
                "tos_version": "1",
                "privacy_version": "1",
            },
        )
    assert reg.status_code == 201
    cust = (await db.execute(select(User).where(User.email == email.lower()))).scalar_one()
    cust.status = "active"
    await db.flush()
    with patch("services.email_service.send_email", new_callable=AsyncMock):
        login = await client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": _VALID_PASSWORD},
        )
    token = login.json()["access_token"]
    ids: list[uuid.UUID] = []
    for _ in range(n_records):
        resp = await client.post(
            "/api/v1/me/equipment",
            json={"photos": []},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 201, resp.json()
        ids.append(uuid.UUID(resp.json()["id"]))
    return ids


def _auth(tok: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {tok}"}


# ---------------------------------------------------------------------------
# Dashboard — RBAC
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dashboard_requires_sales_role(client: AsyncClient, db_session: AsyncSession):
    cust = await _user_with_role(client, db_session, "dash_cust@example.com", "customer")
    resp = await client.get("/api/v1/sales/dashboard", headers=_auth(cust["access_token"]))
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_dashboard_unauth_returns_401(client: AsyncClient):
    resp = await client.get("/api/v1/sales/dashboard")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Dashboard — scope=mine / scope=all / empty
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dashboard_scope_mine_only_shows_records_assigned_to_me(
    client: AsyncClient, db_session: AsyncSession
):
    rep_a = await _user_with_role(client, db_session, "dash_a@example.com", "sales")
    rep_b = await _user_with_role(client, db_session, "dash_b@example.com", "sales")
    [rec_id] = await _customer_with_records(client, db_session, "dash_c1@example.com", 1)

    # Assign the record to rep A.
    rec = (
        await db_session.execute(select(EquipmentRecord).where(EquipmentRecord.id == rec_id))
    ).scalar_one()
    rec.assigned_sales_rep_id = uuid.UUID(rep_a["user_id"])
    await db_session.flush()

    a_resp = await client.get("/api/v1/sales/dashboard", headers=_auth(rep_a["access_token"]))
    assert a_resp.status_code == 200
    a = a_resp.json()
    assert a["total_records"] == 1
    assert len(a["customers"]) == 1

    b_resp = await client.get("/api/v1/sales/dashboard", headers=_auth(rep_b["access_token"]))
    assert b_resp.json()["total_records"] == 0


@pytest.mark.asyncio
async def test_dashboard_scope_all_requires_manager_or_admin(
    client: AsyncClient, db_session: AsyncSession
):
    rep = await _user_with_role(client, db_session, "dash_scope_sales@example.com", "sales")
    mgr = await _user_with_role(client, db_session, "dash_scope_mgr@example.com", "sales_manager")
    [rec_id] = await _customer_with_records(client, db_session, "dash_scope_c@example.com", 1)

    # Leave the record unassigned — rep sees nothing, mgr sees everything.
    rep_all = await client.get(
        "/api/v1/sales/dashboard?scope=all", headers=_auth(rep["access_token"])
    )
    assert rep_all.json()["total_records"] == 0  # silently demoted to mine

    mgr_all = await client.get(
        "/api/v1/sales/dashboard?scope=all", headers=_auth(mgr["access_token"])
    )
    assert mgr_all.json()["total_records"] == 1


@pytest.mark.asyncio
async def test_dashboard_status_filter(client: AsyncClient, db_session: AsyncSession):
    mgr = await _user_with_role(client, db_session, "dash_filter_m@example.com", "sales_manager")
    ids = await _customer_with_records(client, db_session, "dash_filter_c@example.com", 3)

    # Move one record to a later status to exercise the filter.
    rec = (
        await db_session.execute(select(EquipmentRecord).where(EquipmentRecord.id == ids[0]))
    ).scalar_one()
    rec.status = "appraisal_scheduled"
    await db_session.flush()

    resp = await client.get(
        "/api/v1/sales/dashboard?scope=all&status=new_request",
        headers=_auth(mgr["access_token"]),
    )
    assert resp.status_code == 200
    assert resp.json()["total_records"] == 2


@pytest.mark.asyncio
async def test_dashboard_groups_records_under_same_customer(
    client: AsyncClient, db_session: AsyncSession
):
    mgr = await _user_with_role(client, db_session, "dash_group_m@example.com", "sales_manager")
    ids = await _customer_with_records(client, db_session, "dash_group_c@example.com", 3)

    resp = await client.get("/api/v1/sales/dashboard?scope=all", headers=_auth(mgr["access_token"]))
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["customers"]) == 1
    group = body["customers"][0]
    assert group["total_items"] == 3
    assert len(group["records"]) == 3
    assert {r["id"] for r in group["records"]} == {str(i) for i in ids}

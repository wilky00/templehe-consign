# ABOUTME: Phase 3 Sprint 3 — admin CRUD over /admin/routing-rules with admin-only RBAC.
# ABOUTME: Condition shape per rule_type, sparse PATCH, and the include_deleted query knob.
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import LeadRoutingRule, Role, User

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


def _auth(tok: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {tok}"}


@pytest.mark.asyncio
async def test_create_ad_hoc_rule_as_admin_succeeds(client: AsyncClient, db_session: AsyncSession):
    admin = await _user_with_role(client, db_session, "ar_admin@example.com", "admin")
    rep = await _user_with_role(client, db_session, "ar_rep@example.com", "sales")

    resp = await client.post(
        "/api/v1/admin/routing-rules",
        json={
            "rule_type": "ad_hoc",
            "priority": 10,
            "conditions": {"condition_type": "email_domain", "value": "acme.com"},
            "assigned_user_id": rep["user_id"],
            "is_active": True,
        },
        headers=_auth(admin["access_token"]),
    )
    assert resp.status_code == 201, resp.json()
    body = resp.json()
    assert body["rule_type"] == "ad_hoc"
    assert body["created_by"] == admin["user_id"]
    assert body["assigned_user_id"] == rep["user_id"]
    assert body["deleted_at"] is None


@pytest.mark.asyncio
async def test_create_rule_blocked_for_non_admin_role(
    client: AsyncClient, db_session: AsyncSession
):
    mgr = await _user_with_role(client, db_session, "ar_mgr@example.com", "sales_manager")
    rep = await _user_with_role(client, db_session, "ar_rep_blocked@example.com", "sales")

    resp = await client.post(
        "/api/v1/admin/routing-rules",
        json={
            "rule_type": "ad_hoc",
            "conditions": {"condition_type": "email_domain", "value": "acme.com"},
            "assigned_user_id": rep["user_id"],
        },
        headers=_auth(mgr["access_token"]),
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_round_robin_requires_non_empty_rep_ids(
    client: AsyncClient, db_session: AsyncSession
):
    admin = await _user_with_role(client, db_session, "ar_rr_admin@example.com", "admin")

    resp = await client.post(
        "/api/v1/admin/routing-rules",
        json={
            "rule_type": "round_robin",
            "conditions": {"rep_ids": []},
        },
        headers=_auth(admin["access_token"]),
    )
    assert resp.status_code == 422
    assert "rep_ids" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_assigned_user_must_have_sales_role(client: AsyncClient, db_session: AsyncSession):
    admin = await _user_with_role(client, db_session, "ar_role_admin@example.com", "admin")
    customer = await _user_with_role(client, db_session, "ar_cust@example.com", "customer")

    resp = await client.post(
        "/api/v1/admin/routing-rules",
        json={
            "rule_type": "ad_hoc",
            "conditions": {"condition_type": "email_domain", "value": "x.com"},
            "assigned_user_id": customer["user_id"],
        },
        headers=_auth(admin["access_token"]),
    )
    assert resp.status_code == 422
    assert "expected" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_patch_priority_only_keeps_other_fields(
    client: AsyncClient, db_session: AsyncSession
):
    admin = await _user_with_role(client, db_session, "ar_p_admin@example.com", "admin")
    rep = await _user_with_role(client, db_session, "ar_p_rep@example.com", "sales")

    create = await client.post(
        "/api/v1/admin/routing-rules",
        json={
            "rule_type": "geographic",
            "priority": 100,
            "conditions": {"state_list": ["CA"]},
            "assigned_user_id": rep["user_id"],
        },
        headers=_auth(admin["access_token"]),
    )
    rule_id = create.json()["id"]

    resp = await client.patch(
        f"/api/v1/admin/routing-rules/{rule_id}",
        json={"priority": 75},
        headers=_auth(admin["access_token"]),
    )
    assert resp.status_code == 200, resp.json()
    body = resp.json()
    assert body["priority"] == 75
    assert body["conditions"] == {"state_list": ["CA"]}
    assert body["assigned_user_id"] == rep["user_id"]


@pytest.mark.asyncio
async def test_patch_clears_assigned_user_with_explicit_null(
    client: AsyncClient, db_session: AsyncSession
):
    admin = await _user_with_role(client, db_session, "ar_n_admin@example.com", "admin")
    rep = await _user_with_role(client, db_session, "ar_n_rep@example.com", "sales")

    create = await client.post(
        "/api/v1/admin/routing-rules",
        json={
            "rule_type": "ad_hoc",
            "conditions": {"condition_type": "email_domain", "value": "acme.com"},
            "assigned_user_id": rep["user_id"],
        },
        headers=_auth(admin["access_token"]),
    )
    rule_id = create.json()["id"]

    resp = await client.patch(
        f"/api/v1/admin/routing-rules/{rule_id}",
        json={"assigned_user_id": None},
        headers=_auth(admin["access_token"]),
    )
    assert resp.status_code == 200
    assert resp.json()["assigned_user_id"] is None


@pytest.mark.asyncio
async def test_delete_soft_deletes_and_list_excludes_by_default(
    client: AsyncClient, db_session: AsyncSession
):
    admin = await _user_with_role(client, db_session, "ar_del_admin@example.com", "admin")
    rep = await _user_with_role(client, db_session, "ar_del_rep@example.com", "sales")

    create = await client.post(
        "/api/v1/admin/routing-rules",
        json={
            "rule_type": "ad_hoc",
            "conditions": {"condition_type": "email_domain", "value": "acme.com"},
            "assigned_user_id": rep["user_id"],
        },
        headers=_auth(admin["access_token"]),
    )
    rule_id = create.json()["id"]

    delete = await client.delete(
        f"/api/v1/admin/routing-rules/{rule_id}",
        headers=_auth(admin["access_token"]),
    )
    assert delete.status_code == 200
    assert delete.json()["deleted_at"] is not None
    assert delete.json()["is_active"] is False

    listed = await client.get(
        "/api/v1/admin/routing-rules",
        headers=_auth(admin["access_token"]),
    )
    assert listed.status_code == 200
    ids = [r["id"] for r in listed.json()["rules"]]
    assert rule_id not in ids

    listed_all = await client.get(
        "/api/v1/admin/routing-rules?include_deleted=true",
        headers=_auth(admin["access_token"]),
    )
    ids_all = [r["id"] for r in listed_all.json()["rules"]]
    assert rule_id in ids_all

    # Row is preserved in the DB.
    db_row = (
        await db_session.execute(
            select(LeadRoutingRule).where(LeadRoutingRule.id == uuid.UUID(rule_id))
        )
    ).scalar_one()
    assert db_row.deleted_at is not None

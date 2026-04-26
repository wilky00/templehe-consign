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


# --- Sprint 4: priority uniqueness + reorder ---------------------------- #


@pytest.mark.asyncio
async def test_create_blocks_duplicate_priority_in_same_rule_type(
    client: AsyncClient, db_session: AsyncSession
):
    admin = await _user_with_role(client, db_session, "ar_dup_admin@example.com", "admin")
    rep = await _user_with_role(client, db_session, "ar_dup_rep@example.com", "sales")

    first = await client.post(
        "/api/v1/admin/routing-rules",
        json={
            "rule_type": "ad_hoc",
            "priority": 50,
            "conditions": {"condition_type": "email_domain", "value": "a.com"},
            "assigned_user_id": rep["user_id"],
        },
        headers=_auth(admin["access_token"]),
    )
    assert first.status_code == 201, first.json()

    second = await client.post(
        "/api/v1/admin/routing-rules",
        json={
            "rule_type": "ad_hoc",
            "priority": 50,
            "conditions": {"condition_type": "email_domain", "value": "b.com"},
            "assigned_user_id": rep["user_id"],
        },
        headers=_auth(admin["access_token"]),
    )
    assert second.status_code == 409, second.json()
    assert "priority 50" in second.json()["detail"]


@pytest.mark.asyncio
async def test_reorder_renumbers_atomically_and_persists(
    client: AsyncClient, db_session: AsyncSession
):
    admin = await _user_with_role(client, db_session, "ar_reorder_admin@example.com", "admin")
    rep = await _user_with_role(client, db_session, "ar_reorder_rep@example.com", "sales")

    ids = []
    for prio in (10, 20, 30):
        resp = await client.post(
            "/api/v1/admin/routing-rules",
            json={
                "rule_type": "geographic",
                "priority": prio,
                "conditions": {"state_list": ["TX"]},
                "assigned_user_id": rep["user_id"],
            },
            headers=_auth(admin["access_token"]),
        )
        ids.append(resp.json()["id"])

    # Reverse the order.
    new_order = list(reversed(ids))
    reorder = await client.post(
        "/api/v1/admin/routing-rules/reorder",
        json={"rule_type": "geographic", "ordered_ids": new_order},
        headers=_auth(admin["access_token"]),
    )
    assert reorder.status_code == 200, reorder.json()
    body = reorder.json()
    # New priorities are dense 0..N-1 in the requested order.
    by_id = {r["id"]: r for r in body["rules"]}
    assert by_id[new_order[0]]["priority"] == 0
    assert by_id[new_order[1]]["priority"] == 1
    assert by_id[new_order[2]]["priority"] == 2

    # Re-listing reflects the persisted order.
    listed = await client.get(
        "/api/v1/admin/routing-rules",
        headers=_auth(admin["access_token"]),
    )
    geo_rules = [r for r in listed.json()["rules"] if r["rule_type"] == "geographic"]
    geo_rules.sort(key=lambda r: r["priority"])
    assert [r["id"] for r in geo_rules] == new_order


@pytest.mark.asyncio
async def test_reorder_rejects_partial_id_list(client: AsyncClient, db_session: AsyncSession):
    admin = await _user_with_role(client, db_session, "ar_partial_admin@example.com", "admin")
    rep = await _user_with_role(client, db_session, "ar_partial_rep@example.com", "sales")

    ids = []
    for prio in (1, 2):
        resp = await client.post(
            "/api/v1/admin/routing-rules",
            json={
                "rule_type": "ad_hoc",
                "priority": prio,
                "conditions": {"condition_type": "email_domain", "value": f"d{prio}.com"},
                "assigned_user_id": rep["user_id"],
            },
            headers=_auth(admin["access_token"]),
        )
        ids.append(resp.json()["id"])

    # Pass only one of the two ids — service must reject.
    resp = await client.post(
        "/api/v1/admin/routing-rules/reorder",
        json={"rule_type": "ad_hoc", "ordered_ids": [ids[0]]},
        headers=_auth(admin["access_token"]),
    )
    assert resp.status_code == 422
    assert "ordered_ids" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_reorder_rejects_duplicate_ids(client: AsyncClient, db_session: AsyncSession):
    admin = await _user_with_role(client, db_session, "ar_dup2_admin@example.com", "admin")
    rep = await _user_with_role(client, db_session, "ar_dup2_rep@example.com", "sales")

    create = await client.post(
        "/api/v1/admin/routing-rules",
        json={
            "rule_type": "ad_hoc",
            "priority": 5,
            "conditions": {"condition_type": "email_domain", "value": "x.com"},
            "assigned_user_id": rep["user_id"],
        },
        headers=_auth(admin["access_token"]),
    )
    rule_id = create.json()["id"]

    resp = await client.post(
        "/api/v1/admin/routing-rules/reorder",
        json={"rule_type": "ad_hoc", "ordered_ids": [rule_id, rule_id]},
        headers=_auth(admin["access_token"]),
    )
    assert resp.status_code == 422
    assert "duplicate" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_reorder_blocked_for_non_admin(client: AsyncClient, db_session: AsyncSession):
    admin = await _user_with_role(client, db_session, "ar_rb_admin@example.com", "admin")
    rep = await _user_with_role(client, db_session, "ar_rb_rep@example.com", "sales")
    create = await client.post(
        "/api/v1/admin/routing-rules",
        json={
            "rule_type": "ad_hoc",
            "priority": 100,
            "conditions": {"condition_type": "email_domain", "value": "z.com"},
            "assigned_user_id": rep["user_id"],
        },
        headers=_auth(admin["access_token"]),
    )
    rule_id = create.json()["id"]

    resp = await client.post(
        "/api/v1/admin/routing-rules/reorder",
        json={"rule_type": "ad_hoc", "ordered_ids": [rule_id]},
        headers=_auth(rep["access_token"]),
    )
    assert resp.status_code == 403

# ABOUTME: Phase 4 Sprint 4 — POST /admin/routing-rules/{id}/test exercises read-only match.
# ABOUTME: Confirms ad_hoc, geographic (state + metro), and round_robin all return matches.
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import Role, User

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
                "first_name": "Test",
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


# --- ad_hoc ------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_test_rule_ad_hoc_email_domain_matches(client: AsyncClient, db_session: AsyncSession):
    admin = await _user_with_role(client, db_session, "tr_admin1@example.com", "admin")
    rep = await _user_with_role(client, db_session, "tr_rep1@example.com", "sales")

    create = await client.post(
        "/api/v1/admin/routing-rules",
        json={
            "rule_type": "ad_hoc",
            "priority": 10,
            "conditions": {"condition_type": "email_domain", "value": "acme.com"},
            "assigned_user_id": rep["user_id"],
        },
        headers=_auth(admin["access_token"]),
    )
    rule_id = create.json()["id"]

    # Match.
    resp = await client.post(
        f"/api/v1/admin/routing-rules/{rule_id}/test",
        json={"customer_email": "buyer@acme.com"},
        headers=_auth(admin["access_token"]),
    )
    assert resp.status_code == 200, resp.json()
    body = resp.json()
    assert body["matched"] is True
    assert body["would_assign_to"] == rep["user_id"]
    assert body["rule_type"] == "ad_hoc"

    # No match.
    no_match = await client.post(
        f"/api/v1/admin/routing-rules/{rule_id}/test",
        json={"customer_email": "buyer@otherdomain.com"},
        headers=_auth(admin["access_token"]),
    )
    assert no_match.status_code == 200
    body2 = no_match.json()
    assert body2["matched"] is False
    assert body2["would_assign_to"] is None


# --- geographic ---------------------------------------------------------- #


@pytest.mark.asyncio
async def test_test_rule_geographic_state_match(client: AsyncClient, db_session: AsyncSession):
    admin = await _user_with_role(client, db_session, "tr_admin2@example.com", "admin")
    rep = await _user_with_role(client, db_session, "tr_rep2@example.com", "sales")

    create = await client.post(
        "/api/v1/admin/routing-rules",
        json={
            "rule_type": "geographic",
            "priority": 50,
            "conditions": {"state_list": ["TX", "CA"]},
            "assigned_user_id": rep["user_id"],
        },
        headers=_auth(admin["access_token"]),
    )
    rule_id = create.json()["id"]

    resp = await client.post(
        f"/api/v1/admin/routing-rules/{rule_id}/test",
        json={"customer_state": "TX"},
        headers=_auth(admin["access_token"]),
    )
    assert resp.status_code == 200, resp.json()
    body = resp.json()
    assert body["matched"] is True
    assert body["would_assign_to"] == rep["user_id"]
    assert "state" in body["reason"].lower()


@pytest.mark.asyncio
async def test_test_rule_geographic_metro_radius_match(
    client: AsyncClient, db_session: AsyncSession
):
    admin = await _user_with_role(client, db_session, "tr_admin3@example.com", "admin")
    rep = await _user_with_role(client, db_session, "tr_rep3@example.com", "sales")

    create = await client.post(
        "/api/v1/admin/routing-rules",
        json={
            "rule_type": "geographic",
            "priority": 60,
            "conditions": {
                "metro_area": {
                    "name": "Denver",
                    "center_lat": 39.7392,
                    "center_lon": -104.9903,
                    "radius_miles": 50,
                }
            },
            "assigned_user_id": rep["user_id"],
        },
        headers=_auth(admin["access_token"]),
    )
    rule_id = create.json()["id"]

    # Within radius (downtown Denver).
    resp = await client.post(
        f"/api/v1/admin/routing-rules/{rule_id}/test",
        json={"customer_lat": 39.74, "customer_lng": -104.99},
        headers=_auth(admin["access_token"]),
    )
    body = resp.json()
    assert body["matched"] is True
    assert "metro" in body["reason"].lower()

    # Outside the radius (NYC ~1500mi away).
    far = await client.post(
        f"/api/v1/admin/routing-rules/{rule_id}/test",
        json={"customer_lat": 40.7, "customer_lng": -74.0},
        headers=_auth(admin["access_token"]),
    )
    assert far.json()["matched"] is False


# --- round_robin --------------------------------------------------------- #


@pytest.mark.asyncio
async def test_test_rule_round_robin_returns_next_rep_without_claiming(
    client: AsyncClient, db_session: AsyncSession
):
    admin = await _user_with_role(client, db_session, "tr_admin4@example.com", "admin")
    rep_a = await _user_with_role(client, db_session, "tr_rep4a@example.com", "sales")
    rep_b = await _user_with_role(client, db_session, "tr_rep4b@example.com", "sales")

    create = await client.post(
        "/api/v1/admin/routing-rules",
        json={
            "rule_type": "round_robin",
            "priority": 200,
            "conditions": {"rep_ids": [rep_a["user_id"], rep_b["user_id"]]},
        },
        headers=_auth(admin["access_token"]),
    )
    rule_id = create.json()["id"]

    # Two consecutive tests should return the SAME pick — no increment.
    a = await client.post(
        f"/api/v1/admin/routing-rules/{rule_id}/test",
        json={},
        headers=_auth(admin["access_token"]),
    )
    b = await client.post(
        f"/api/v1/admin/routing-rules/{rule_id}/test",
        json={},
        headers=_auth(admin["access_token"]),
    )
    assert a.json()["matched"] is True
    assert b.json()["matched"] is True
    assert a.json()["would_assign_to"] == b.json()["would_assign_to"]
    assert a.json()["would_assign_to"] in (rep_a["user_id"], rep_b["user_id"])


# --- 404 / RBAC --------------------------------------------------------- #


@pytest.mark.asyncio
async def test_test_rule_404_for_unknown_rule(client: AsyncClient, db_session: AsyncSession):
    admin = await _user_with_role(client, db_session, "tr_admin5@example.com", "admin")
    fake = uuid.uuid4()
    resp = await client.post(
        f"/api/v1/admin/routing-rules/{fake}/test",
        json={"customer_email": "x@y.com"},
        headers=_auth(admin["access_token"]),
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_test_rule_blocked_for_non_admin(client: AsyncClient, db_session: AsyncSession):
    admin = await _user_with_role(client, db_session, "tr_admin6@example.com", "admin")
    rep = await _user_with_role(client, db_session, "tr_rep6@example.com", "sales")
    create = await client.post(
        "/api/v1/admin/routing-rules",
        json={
            "rule_type": "ad_hoc",
            "priority": 10,
            "conditions": {"condition_type": "email_domain", "value": "acme.com"},
            "assigned_user_id": rep["user_id"],
        },
        headers=_auth(admin["access_token"]),
    )
    rule_id = create.json()["id"]

    resp = await client.post(
        f"/api/v1/admin/routing-rules/{rule_id}/test",
        json={"customer_email": "x@acme.com"},
        headers=_auth(rep["access_token"]),
    )
    assert resp.status_code == 403

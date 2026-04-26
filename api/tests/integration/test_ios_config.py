# ABOUTME: Phase 4 Sprint 3 — iOS config endpoint returns deterministic SHA-256 hash.
# ABOUTME: Mutating any input bumps the hash; same input = same hash; RBAC keeps customers out.
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import EquipmentCategory, Role, User

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
                "first_name": "Ios",
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


@pytest.mark.asyncio
async def test_returns_config_version_sha256_hex(client: AsyncClient, db_session: AsyncSession):
    appr = await _user_with_role(client, db_session, "ios_appr1@example.com", "appraiser")
    resp = await client.get("/api/v1/ios/config", headers=_auth(appr["access_token"]))
    assert resp.status_code == 200, resp.json()
    body = resp.json()
    assert "config_version" in body
    assert isinstance(body["config_version"], str)
    assert len(body["config_version"]) == 64  # SHA-256 hex
    int(body["config_version"], 16)  # is hex
    assert "categories" in body
    assert "inspection_prompts" in body
    assert "red_flag_rules" in body
    assert "app_config" in body


@pytest.mark.asyncio
async def test_two_calls_with_no_changes_return_same_hash(
    client: AsyncClient, db_session: AsyncSession
):
    appr = await _user_with_role(client, db_session, "ios_appr2@example.com", "appraiser")
    a = await client.get("/api/v1/ios/config", headers=_auth(appr["access_token"]))
    b = await client.get("/api/v1/ios/config", headers=_auth(appr["access_token"]))
    assert a.status_code == 200 and b.status_code == 200
    assert a.json()["config_version"] == b.json()["config_version"]


@pytest.mark.asyncio
async def test_mutating_a_category_bumps_hash(client: AsyncClient, db_session: AsyncSession):
    appr = await _user_with_role(client, db_session, "ios_appr3@example.com", "appraiser")
    before = await client.get("/api/v1/ios/config", headers=_auth(appr["access_token"]))
    pre_hash = before.json()["config_version"]

    # Rename one category — should bump the hash deterministically.
    cat = (
        await db_session.execute(
            select(EquipmentCategory).where(EquipmentCategory.deleted_at.is_(None)).limit(1)
        )
    ).scalar_one()
    cat.name = cat.name + " (bumped)"
    await db_session.flush()

    after = await client.get("/api/v1/ios/config", headers=_auth(appr["access_token"]))
    assert after.json()["config_version"] != pre_hash


@pytest.mark.asyncio
async def test_mutating_app_config_bumps_hash(client: AsyncClient, db_session: AsyncSession):
    admin = await _user_with_role(client, db_session, "ios_admin1@example.com", "admin")
    appr = await _user_with_role(client, db_session, "ios_appr4@example.com", "appraiser")

    before = await client.get("/api/v1/ios/config", headers=_auth(appr["access_token"]))
    pre_hash = before.json()["config_version"]

    # Admin flips an AppConfig key.
    patch_resp = await client.patch(
        "/api/v1/admin/config/calendar_buffer_minutes_default",
        json={"value": 45},
        headers=_auth(admin["access_token"]),
    )
    assert patch_resp.status_code == 200, patch_resp.json()

    after = await client.get("/api/v1/ios/config", headers=_auth(appr["access_token"]))
    assert after.json()["config_version"] != pre_hash


@pytest.mark.asyncio
async def test_customer_role_blocked(client: AsyncClient, db_session: AsyncSession):
    cust = await _user_with_role(client, db_session, "ios_cust@example.com", "customer")
    resp = await client.get("/api/v1/ios/config", headers=_auth(cust["access_token"]))
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_admin_can_access_for_qa(client: AsyncClient, db_session: AsyncSession):
    admin = await _user_with_role(client, db_session, "ios_admin_qa@example.com", "admin")
    resp = await client.get("/api/v1/ios/config", headers=_auth(admin["access_token"]))
    assert resp.status_code == 200

# ABOUTME: Phase 4 Sprint 3 — admin reads + writes AppConfig keys via /admin/config.
# ABOUTME: Per-key validators run; bad payloads surface as 422; RBAC admin-only.
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import Role, User
from services import app_config_registry

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
                "first_name": "Cfg",
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
async def test_list_returns_every_registered_key(client: AsyncClient, db_session: AsyncSession):
    admin = await _user_with_role(client, db_session, "ac_cfg_a@example.com", "admin")
    resp = await client.get("/api/v1/admin/config", headers=_auth(admin["access_token"]))
    assert resp.status_code == 200
    body = resp.json()
    names = {item["name"] for item in body["items"]}
    expected = {spec.name for spec in app_config_registry.all_specs()}
    assert names == expected
    # Spot-check shape.
    one = body["items"][0]
    assert {"name", "category", "field_type", "description", "default", "value"}.issubset(one)


@pytest.mark.asyncio
async def test_list_grouped_by_category(client: AsyncClient, db_session: AsyncSession):
    admin = await _user_with_role(client, db_session, "ac_cfg_b@example.com", "admin")
    resp = await client.get("/api/v1/admin/config", headers=_auth(admin["access_token"]))
    items = resp.json()["items"]
    # Items are sorted by (category, name); same-category items should be adjacent.
    seen_categories: list[str] = []
    for item in items:
        cat = item["category"]
        if not seen_categories or seen_categories[-1] != cat:
            assert cat not in seen_categories, f"category {cat} not contiguous"
            seen_categories.append(cat)


@pytest.mark.asyncio
async def test_patch_valid_value_persists_and_returns_new_value(
    client: AsyncClient, db_session: AsyncSession
):
    admin = await _user_with_role(client, db_session, "ac_cfg_c@example.com", "admin")
    resp = await client.patch(
        "/api/v1/admin/config/equipment_record_overdue_threshold_days",
        json={"value": 14},
        headers=_auth(admin["access_token"]),
    )
    assert resp.status_code == 200, resp.json()
    body = resp.json()
    assert body["name"] == "equipment_record_overdue_threshold_days"
    assert body["value"] == 14

    # Subsequent get reflects the new value.
    list_resp = await client.get("/api/v1/admin/config", headers=_auth(admin["access_token"]))
    item = next(
        i
        for i in list_resp.json()["items"]
        if i["name"] == "equipment_record_overdue_threshold_days"
    )
    assert item["value"] == 14


@pytest.mark.asyncio
async def test_patch_invalid_value_returns_422(client: AsyncClient, db_session: AsyncSession):
    admin = await _user_with_role(client, db_session, "ac_cfg_d@example.com", "admin")
    # security_session_ttl_minutes must be in [5, 720]
    resp = await client.patch(
        "/api/v1/admin/config/security_session_ttl_minutes",
        json={"value": 9999},
        headers=_auth(admin["access_token"]),
    )
    assert resp.status_code == 422
    assert "720" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_patch_unknown_key_returns_404(client: AsyncClient, db_session: AsyncSession):
    admin = await _user_with_role(client, db_session, "ac_cfg_e@example.com", "admin")
    resp = await client.patch(
        "/api/v1/admin/config/totally_made_up_key",
        json={"value": 1},
        headers=_auth(admin["access_token"]),
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_patch_intake_visible_rejects_unknown_field(
    client: AsyncClient, db_session: AsyncSession
):
    admin = await _user_with_role(client, db_session, "ac_cfg_f@example.com", "admin")
    resp = await client.patch(
        "/api/v1/admin/config/intake_fields_visible",
        json={"value": ["make", "definitely_not_a_field"]},
        headers=_auth(admin["access_token"]),
    )
    assert resp.status_code == 422
    assert "definitely_not_a_field" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_list_blocked_for_sales_role(client: AsyncClient, db_session: AsyncSession):
    sales = await _user_with_role(client, db_session, "ac_cfg_sales@example.com", "sales")
    resp = await client.get("/api/v1/admin/config", headers=_auth(sales["access_token"]))
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_patch_blocked_for_reporting_role(client: AsyncClient, db_session: AsyncSession):
    rep = await _user_with_role(client, db_session, "ac_cfg_reporting@example.com", "reporting")
    resp = await client.patch(
        "/api/v1/admin/config/equipment_record_overdue_threshold_days",
        json={"value": 14},
        headers=_auth(rep["access_token"]),
    )
    assert resp.status_code == 403

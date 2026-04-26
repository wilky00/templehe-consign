# ABOUTME: Phase 4 Sprint 3 — admin hides intake fields via AppConfig; customer form respects.
# ABOUTME: Verifies /me/equipment/form-config defaults to all canonical fields and respects PATCHes.
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
                "first_name": "Vis",
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
async def test_default_visible_fields_includes_every_canonical_field(
    client: AsyncClient, db_session: AsyncSession
):
    cust = await _user_with_role(client, db_session, "iv_cust1@example.com", "customer")
    resp = await client.get("/api/v1/me/equipment/form-config", headers=_auth(cust["access_token"]))
    assert resp.status_code == 200, resp.json()
    body = resp.json()
    assert set(body["visible_fields"]) == set(app_config_registry.INTAKE_FIELDS_CANONICAL)
    assert body["field_order"] == list(app_config_registry.INTAKE_FIELDS_CANONICAL)


@pytest.mark.asyncio
async def test_admin_hiding_field_removes_it_from_form_config(
    client: AsyncClient, db_session: AsyncSession
):
    admin = await _user_with_role(client, db_session, "iv_admin@example.com", "admin")
    cust = await _user_with_role(client, db_session, "iv_cust2@example.com", "customer")

    # Hide every field except a small subset (year + serial_number stay).
    visible = ["category_id", "make", "model", "description"]
    patch_resp = await client.patch(
        "/api/v1/admin/config/intake_fields_visible",
        json={"value": visible},
        headers=_auth(admin["access_token"]),
    )
    assert patch_resp.status_code == 200, patch_resp.json()

    resp = await client.get("/api/v1/me/equipment/form-config", headers=_auth(cust["access_token"]))
    assert resp.status_code == 200
    body = resp.json()
    assert set(body["visible_fields"]) == set(visible)
    # year was hidden — must not appear in field_order
    assert "year" not in body["field_order"]
    assert "hours" not in body["field_order"]


@pytest.mark.asyncio
async def test_admin_reorder_respected(client: AsyncClient, db_session: AsyncSession):
    admin = await _user_with_role(client, db_session, "iv_admin2@example.com", "admin")
    cust = await _user_with_role(client, db_session, "iv_cust3@example.com", "customer")

    new_order = ["description", "make", "model", "category_id"]
    resp = await client.patch(
        "/api/v1/admin/config/intake_fields_order",
        json={"value": new_order},
        headers=_auth(admin["access_token"]),
    )
    assert resp.status_code == 200, resp.json()

    cfg = await client.get("/api/v1/me/equipment/form-config", headers=_auth(cust["access_token"]))
    body = cfg.json()
    # The four explicitly ordered fields come first, in the order admin set.
    assert body["field_order"][:4] == new_order
    # Remaining canonical fields appear after, in canonical order.
    remaining = [f for f in app_config_registry.INTAKE_FIELDS_CANONICAL if f not in new_order]
    assert body["field_order"][4:] == remaining

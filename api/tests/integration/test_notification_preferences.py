# ABOUTME: Phase 3 Sprint 5 — /me/notification-preferences GET/PUT + role-based hide/RO gates.
# ABOUTME: Default channel, upsert, slack-pref allowed, hidden role 404, customer 403.
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import NotificationPreference, Role, User

_VALID_PASSWORD = "TestPassword1!"


async def _login_user(client: AsyncClient, db: AsyncSession, email: str, role_slug: str) -> str:
    with patch("services.email_service.send_email", new_callable=AsyncMock):
        reg = await client.post(
            "/api/v1/auth/register",
            json={
                "email": email,
                "password": _VALID_PASSWORD,
                "first_name": "Pref",
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
    return login.json()["access_token"]


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_get_returns_email_default_when_no_row(client: AsyncClient, db_session: AsyncSession):
    token = await _login_user(client, db_session, "pref_default@example.com", "sales")
    resp = await client.get("/api/v1/me/notification-preferences", headers=_auth(token))
    assert resp.status_code == 200
    body = resp.json()
    assert body["channel"] == "email"
    assert body["phone_number"] is None
    assert body["slack_user_id"] is None
    assert body["read_only"] is False


@pytest.mark.asyncio
async def test_put_upserts_and_get_reflects(client: AsyncClient, db_session: AsyncSession):
    token = await _login_user(client, db_session, "pref_put@example.com", "sales")
    put = await client.put(
        "/api/v1/me/notification-preferences",
        json={"channel": "sms", "phone_number": "+15551234567"},
        headers=_auth(token),
    )
    assert put.status_code == 200, put.json()
    assert put.json()["channel"] == "sms"
    assert put.json()["phone_number"] == "+15551234567"

    # Second PUT replaces (not duplicates) — UNIQUE(user_id) backed.
    put2 = await client.put(
        "/api/v1/me/notification-preferences",
        json={"channel": "email"},
        headers=_auth(token),
    )
    assert put2.status_code == 200
    assert put2.json()["channel"] == "email"
    assert put2.json()["phone_number"] is None

    rows = await db_session.execute(
        select(NotificationPreference).where(
            NotificationPreference.user_id
            == (
                await db_session.execute(
                    select(User.id).where(User.email == "pref_put@example.com")
                )
            ).scalar_one()
        )
    )
    assert len(list(rows.scalars().all())) == 1


@pytest.mark.asyncio
async def test_put_sms_without_phone_rejected(client: AsyncClient, db_session: AsyncSession):
    token = await _login_user(client, db_session, "pref_smsbad@example.com", "sales")
    resp = await client.put(
        "/api/v1/me/notification-preferences",
        json={"channel": "sms"},
        headers=_auth(token),
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_put_slack_without_user_id_rejected(client: AsyncClient, db_session: AsyncSession):
    token = await _login_user(client, db_session, "pref_slackbad@example.com", "sales")
    resp = await client.put(
        "/api/v1/me/notification-preferences",
        json={"channel": "slack"},
        headers=_auth(token),
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_customer_can_read_but_cannot_edit(client: AsyncClient, db_session: AsyncSession):
    token = await _login_user(client, db_session, "pref_cust@example.com", "customer")
    get = await client.get("/api/v1/me/notification-preferences", headers=_auth(token))
    assert get.status_code == 200
    assert get.json()["read_only"] is True

    put = await client.put(
        "/api/v1/me/notification-preferences",
        json={"channel": "email"},
        headers=_auth(token),
    )
    assert put.status_code == 403


@pytest.mark.asyncio
async def test_hidden_role_404s_both_methods(client: AsyncClient, db_session: AsyncSession):
    token = await _login_user(client, db_session, "pref_hide@example.com", "reporting")

    # Flip the visibility flag to hide the page from the reporting role.
    await db_session.execute(
        text(
            "UPDATE app_config SET value = :val WHERE key = 'notification_preferences_hidden_roles'"
        ),
        {"val": '{"roles": ["reporting"]}'},
    )
    await db_session.flush()

    get = await client.get("/api/v1/me/notification-preferences", headers=_auth(token))
    assert get.status_code == 404

    put = await client.put(
        "/api/v1/me/notification-preferences",
        json={"channel": "email"},
        headers=_auth(token),
    )
    assert put.status_code == 404


@pytest.mark.asyncio
async def test_unauthenticated_request_rejected(client: AsyncClient):
    resp = await client.get("/api/v1/me/notification-preferences")
    assert resp.status_code == 401

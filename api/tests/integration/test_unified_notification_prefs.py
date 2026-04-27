# ABOUTME: Phase 4 Sprint 5 — admin gets one merged view of comms prefs + channel.
# ABOUTME: Architectural Debt #5 — unified read collapses two tables into one shape.
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import Customer, NotificationPreference, Role, User

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
                "first_name": "U",
                "last_name": "P",
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
async def test_returns_defaults_for_user_with_no_prefs_or_customer(
    client: AsyncClient, db_session: AsyncSession
):
    admin = await _user_with_role(client, db_session, "unp_admin1@example.com", "admin")
    rep = await _user_with_role(client, db_session, "unp_rep1@example.com", "sales")
    resp = await client.get(
        f"/api/v1/admin/users/{rep['user_id']}/notification-summary",
        headers=_auth(admin["access_token"]),
    )
    assert resp.status_code == 200, resp.json()
    body = resp.json()
    assert body["channel"] == "email"  # default
    assert body["phone_number"] is None
    assert body["intake_confirmations"] is None  # no Customer profile
    assert body["status_updates"] is None
    assert body["role_slug"] == "sales"


@pytest.mark.asyncio
async def test_returns_channel_from_notification_preferences(
    client: AsyncClient, db_session: AsyncSession
):
    admin = await _user_with_role(client, db_session, "unp_admin2@example.com", "admin")
    rep = await _user_with_role(client, db_session, "unp_rep2@example.com", "sales")
    db_session.add(
        NotificationPreference(
            user_id=uuid.UUID(rep["user_id"]),
            channel="sms",
            phone_number="+15555550100",
        )
    )
    await db_session.flush()

    resp = await client.get(
        f"/api/v1/admin/users/{rep['user_id']}/notification-summary",
        headers=_auth(admin["access_token"]),
    )
    body = resp.json()
    assert body["channel"] == "sms"
    assert body["phone_number"] == "+15555550100"


@pytest.mark.asyncio
async def test_returns_customer_comms_prefs_for_customer(
    client: AsyncClient, db_session: AsyncSession
):
    admin = await _user_with_role(client, db_session, "unp_admin3@example.com", "admin")
    cust = await _user_with_role(client, db_session, "unp_cust3@example.com", "customer")
    db_session.add(
        Customer(
            user_id=uuid.UUID(cust["user_id"]),
            submitter_name="Sue",
            communication_prefs={
                "intake_confirmations": True,
                "status_updates": False,
                "marketing": True,
                "sms_opt_in": True,
            },
        )
    )
    await db_session.flush()

    resp = await client.get(
        f"/api/v1/admin/users/{cust['user_id']}/notification-summary",
        headers=_auth(admin["access_token"]),
    )
    body = resp.json()
    assert body["intake_confirmations"] is True
    assert body["status_updates"] is False
    assert body["marketing"] is True
    assert body["sms_opt_in"] is True


@pytest.mark.asyncio
async def test_blocked_for_non_admin(client: AsyncClient, db_session: AsyncSession):
    admin = await _user_with_role(client, db_session, "unp_admin4@example.com", "admin")
    sales = await _user_with_role(client, db_session, "unp_sales@example.com", "sales")
    resp = await client.get(
        f"/api/v1/admin/users/{admin['user_id']}/notification-summary",
        headers=_auth(sales["access_token"]),
    )
    assert resp.status_code == 403

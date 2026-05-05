# ABOUTME: Phase 8 Sprint 1 — POST /analytics/event.
# ABOUTME: Verifies customer events are recorded and staff events are silently dropped.
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import AnalyticsEvent, Role, User

_VALID_PASSWORD = "TestPassword1!"


async def _make_user(client: AsyncClient, db: AsyncSession, email: str, role_slug: str) -> str:
    with patch("services.email_service.send_email", new_callable=AsyncMock):
        await client.post(
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


_EVENT_PAYLOAD = {
    "event_type": "page_view",
    "page": "/portal/submit",
    "session_id": "sess-abc123",
}


@pytest.mark.asyncio
async def test_analytics_event_recorded_for_anonymous(
    client: AsyncClient, db_session: AsyncSession
):
    await db_session.commit()
    r = await client.post("/api/v1/analytics/event", json=_EVENT_PAYLOAD)
    assert r.status_code == 200
    assert r.json()["recorded"] is True

    await db_session.rollback()
    events = (
        (
            await db_session.execute(
                select(AnalyticsEvent).where(
                    (AnalyticsEvent.event_type == "page_view")
                    & (AnalyticsEvent.page == "/portal/submit")
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(events) >= 1


@pytest.mark.asyncio
async def test_analytics_event_recorded_for_customer(client: AsyncClient, db_session: AsyncSession):
    tok = await _make_user(client, db_session, "customer_analytics@example.com", "customer")
    await db_session.commit()

    r = await client.post(
        "/api/v1/analytics/event",
        json=_EVENT_PAYLOAD,
        headers={"Authorization": f"Bearer {tok}"},
    )
    assert r.status_code == 200
    assert r.json()["recorded"] is True


@pytest.mark.asyncio
async def test_analytics_event_dropped_for_sales_rep(client: AsyncClient, db_session: AsyncSession):
    tok = await _make_user(client, db_session, "sales_analytics@example.com", "sales")
    await db_session.commit()

    r = await client.post(
        "/api/v1/analytics/event",
        json={"event_type": "page_view", "page": "/sales/dashboard"},
        headers={"Authorization": f"Bearer {tok}"},
    )
    assert r.status_code == 200
    assert r.json()["recorded"] is False


@pytest.mark.asyncio
async def test_analytics_event_dropped_for_admin(client: AsyncClient, db_session: AsyncSession):
    tok = await _make_user(client, db_session, "admin_analytics@example.com", "admin")
    await db_session.commit()

    r = await client.post(
        "/api/v1/analytics/event",
        json={"event_type": "page_view", "page": "/admin/reports"},
        headers={"Authorization": f"Bearer {tok}"},
    )
    assert r.status_code == 200
    assert r.json()["recorded"] is False


@pytest.mark.asyncio
async def test_analytics_event_rejects_pii_in_metadata(
    client: AsyncClient, db_session: AsyncSession
):
    await db_session.commit()
    r = await client.post(
        "/api/v1/analytics/event",
        json={
            **_EVENT_PAYLOAD,
            "metadata": {"user_email": "leaking@example.com"},
        },
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_analytics_event_no_auth_required(client: AsyncClient, db_session: AsyncSession):
    await db_session.commit()
    r = await client.post("/api/v1/analytics/event", json=_EVENT_PAYLOAD)
    assert r.status_code == 200

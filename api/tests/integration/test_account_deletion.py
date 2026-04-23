# ABOUTME: Phase 2 Sprint 4 tests for account deletion request + cancel + PII scrub finalize.
# ABOUTME: Exercises grace-window semantics and the pending_deletion auth path.
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import Customer, NotificationJob, User, UserSession
from services import account_deletion_service

_VALID_PASSWORD = "TestPassword1!"


def _register_payload(email: str) -> dict:
    return {
        "email": email,
        "password": _VALID_PASSWORD,
        "first_name": "Delete",
        "last_name": "Customer",
        "tos_version": "1",
        "privacy_version": "1",
    }


async def _login_customer(client: AsyncClient, db: AsyncSession, email: str) -> tuple[str, User]:
    with patch("services.email_service.send_email", new_callable=AsyncMock):
        await client.post("/api/v1/auth/register", json=_register_payload(email))
    result = await db.execute(select(User).where(User.email == email.lower()))
    user = result.scalar_one()
    user.status = "active"
    await db.flush()
    with patch("services.email_service.send_email", new_callable=AsyncMock):
        login = await client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": _VALID_PASSWORD},
        )
    return login.json()["access_token"], user


# ---------------------------------------------------------------------------
# Request deletion
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_sets_grace_and_enqueues_email(client: AsyncClient, db_session: AsyncSession):
    token, user = await _login_customer(client, db_session, "delete_happy@example.com")

    resp = await client.post(
        "/api/v1/me/account/delete",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.json()
    body = resp.json()
    assert body["status"] == "pending_deletion"
    assert body["deletion_grace_until"] is not None

    await db_session.refresh(user)
    assert user.status == "pending_deletion"
    assert user.deletion_grace_until is not None
    # Grace is close to 30 days.
    delta = user.deletion_grace_until - datetime.now(UTC)
    assert timedelta(days=29) < delta <= timedelta(days=30)

    jobs = await db_session.execute(
        select(NotificationJob).where(NotificationJob.template == "account_deletion_requested")
    )
    assert len(list(jobs.scalars().all())) == 1


@pytest.mark.asyncio
async def test_delete_revokes_other_sessions(client: AsyncClient, db_session: AsyncSession):
    token, user = await _login_customer(client, db_session, "delete_sessions@example.com")
    # Sanity: there is at least one active session (from the login above).
    before = await db_session.execute(
        select(UserSession).where(UserSession.user_id == user.id, UserSession.revoked_at.is_(None))
    )
    assert len(list(before.scalars().all())) >= 1

    await client.post(
        "/api/v1/me/account/delete",
        headers={"Authorization": f"Bearer {token}"},
    )
    after = await db_session.execute(
        select(UserSession).where(UserSession.user_id == user.id, UserSession.revoked_at.is_(None))
    )
    assert list(after.scalars().all()) == []


@pytest.mark.asyncio
async def test_delete_is_idempotent(client: AsyncClient, db_session: AsyncSession):
    """A second POST /delete during grace must not reset the clock."""
    token, user = await _login_customer(client, db_session, "delete_idem@example.com")
    first = await client.post(
        "/api/v1/me/account/delete",
        headers={"Authorization": f"Bearer {token}"},
    )
    first_until = first.json()["deletion_grace_until"]

    second = await client.post(
        "/api/v1/me/account/delete",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert second.status_code == 200
    assert second.json()["deletion_grace_until"] == first_until


# ---------------------------------------------------------------------------
# Cancel
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cancel_restores_active_status(client: AsyncClient, db_session: AsyncSession):
    token, user = await _login_customer(client, db_session, "delete_cancel@example.com")
    await client.post(
        "/api/v1/me/account/delete",
        headers={"Authorization": f"Bearer {token}"},
    )

    resp = await client.post(
        "/api/v1/me/account/delete/cancel",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "active"
    assert body["deletion_grace_until"] is None

    await db_session.refresh(user)
    assert user.status == "active"
    assert user.deletion_grace_until is None


@pytest.mark.asyncio
async def test_cancel_without_pending_deletion_is_409(
    client: AsyncClient, db_session: AsyncSession
):
    token, _ = await _login_customer(client, db_session, "delete_cancel_bad@example.com")
    resp = await client.post(
        "/api/v1/me/account/delete/cancel",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 409


# ---------------------------------------------------------------------------
# Finalize (PII scrub)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_finalize_pseudonymizes_user_and_customer(
    client: AsyncClient, db_session: AsyncSession
):
    token, user = await _login_customer(client, db_session, "delete_finalize@example.com")
    # Fill in a customer profile so the scrub has something to clear.
    await client.patch(
        "/api/v1/me/profile",
        json={"business_name": "Acme LLC", "cell_phone": "555-555-5555"},
        headers={"Authorization": f"Bearer {token}"},
    )

    await account_deletion_service.finalize_deletion_for_user(db_session, user)

    await db_session.refresh(user)
    assert user.status == "deleted"
    assert user.email.startswith("deleted-")
    assert user.email.endswith("@deleted.invalid")
    assert user.first_name == "[deleted]"
    assert user.password_hash is None

    cust = await db_session.execute(select(Customer).where(Customer.user_id == user.id))
    customer = cust.scalar_one()
    assert customer.business_name is None
    assert customer.cell_phone is None
    assert customer.submitter_name == "[deleted]"
    assert customer.deleted_at is not None


@pytest.mark.asyncio
async def test_finalize_via_fn_delete_expired_accounts(
    client: AsyncClient, db_session: AsyncSession
):
    """The hourly sweeper runs fn_delete_expired_accounts(); we simulate it
    by rewinding the grace timestamp into the past, then calling the fn."""
    token, user = await _login_customer(client, db_session, "delete_expired@example.com")
    await client.post(
        "/api/v1/me/account/delete",
        headers={"Authorization": f"Bearer {token}"},
    )
    # Force the grace window into the past.
    await db_session.execute(
        text("UPDATE users SET deletion_grace_until = NOW() - interval '1 hour' WHERE id = :id"),
        {"id": user.id},
    )
    await db_session.flush()

    result = await db_session.execute(text("SELECT fn_delete_expired_accounts()"))
    scrubbed = result.scalar_one()
    assert scrubbed == 1

    await db_session.refresh(user)
    assert user.status == "deleted"


@pytest.mark.asyncio
async def test_deleted_user_cannot_authenticate(client: AsyncClient, db_session: AsyncSession):
    """Once a user is scrubbed to status='deleted', their old token must 401."""
    token, user = await _login_customer(client, db_session, "delete_authblock@example.com")
    await account_deletion_service.finalize_deletion_for_user(db_session, user)

    resp = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401

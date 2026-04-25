# ABOUTME: Phase 2 Sprint 3 tests for customer-initiated change requests.
# ABOUTME: Verifies persistence, sales-rep notification enqueue, ops-fallback, isolation.
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import ChangeRequest, NotificationJob, Role, User

_VALID_PASSWORD = "TestPassword1!"


def _register_payload(email: str) -> dict:
    return {
        "email": email,
        "password": _VALID_PASSWORD,
        "first_name": "Change",
        "last_name": "Customer",
        "tos_version": "1",
        "privacy_version": "1",
    }


async def _login_customer(client: AsyncClient, db: AsyncSession, email: str) -> str:
    with patch("services.email_service.send_email", new_callable=AsyncMock):
        reg = await client.post("/api/v1/auth/register", json=_register_payload(email))
    assert reg.status_code == 201
    result = await db.execute(select(User).where(User.email == email.lower()))
    user = result.scalar_one_or_none()
    assert user is not None
    user.status = "active"
    await db.flush()
    with patch("services.email_service.send_email", new_callable=AsyncMock):
        login = await client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": _VALID_PASSWORD},
        )
    return login.json()["access_token"]


async def _create_record(client: AsyncClient, token: str) -> str:
    resp = await client.post(
        "/api/v1/me/equipment",
        json={"photos": []},
        headers={"Authorization": f"Bearer {token}"},
    )
    return resp.json()["id"]


async def _make_sales_user(db: AsyncSession, email: str) -> User:
    role_row = await db.execute(select(Role).where(Role.slug == "sales"))
    sales_role = role_row.scalar_one()
    user = User(
        email=email,
        password_hash="x",
        first_name="Sales",
        last_name="Rep",
        role_id=sales_role.id,
        status="active",
    )
    db.add(user)
    await db.flush()
    return user


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_change_request_persists_and_notifies_assigned_rep(
    client: AsyncClient, db_session: AsyncSession
):
    token = await _login_customer(client, db_session, "change_happy@example.com")
    record_id = await _create_record(client, token)
    rep = await _make_sales_user(db_session, "rep1@example.com")

    # Assign the rep at the DB level (no router for this in Phase 2).
    from database.models import EquipmentRecord

    rec_result = await db_session.execute(
        select(EquipmentRecord).where(EquipmentRecord.id == uuid.UUID(record_id))
    )
    rec = rec_result.scalar_one()
    rec.assigned_sales_rep_id = rep.id
    await db_session.flush()

    resp = await client.post(
        f"/api/v1/me/equipment/{record_id}/change-requests",
        json={
            "request_type": "update_location",
            "customer_notes": "Moved to yard 3 — <script>alert(1)</script>.",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201, resp.json()
    body = resp.json()
    assert body["status"] == "pending"
    assert body["request_type"] == "update_location"
    assert "<script" not in (body["customer_notes"] or "")

    jobs = await db_session.execute(
        select(NotificationJob).where(NotificationJob.template == "sales_change_request")
    )
    queued = list(jobs.scalars().all())
    assert len(queued) == 1
    assert queued[0].payload["to_email"] == "rep1@example.com"
    assert queued[0].user_id == rep.id


@pytest.mark.asyncio
async def test_change_request_falls_back_to_sales_ops_email(
    client: AsyncClient, db_session: AsyncSession
):
    """When no rep is assigned, use settings.sales_ops_email if set."""
    token = await _login_customer(client, db_session, "change_fallback@example.com")
    record_id = await _create_record(client, token)

    with patch("services.change_request_service.settings") as patched_settings:
        patched_settings.sales_ops_email = "ops@saltrun.net"
        resp = await client.post(
            f"/api/v1/me/equipment/{record_id}/change-requests",
            json={"request_type": "withdraw"},
            headers={"Authorization": f"Bearer {token}"},
        )
    assert resp.status_code == 201
    jobs = await db_session.execute(
        select(NotificationJob).where(NotificationJob.template == "sales_change_request")
    )
    queued = list(jobs.scalars().all())
    assert len(queued) == 1
    assert queued[0].payload["to_email"] == "ops@saltrun.net"


@pytest.mark.asyncio
async def test_change_request_no_rep_no_ops_email_is_silent(
    client: AsyncClient, db_session: AsyncSession
):
    """No rep assigned + no ops-mailbox config = create the row without
    enqueuing; a log line explains the silence."""
    token = await _login_customer(client, db_session, "change_silent@example.com")
    record_id = await _create_record(client, token)

    # sales_ops_email defaults to "" in test env; no patch needed.
    resp = await client.post(
        f"/api/v1/me/equipment/{record_id}/change-requests",
        json={"request_type": "edit_details"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201
    jobs = await db_session.execute(
        select(NotificationJob).where(NotificationJob.template == "sales_change_request")
    )
    assert list(jobs.scalars().all()) == []

    # The row itself must still exist — we don't skip persistence.
    rows = await db_session.execute(select(ChangeRequest))
    assert len(list(rows.scalars().all())) == 1


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_change_request_rejects_unknown_type(client: AsyncClient, db_session: AsyncSession):
    token = await _login_customer(client, db_session, "change_bad_type@example.com")
    record_id = await _create_record(client, token)
    resp = await client.post(
        f"/api/v1/me/equipment/{record_id}/change-requests",
        json={"request_type": "reassign_rep"},  # not in allowlist
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_change_request_cross_customer_is_404(client: AsyncClient, db_session: AsyncSession):
    alice = await _login_customer(client, db_session, "change_alice@example.com")
    alice_record = await _create_record(client, alice)
    bob = await _login_customer(client, db_session, "change_bob@example.com")

    resp = await client.post(
        f"/api/v1/me/equipment/{alice_record}/change-requests",
        json={"request_type": "withdraw"},
        headers={"Authorization": f"Bearer {bob}"},
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# List
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_change_request_list_returns_only_records_entries(
    client: AsyncClient, db_session: AsyncSession
):
    token = await _login_customer(client, db_session, "change_list@example.com")
    record_a = await _create_record(client, token)
    record_b = await _create_record(client, token)

    await client.post(
        f"/api/v1/me/equipment/{record_a}/change-requests",
        json={"request_type": "edit_details"},
        headers={"Authorization": f"Bearer {token}"},
    )
    await client.post(
        f"/api/v1/me/equipment/{record_b}/change-requests",
        json={"request_type": "update_photos"},
        headers={"Authorization": f"Bearer {token}"},
    )

    listed = await client.get(
        f"/api/v1/me/equipment/{record_a}/change-requests",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert listed.status_code == 200
    items = listed.json()
    assert len(items) == 1
    assert items[0]["request_type"] == "edit_details"


# ---------------------------------------------------------------------------
# Duplicate-pending guard (Phase 3 Sprint 1 — Phase 2 carry-over)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_second_pending_request_on_same_record_returns_409(
    client: AsyncClient, db_session: AsyncSession
):
    """A customer cannot open a second pending change request on the same
    record — the partial unique index enforces one-at-a-time at the DB."""
    token = await _login_customer(client, db_session, "change_dup1@example.com")
    record_id = await _create_record(client, token)

    first = await client.post(
        f"/api/v1/me/equipment/{record_id}/change-requests",
        json={"request_type": "update_location"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert first.status_code == 201

    second = await client.post(
        f"/api/v1/me/equipment/{record_id}/change-requests",
        json={"request_type": "edit_details"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert second.status_code == 409
    assert "already pending" in second.json()["detail"].lower()


@pytest.mark.asyncio
async def test_new_request_allowed_after_prior_is_resolved(
    client: AsyncClient, db_session: AsyncSession
):
    """Once a request flips out of 'pending' (resolved/rejected), the next
    one can land. Partial index only binds pending rows."""
    token = await _login_customer(client, db_session, "change_dup2@example.com")
    record_id = await _create_record(client, token)

    first = await client.post(
        f"/api/v1/me/equipment/{record_id}/change-requests",
        json={"request_type": "update_location"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert first.status_code == 201

    # Simulate sales-rep resolution (Sprint 2 ships the HTTP endpoint for this;
    # here we flip the row directly).
    row = (
        await db_session.execute(
            select(ChangeRequest).where(ChangeRequest.equipment_record_id == uuid.UUID(record_id))
        )
    ).scalar_one()
    row.status = "resolved"
    await db_session.flush()

    second = await client.post(
        f"/api/v1/me/equipment/{record_id}/change-requests",
        json={"request_type": "edit_details"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert second.status_code == 201

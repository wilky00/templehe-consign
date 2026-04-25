# ABOUTME: Phase 3 Sprint 1 — record-lock endpoints (acquire/heartbeat/release/override).
# ABOUTME: Exercises the Postgres-backed POC impl; swap to Redis must keep these tests green.
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import AuditLog, RecordLock, Role, User

_VALID_PASSWORD = "TestPassword1!"


async def _active_user_with_role(
    client: AsyncClient,
    db: AsyncSession,
    email: str,
    role_slug: str,
) -> dict:
    """Register, activate, set role, log in. Returns {access_token, user_id, ...}."""
    with patch("services.email_service.send_email", new_callable=AsyncMock):
        reg = await client.post(
            "/api/v1/auth/register",
            json={
                "email": email,
                "password": _VALID_PASSWORD,
                "first_name": "Lock",
                "last_name": "Tester",
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
    assert login.status_code == 200
    body = login.json()
    body["user_id"] = str(user.id)
    return body


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Acquire
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_acquire_lock_returns_lock_info_and_audit_event(
    client: AsyncClient, db_session: AsyncSession
):
    cust = await _active_user_with_role(client, db_session, "lock_a@example.com", "customer")
    record_id = uuid.uuid4()

    resp = await client.post(
        "/api/v1/record-locks",
        json={"record_id": str(record_id), "record_type": "equipment_record"},
        headers=_auth(cust["access_token"]),
    )
    assert resp.status_code == 200, resp.json()
    body = resp.json()
    assert body["record_id"] == str(record_id)
    assert body["locked_by"] == cust["user_id"]
    assert body["expires_at"] > body["locked_at"]

    # Audit event written
    events = (
        await db_session.execute(
            select(AuditLog).where(AuditLog.event_type == "record_lock.acquired")
        )
    ).scalars().all()
    assert any(e.target_id == record_id for e in events)


@pytest.mark.asyncio
async def test_acquire_conflict_returns_409_with_lock_info(
    client: AsyncClient, db_session: AsyncSession
):
    first = await _active_user_with_role(client, db_session, "lock_b1@example.com", "customer")
    second = await _active_user_with_role(client, db_session, "lock_b2@example.com", "customer")
    record_id = uuid.uuid4()

    r1 = await client.post(
        "/api/v1/record-locks",
        json={"record_id": str(record_id)},
        headers=_auth(first["access_token"]),
    )
    assert r1.status_code == 200

    r2 = await client.post(
        "/api/v1/record-locks",
        json={"record_id": str(record_id)},
        headers=_auth(second["access_token"]),
    )
    assert r2.status_code == 409
    body = r2.json()
    assert body["locked_by"] == first["user_id"]
    assert "detail" in body


@pytest.mark.asyncio
async def test_acquire_same_user_refreshes_expiry(
    client: AsyncClient, db_session: AsyncSession
):
    cust = await _active_user_with_role(client, db_session, "lock_c@example.com", "customer")
    record_id = uuid.uuid4()

    first = await client.post(
        "/api/v1/record-locks",
        json={"record_id": str(record_id)},
        headers=_auth(cust["access_token"]),
    )
    assert first.status_code == 200
    first_expiry = first.json()["expires_at"]

    # Rewind the row to simulate time passing without relying on sleep.
    await db_session.execute(
        update(RecordLock)
        .where(RecordLock.record_id == record_id)
        .values(expires_at=datetime.now(UTC) + timedelta(minutes=5))
    )
    await db_session.flush()

    second = await client.post(
        "/api/v1/record-locks",
        json={"record_id": str(record_id)},
        headers=_auth(cust["access_token"]),
    )
    assert second.status_code == 200
    second_expiry = second.json()["expires_at"]
    assert second_expiry > first_expiry


@pytest.mark.asyncio
async def test_acquire_replaces_expired_lock_from_different_user(
    client: AsyncClient, db_session: AsyncSession
):
    ghost = await _active_user_with_role(client, db_session, "lock_d1@example.com", "customer")
    current = await _active_user_with_role(client, db_session, "lock_d2@example.com", "customer")
    record_id = uuid.uuid4()

    # Insert a stale lock held by a different user.
    db_session.add(
        RecordLock(
            record_id=record_id,
            record_type="equipment_record",
            locked_by=uuid.UUID(ghost["user_id"]),
            expires_at=datetime.now(UTC) - timedelta(minutes=1),
        )
    )
    await db_session.flush()

    resp = await client.post(
        "/api/v1/record-locks",
        json={"record_id": str(record_id)},
        headers=_auth(current["access_token"]),
    )
    assert resp.status_code == 200
    assert resp.json()["locked_by"] == current["user_id"]


# ---------------------------------------------------------------------------
# Heartbeat
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_heartbeat_refreshes_expiry_for_owner(
    client: AsyncClient, db_session: AsyncSession
):
    cust = await _active_user_with_role(client, db_session, "lock_e@example.com", "customer")
    record_id = uuid.uuid4()

    acquired = await client.post(
        "/api/v1/record-locks",
        json={"record_id": str(record_id)},
        headers=_auth(cust["access_token"]),
    )
    assert acquired.status_code == 200
    first_expiry = acquired.json()["expires_at"]

    # Rewind expiry to force a visible delta on heartbeat.
    await db_session.execute(
        update(RecordLock)
        .where(RecordLock.record_id == record_id)
        .values(expires_at=datetime.now(UTC) + timedelta(minutes=2))
    )
    await db_session.flush()

    hb = await client.put(
        f"/api/v1/record-locks/{record_id}/heartbeat",
        headers=_auth(cust["access_token"]),
    )
    assert hb.status_code == 200
    assert hb.json()["expires_at"] > first_expiry


@pytest.mark.asyncio
async def test_heartbeat_without_lock_returns_404(
    client: AsyncClient, db_session: AsyncSession
):
    cust = await _active_user_with_role(client, db_session, "lock_f@example.com", "customer")
    resp = await client.put(
        f"/api/v1/record-locks/{uuid.uuid4()}/heartbeat",
        headers=_auth(cust["access_token"]),
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_heartbeat_by_non_owner_returns_404(
    client: AsyncClient, db_session: AsyncSession
):
    owner = await _active_user_with_role(client, db_session, "lock_g1@example.com", "customer")
    stranger = await _active_user_with_role(client, db_session, "lock_g2@example.com", "customer")
    record_id = uuid.uuid4()

    r = await client.post(
        "/api/v1/record-locks",
        json={"record_id": str(record_id)},
        headers=_auth(owner["access_token"]),
    )
    assert r.status_code == 200

    hb = await client.put(
        f"/api/v1/record-locks/{record_id}/heartbeat",
        headers=_auth(stranger["access_token"]),
    )
    assert hb.status_code == 404


# ---------------------------------------------------------------------------
# Release
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_release_by_owner_deletes_row(
    client: AsyncClient, db_session: AsyncSession
):
    cust = await _active_user_with_role(client, db_session, "lock_h@example.com", "customer")
    record_id = uuid.uuid4()

    await client.post(
        "/api/v1/record-locks",
        json={"record_id": str(record_id)},
        headers=_auth(cust["access_token"]),
    )

    resp = await client.delete(
        f"/api/v1/record-locks/{record_id}",
        headers=_auth(cust["access_token"]),
    )
    assert resp.status_code == 204

    remaining = (
        await db_session.execute(
            select(RecordLock).where(RecordLock.record_id == record_id)
        )
    ).scalar_one_or_none()
    assert remaining is None


@pytest.mark.asyncio
async def test_release_is_idempotent_on_missing_lock(
    client: AsyncClient, db_session: AsyncSession
):
    cust = await _active_user_with_role(client, db_session, "lock_i@example.com", "customer")
    resp = await client.delete(
        f"/api/v1/record-locks/{uuid.uuid4()}",
        headers=_auth(cust["access_token"]),
    )
    # No lock → no-op. Client fires-and-forgets on page unload.
    assert resp.status_code == 204


# ---------------------------------------------------------------------------
# Override
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_manager_override_removes_lock_and_audits(
    client: AsyncClient, db_session: AsyncSession
):
    owner = await _active_user_with_role(client, db_session, "lock_j1@example.com", "customer")
    manager = await _active_user_with_role(client, db_session, "lock_j2@example.com", "sales_manager")
    record_id = uuid.uuid4()

    await client.post(
        "/api/v1/record-locks",
        json={"record_id": str(record_id)},
        headers=_auth(owner["access_token"]),
    )

    resp = await client.delete(
        f"/api/v1/record-locks/{record_id}/override",
        headers=_auth(manager["access_token"]),
    )
    assert resp.status_code == 204

    remaining = (
        await db_session.execute(
            select(RecordLock).where(RecordLock.record_id == record_id)
        )
    ).scalar_one_or_none()
    assert remaining is None

    override_events = (
        await db_session.execute(
            select(AuditLog).where(AuditLog.event_type == "record_lock.overridden")
        )
    ).scalars().all()
    match = next((e for e in override_events if e.target_id == record_id), None)
    assert match is not None
    assert match.actor_id == uuid.UUID(manager["user_id"])
    assert match.before_state["locked_by"] == owner["user_id"]


@pytest.mark.asyncio
async def test_customer_cannot_override_lock(
    client: AsyncClient, db_session: AsyncSession
):
    owner = await _active_user_with_role(client, db_session, "lock_k1@example.com", "customer")
    other = await _active_user_with_role(client, db_session, "lock_k2@example.com", "customer")
    record_id = uuid.uuid4()

    await client.post(
        "/api/v1/record-locks",
        json={"record_id": str(record_id)},
        headers=_auth(owner["access_token"]),
    )

    resp = await client.delete(
        f"/api/v1/record-locks/{record_id}/override",
        headers=_auth(other["access_token"]),
    )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Cross-record isolation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_locks_on_different_records_are_independent(
    client: AsyncClient, db_session: AsyncSession
):
    a = await _active_user_with_role(client, db_session, "lock_l1@example.com", "customer")
    b = await _active_user_with_role(client, db_session, "lock_l2@example.com", "customer")
    record_a = uuid.uuid4()
    record_b = uuid.uuid4()

    r1 = await client.post(
        "/api/v1/record-locks",
        json={"record_id": str(record_a)},
        headers=_auth(a["access_token"]),
    )
    r2 = await client.post(
        "/api/v1/record-locks",
        json={"record_id": str(record_b)},
        headers=_auth(b["access_token"]),
    )
    assert r1.status_code == 200
    assert r2.status_code == 200
    assert r1.json()["locked_by"] == a["user_id"]
    assert r2.json()["locked_by"] == b["user_id"]


@pytest.mark.asyncio
async def test_acquire_integrityerror_fallback_treats_same_user_as_heartbeat(
    db_session: AsyncSession,
):
    """If two acquire() calls by the same user race past the initial SELECT,
    one wins the INSERT and the other hits the unique-constraint
    IntegrityError fallback. The fallback must treat the same-user case as a
    heartbeat — not raise 409 against the user against themselves. Repros
    the React-StrictMode-double-mount and two-tab-same-user cases.

    Mocked at the service layer because the deterministic race is hard to
    stage with the conftest's nested-transaction db_session — the source of
    truth for end-to-end behavior is ``web/e2e/phase3_calendar.spec.ts``,
    which naturally fires the race via React StrictMode.
    """
    from datetime import datetime as _dt
    from types import SimpleNamespace

    from services import record_lock_service

    user_id = uuid.uuid4()
    record_id = uuid.uuid4()
    existing_locked_at = datetime.now(UTC)
    existing_expires_at = datetime.now(UTC) + timedelta(seconds=1)

    # _find returns a RecordLock ORM row in production; SimpleNamespace
    # gives us the same attribute surface.
    existing_row = SimpleNamespace(
        record_id=record_id,
        record_type="equipment_record",
        locked_by=user_id,  # SAME user — the key condition under test
        locked_at=existing_locked_at,
        expires_at=existing_expires_at,
    )

    # _find returns None first (so acquire() proceeds to INSERT and trips
    # the unique constraint), then returns the existing same-user row on
    # the post-rollback re-check.
    call_count = {"n": 0}

    async def fake_find(*_args, **_kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return None
        return existing_row

    # Stub the savepoint context manager and flush() so the first attempt
    # raises IntegrityError; subsequent _find returns the existing same-
    # user row.
    flush_count = {"n": 0}
    savepoint_rolled_back = {"n": 0}

    async def fake_flush(_self=None):
        flush_count["n"] += 1
        if flush_count["n"] == 1:
            from sqlalchemy.exc import IntegrityError

            raise IntegrityError("INSERT", {}, Exception("unique violation"))

    class FakeSavepoint:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            if exc_type is not None:
                # Mirror real begin_nested(): rolls back to savepoint,
                # then re-raises so the outer try/except can handle it.
                savepoint_rolled_back["n"] += 1
            return False  # don't suppress

    fake_session = type(
        "FakeSession",
        (),
        {
            "add": lambda self, _row: None,
            "flush": fake_flush,
            "begin_nested": lambda self: FakeSavepoint(),
        },
    )()

    with patch.object(record_lock_service, "_find", side_effect=fake_find):
        info = await record_lock_service.acquire(
            fake_session,
            record_id=record_id,
            record_type="equipment_record",
            user_id=user_id,
        )

    assert info.locked_by == user_id
    assert info.expires_at == existing_expires_at
    assert savepoint_rolled_back["n"] == 1
    assert isinstance(info.locked_at, _dt)

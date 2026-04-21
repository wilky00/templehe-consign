# ABOUTME: Integration tests for fn_sweep_retention and fn_ensure_audit_partitions.
# ABOUTME: Verifies the SQL functions land the correct rows and are idempotent.
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text

from database.models import RateLimitCounter, UserSession, WebhookEventSeen


@pytest.mark.asyncio
async def test_sweep_retention_deletes_stale_rate_limit_counters(db_session):
    stale = RateLimitCounter(
        key="login_ip:1.2.3.4",
        window_start=datetime.now(UTC) - timedelta(hours=3),
        count=1,
    )
    fresh = RateLimitCounter(
        key="login_ip:5.6.7.8",
        window_start=datetime.now(UTC) - timedelta(minutes=5),
        count=1,
    )
    db_session.add(stale)
    db_session.add(fresh)
    await db_session.flush()

    result = await db_session.execute(text("SELECT * FROM fn_sweep_retention()"))
    rows = {t: n for t, n in result.all()}
    assert rows["rate_limit_counters"] >= 1

    remaining_keys = {
        r[0] for r in (await db_session.execute(text("SELECT key FROM rate_limit_counters"))).all()
    }
    assert "login_ip:1.2.3.4" not in remaining_keys
    assert "login_ip:5.6.7.8" in remaining_keys


@pytest.mark.asyncio
async def test_sweep_retention_deletes_expired_webhook_events(db_session):
    expired = WebhookEventSeen(
        event_id="evt_expired",
        expires_at=datetime.now(UTC) - timedelta(hours=1),
    )
    active = WebhookEventSeen(
        event_id="evt_active",
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    db_session.add(expired)
    db_session.add(active)
    await db_session.flush()

    await db_session.execute(text("SELECT * FROM fn_sweep_retention()"))

    remaining_ids = {
        r[0]
        for r in (await db_session.execute(text("SELECT event_id FROM webhook_events_seen"))).all()
    }
    assert "evt_expired" not in remaining_ids
    assert "evt_active" in remaining_ids


@pytest.mark.asyncio
async def test_sweep_retention_deletes_long_revoked_sessions(db_session):
    from sqlalchemy import select

    from database.models import Role, User

    role = (await db_session.execute(select(Role).where(Role.slug == "customer"))).scalar_one()
    user = User(
        email="retention_user@example.com",
        password_hash="irrelevant",
        first_name="R",
        last_name="User",
        role_id=role.id,
        status="active",
    )
    db_session.add(user)
    await db_session.flush()

    expired_session = UserSession(
        user_id=user.id,
        token_hash="a" * 64,
        expires_at=datetime.now(UTC) - timedelta(days=1),
    )
    old_revoked = UserSession(
        user_id=user.id,
        token_hash="b" * 64,
        expires_at=datetime.now(UTC) + timedelta(days=30),
        revoked_at=datetime.now(UTC) - timedelta(days=8),
    )
    fresh_revoked = UserSession(
        user_id=user.id,
        token_hash="c" * 64,
        expires_at=datetime.now(UTC) + timedelta(days=30),
        revoked_at=datetime.now(UTC) - timedelta(hours=1),
    )
    active = UserSession(
        user_id=user.id,
        token_hash="d" * 64,
        expires_at=datetime.now(UTC) + timedelta(days=30),
    )
    for s in (expired_session, old_revoked, fresh_revoked, active):
        db_session.add(s)
    await db_session.flush()

    await db_session.execute(text("SELECT * FROM fn_sweep_retention()"))

    remaining_hashes = {
        r[0]
        for r in (
            await db_session.execute(
                text("SELECT token_hash FROM user_sessions WHERE user_id = :uid"),
                {"uid": user.id},
            )
        ).all()
    }
    assert "a" * 64 not in remaining_hashes  # expired
    assert "b" * 64 not in remaining_hashes  # long-revoked
    assert "c" * 64 in remaining_hashes  # recently revoked (keep 7d)
    assert "d" * 64 in remaining_hashes  # active


@pytest.mark.asyncio
async def test_ensure_audit_partitions_is_idempotent(db_session):
    # First call may or may not create partitions depending on what the
    # migration already seeded — but must not error.
    result = await db_session.execute(text("SELECT fn_ensure_audit_partitions()"))
    first_count = result.scalar_one()
    assert first_count >= 0

    # Second call should create zero — partitions already exist.
    result = await db_session.execute(text("SELECT fn_ensure_audit_partitions()"))
    second_count = result.scalar_one()
    assert second_count == 0

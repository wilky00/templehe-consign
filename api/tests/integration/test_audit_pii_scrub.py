# ABOUTME: Phase 2 Sprint 4 tests for fn_scrub_audit_pii() — PII scrubber on audit_logs.
# ABOUTME: Ensures old rows are nulled, young rows untouched, trigger bypass is scoped.
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import AuditLog


async def _insert_audit_row(
    db: AsyncSession,
    *,
    event_type: str,
    ip: str,
    ua: str,
    age_days: int,
) -> uuid.UUID:
    row_id = uuid.uuid4()
    await db.execute(
        text(
            "INSERT INTO audit_logs (id, event_type, ip_address, user_agent, created_at) "
            "VALUES (:id, :et, :ip, :ua, NOW() - make_interval(days => :days))"
        ),
        {"id": row_id, "et": event_type, "ip": ip, "ua": ua, "days": age_days},
    )
    return row_id


@pytest.mark.asyncio
async def test_scrubber_nulls_rows_older_than_retention(db_session: AsyncSession):
    old_id = await _insert_audit_row(
        db_session, event_type="user.login", ip="1.2.3.4", ua="OldBrowser", age_days=45
    )
    young_id = await _insert_audit_row(
        db_session, event_type="user.login", ip="5.6.7.8", ua="NewBrowser", age_days=5
    )
    await db_session.flush()

    result = await db_session.execute(text("SELECT fn_scrub_audit_pii(30)"))
    scrubbed = result.scalar_one()
    assert scrubbed == 1

    rows = await db_session.execute(select(AuditLog).where(AuditLog.id.in_([old_id, young_id])))
    by_id = {r.id: r for r in rows.scalars().all()}
    assert by_id[old_id].ip_address is None
    assert by_id[old_id].user_agent is None
    assert by_id[young_id].ip_address == "5.6.7.8"
    assert by_id[young_id].user_agent == "NewBrowser"


@pytest.mark.asyncio
async def test_scrubber_rejects_out_of_range_retention(db_session: AsyncSession):
    with pytest.raises(DBAPIError, match="between 30 and 120"):
        await db_session.execute(text("SELECT fn_scrub_audit_pii(7)"))


@pytest.mark.asyncio
async def test_scrubber_leaves_event_skeleton_intact(db_session: AsyncSession):
    """Scrubbing only touches ip_address and user_agent — the rest stays."""
    row_id = await _insert_audit_row(
        db_session,
        event_type="user.login_failed",
        ip="9.9.9.9",
        ua="Scrubbed",
        age_days=60,
    )
    await db_session.flush()

    await db_session.execute(text("SELECT fn_scrub_audit_pii(30)"))
    fetched = await db_session.execute(select(AuditLog).where(AuditLog.id == row_id))
    row = fetched.scalar_one()
    assert row.event_type == "user.login_failed"
    assert row.ip_address is None


@pytest.mark.asyncio
async def test_audit_log_update_still_blocked_outside_scrubber(db_session: AsyncSession):
    """The trigger only yields when the PII-scrub GUC is set. A naïve UPDATE
    from application code must still be blocked — otherwise the append-only
    guarantee is silently gone.
    """
    row_id = await _insert_audit_row(
        db_session, event_type="user.login", ip="1.1.1.1", ua="x", age_days=0
    )
    await db_session.flush()

    with pytest.raises(DBAPIError, match="append-only"):
        await db_session.execute(
            text("UPDATE audit_logs SET ip_address = NULL WHERE id = :id"),
            {"id": row_id},
        )


@pytest.mark.asyncio
async def test_audit_log_delete_still_blocked(db_session: AsyncSession):
    """Deletion is never allowed — not even via the scrubber's GUC path."""
    row_id = await _insert_audit_row(
        db_session, event_type="user.login", ip="1.1.1.1", ua="x", age_days=0
    )
    await db_session.flush()

    with pytest.raises(DBAPIError, match="append-only"):
        await db_session.execute(text("DELETE FROM audit_logs WHERE id = :id"), {"id": row_id})

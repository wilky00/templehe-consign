# ABOUTME: Phase 2 Sprint 2 integration tests for NotificationService enqueue + process + retry.
# ABOUTME: Durable-queue contract that replaces BackgroundTasks for customer-facing flows.
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import NotificationJob
from services import notification_service


def _base_payload() -> dict:
    return {
        "to_email": "hello@example.com",
        "subject": "Test",
        "html_body": "<p>Hi</p>",
    }


# ---------------------------------------------------------------------------
# Enqueue
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_enqueue_writes_pending_row(db_session: AsyncSession):
    job = await notification_service.enqueue(
        db_session,
        idempotency_key="intake_confirmation:abc",
        user_id=None,
        channel="email",
        template="intake_confirmation",
        payload=_base_payload(),
    )
    await db_session.flush()
    assert job is not None
    assert job.status == "pending"
    assert job.attempts == 0
    assert job.channel == "email"


@pytest.mark.asyncio
async def test_enqueue_is_idempotent_on_key(db_session: AsyncSession):
    key = "intake_confirmation:dup"
    first = await notification_service.enqueue(
        db_session,
        idempotency_key=key,
        user_id=None,
        channel="email",
        template="intake_confirmation",
        payload=_base_payload(),
    )
    second = await notification_service.enqueue(
        db_session,
        idempotency_key=key,
        user_id=None,
        channel="email",
        template="intake_confirmation",
        payload=_base_payload(),
    )
    assert first is not None
    assert second is None  # ON CONFLICT DO NOTHING, no second row
    result = await db_session.execute(
        select(NotificationJob).where(NotificationJob.idempotency_key == key)
    )
    rows = list(result.scalars().all())
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_enqueue_rejects_unknown_channel(db_session: AsyncSession):
    with pytest.raises(ValueError, match="channel"):
        await notification_service.enqueue(
            db_session,
            idempotency_key="bad_channel",
            user_id=None,
            channel="fax",
            template="x",
            payload={},
        )


# ---------------------------------------------------------------------------
# Claim + process
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_claim_batch_marks_processing_and_skips_future(
    db_session: AsyncSession,
):
    future_sched = datetime.now(UTC) + timedelta(hours=1)
    await notification_service.enqueue(
        db_session,
        idempotency_key="claim:now",
        user_id=None,
        channel="email",
        template="intake_confirmation",
        payload=_base_payload(),
    )
    await notification_service.enqueue(
        db_session,
        idempotency_key="claim:future",
        user_id=None,
        channel="email",
        template="intake_confirmation",
        payload=_base_payload(),
        scheduled_for=future_sched,
    )
    await db_session.flush()

    claimed = await notification_service.claim_next_batch(db_session, limit=10)
    assert [j.idempotency_key for j in claimed] == ["claim:now"]

    # Future job is still pending; claimed one flipped to processing.
    state = await db_session.execute(
        select(NotificationJob.idempotency_key, NotificationJob.status).order_by(
            NotificationJob.idempotency_key
        )
    )
    by_key = {k: s for k, s in state.all()}
    assert by_key["claim:now"] == "processing"
    assert by_key["claim:future"] == "pending"


@pytest.mark.asyncio
async def test_process_email_job_marks_delivered(db_session: AsyncSession):
    job = await notification_service.enqueue(
        db_session,
        idempotency_key="proc:ok",
        user_id=None,
        channel="email",
        template="intake_confirmation",
        payload=_base_payload(),
    )
    await db_session.flush()
    assert job is not None

    with patch("services.email_service.send_email", new_callable=AsyncMock):
        status = await notification_service.process_job(db_session, job)
    assert status == "delivered"
    row = await db_session.execute(select(NotificationJob).where(NotificationJob.id == job.id))
    persisted = row.scalar_one()
    assert persisted.status == "delivered"
    assert persisted.attempts == 1
    assert persisted.processed_at is not None


@pytest.mark.asyncio
async def test_process_email_retries_on_exception(db_session: AsyncSession):
    job = await notification_service.enqueue(
        db_session,
        idempotency_key="proc:flaky",
        user_id=None,
        channel="email",
        template="intake_confirmation",
        payload=_base_payload(),
    )
    await db_session.flush()
    assert job is not None

    with patch(
        "services.email_service.send_email",
        new_callable=AsyncMock,
        side_effect=RuntimeError("boom"),
    ):
        status = await notification_service.process_job(db_session, job)
    assert status == "pending"  # re-scheduled for a later attempt
    row = await db_session.execute(select(NotificationJob).where(NotificationJob.id == job.id))
    persisted = row.scalar_one()
    assert persisted.status == "pending"
    assert persisted.attempts == 1
    assert persisted.scheduled_for > datetime.now(UTC)
    assert "RuntimeError" in (persisted.last_error or "")


@pytest.mark.asyncio
async def test_process_email_marks_failed_after_max_attempts(db_session: AsyncSession):
    job = await notification_service.enqueue(
        db_session,
        idempotency_key="proc:dead",
        user_id=None,
        channel="email",
        template="intake_confirmation",
        payload=_base_payload(),
    )
    await db_session.flush()
    assert job is not None

    # Bump attempts to one below max so the next failure tips it over.
    await db_session.execute(
        text("UPDATE notification_jobs SET attempts = max_attempts - 1 WHERE id = :id"),
        {"id": job.id},
    )
    await db_session.flush()
    # Identity-map cache holds the pre-UPDATE values; expire + refresh so the
    # local object matches what the DB actually has.
    await db_session.refresh(job)

    with patch(
        "services.email_service.send_email",
        new_callable=AsyncMock,
        side_effect=RuntimeError("again"),
    ):
        status = await notification_service.process_job(db_session, job)
    assert status == "failed"
    row = await db_session.execute(select(NotificationJob).where(NotificationJob.id == job.id))
    persisted = row.scalar_one()
    assert persisted.status == "failed"
    assert persisted.attempts == persisted.max_attempts
    assert persisted.processed_at is not None


# ---------------------------------------------------------------------------
# SMS gating
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sms_unconfigured_is_skipped(db_session: AsyncSession):
    job = await notification_service.enqueue(
        db_session,
        idempotency_key="sms:noconfig",
        user_id=None,
        channel="sms",
        template="intake_status",
        payload={"to_number": "+15555551212", "body": "Your unit was received."},
    )
    await db_session.flush()
    assert job is not None

    # settings.twilio_messaging_service_sid is "" in the test env — no patch needed.
    status = await notification_service.process_job(db_session, job)
    assert status == "skipped"
    row = await db_session.execute(select(NotificationJob).where(NotificationJob.id == job.id))
    persisted = row.scalar_one()
    assert persisted.status == "skipped"
    assert persisted.last_error == "sms_skipped_not_configured"


@pytest.mark.asyncio
async def test_sms_missing_payload_fields_is_failed(db_session: AsyncSession):
    job = await notification_service.enqueue(
        db_session,
        idempotency_key="sms:badpayload",
        user_id=None,
        channel="sms",
        template="intake_status",
        payload={"to_number": "+15555551212"},  # body missing
    )
    await db_session.flush()
    assert job is not None

    with patch.object(notification_service.settings, "twilio_messaging_service_sid", "MG-fake-sid"):
        status = await notification_service.process_job(db_session, job)
    assert status == "failed"
    row = await db_session.execute(select(NotificationJob).where(NotificationJob.id == job.id))
    persisted = row.scalar_one()
    assert persisted.status == "failed"
    assert "to_number/body" in (persisted.last_error or "")

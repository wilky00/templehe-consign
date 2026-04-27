# ABOUTME: Phase 4 Sprint 7 — Slack webhook dispatch via the notification_jobs queue.
# ABOUTME: Verifies the Phase 3-deferred Slack channel now actually delivers.
from __future__ import annotations

import uuid

import pytest
import respx
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import IntegrationCredential
from services import credentials_vault, notification_service, slack_dispatch_service


async def _save_slack_webhook(db: AsyncSession, url: str) -> None:
    db.add(
        IntegrationCredential(
            integration_name="slack",
            encrypted_value=credentials_vault.encrypt(url),
        )
    )
    await db.flush()


@pytest.mark.asyncio
@respx.mock
async def test_slack_dispatch_delivers_on_200_ok(db_session: AsyncSession):
    await _save_slack_webhook(db_session, "https://hooks.slack.com/services/T/B/X")
    respx.post("https://hooks.slack.com/services/T/B/X").respond(status_code=200, text="ok")

    job = await notification_service.enqueue(
        db_session,
        idempotency_key=f"slack-test-{uuid.uuid4()}",
        user_id=None,
        channel="slack",
        template="ad_hoc_slack",
        payload={"text": "hello slack"},
    )
    assert job is not None
    status = await notification_service.process_job(db_session, job)
    assert status == "delivered"


@pytest.mark.asyncio
@respx.mock
async def test_slack_5xx_marks_for_retry(db_session: AsyncSession):
    """5xx is transient — process_job catches the raised TransientSlackError
    and flips the row to 'pending' with a backoff schedule."""
    await _save_slack_webhook(db_session, "https://hooks.slack.com/services/T/B/X")
    respx.post("https://hooks.slack.com/services/T/B/X").respond(
        status_code=503, text="upstream-out"
    )

    job = await notification_service.enqueue(
        db_session,
        idempotency_key=f"slack-503-{uuid.uuid4()}",
        user_id=None,
        channel="slack",
        template="ad_hoc_slack",
        payload={"text": "hi"},
    )
    assert job is not None
    status = await notification_service.process_job(db_session, job)
    assert status == "pending"  # retry on backoff
    assert job.attempts == 1


@pytest.mark.asyncio
@respx.mock
async def test_slack_4xx_fails_permanently(db_session: AsyncSession):
    """4xx (other than 429) is a permanent dispatch failure — no retry."""
    await _save_slack_webhook(db_session, "https://hooks.slack.com/services/T/B/X")
    respx.post("https://hooks.slack.com/services/T/B/X").respond(
        status_code=404, text="invalid_token"
    )

    job = await notification_service.enqueue(
        db_session,
        idempotency_key=f"slack-404-{uuid.uuid4()}",
        user_id=None,
        channel="slack",
        template="ad_hoc_slack",
        payload={"text": "hi"},
    )
    assert job is not None
    status = await notification_service.process_job(db_session, job)
    assert status == "failed"
    assert "404" in (job.last_error or "")


@pytest.mark.asyncio
async def test_slack_skipped_when_no_credential(db_session: AsyncSession):
    """No credential saved → status='skipped'. The notification_jobs row
    won't retry on its own; admin needs to save creds + re-enqueue."""
    job = await notification_service.enqueue(
        db_session,
        idempotency_key=f"slack-skip-{uuid.uuid4()}",
        user_id=None,
        channel="slack",
        template="ad_hoc_slack",
        payload={"text": "hi"},
    )
    assert job is not None
    status = await notification_service.process_job(db_session, job)
    assert status == "skipped"
    assert job.last_error == "slack_skipped_not_configured"


@pytest.mark.asyncio
async def test_slack_payload_missing_text_fails(db_session: AsyncSession):
    job = await notification_service.enqueue(
        db_session,
        idempotency_key=f"slack-empty-{uuid.uuid4()}",
        user_id=None,
        channel="slack",
        template="ad_hoc_slack",
        payload={},  # no text
    )
    assert job is not None
    status = await notification_service.process_job(db_session, job)
    assert status == "failed"
    assert "missing text" in (job.last_error or "")


@pytest.mark.asyncio
@respx.mock
async def test_dispatch_service_raises_transient_on_429(db_session: AsyncSession):
    """Direct test of the underlying dispatch service — 429 should be
    classified as transient (Slack throttles via Retry-After)."""
    await _save_slack_webhook(db_session, "https://hooks.slack.com/services/T/B/X")
    respx.post("https://hooks.slack.com/services/T/B/X").respond(
        status_code=429, text="rate_limited"
    )
    with pytest.raises(slack_dispatch_service.TransientSlackError):
        await slack_dispatch_service.send(db=db_session, text_body="hello")

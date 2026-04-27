# ABOUTME: Durable notification queue — enqueues rows in notification_jobs; worker drains.
# ABOUTME: Replaces BackgroundTasks for Phase 2+ flows that need at-least-once delivery.
"""NotificationService — Phase 2 durable-dispatch contract (ADR-001 / ADR-012).

The API enqueues a row into ``notification_jobs``; a long-running
``scripts/notification_worker.py`` process (run as the
``temple-notifications`` Fly Machine in prod) drains pending rows using
``SELECT ... FOR UPDATE SKIP LOCKED`` and dispatches via
``email_service`` or Twilio.

Design notes:
- **At-least-once**, not exactly-once. Templates must tolerate duplicate
  delivery (idempotency lives in the receiver; sending two "your
  submission received" emails is annoying but not a safety issue).
- **Idempotency key** on the enqueue call collapses retries from the
  API side — e.g. a network-flaky intake submission that retries won't
  enqueue two "intake confirmation" rows.
- **SMS gated on settings.twilio_messaging_service_sid.** If unset, the
  worker marks the row as ``skipped`` with ``last_error='sms_skipped_not_configured'``
  and emits an audit event. Email fallback for customer-facing events
  is the caller's responsibility (pass an email template alongside).
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database.models import NotificationJob
from services import email_service

logger = structlog.get_logger(__name__)

# Exponential-ish backoff in seconds: 30s, 2min, 10min, 1hr, 6hr.
_BACKOFF_SECONDS = [30, 120, 600, 3600, 21600]


async def enqueue(
    db: AsyncSession,
    *,
    idempotency_key: str,
    user_id: uuid.UUID | None,
    channel: str,
    template: str,
    payload: dict,
    scheduled_for: datetime | None = None,
) -> NotificationJob | None:
    """Insert a pending job. Returns the row, or None if idempotency_key collided.

    Callers should treat a None return as "already enqueued" — not an error.

    When ``scheduled_for`` is omitted, the DB default (``NOW()``) fills it.
    That keeps the insert timestamp and the worker's ``clock_timestamp()``
    claim query on the same clock — Python-on-host vs Postgres-in-Docker
    can drift by hundreds of milliseconds, which otherwise races the worker.
    """
    if channel not in ("email", "sms", "slack"):
        raise ValueError(f"Unknown notification channel: {channel}")
    values: dict = {
        "idempotency_key": idempotency_key,
        "user_id": user_id,
        "channel": channel,
        "template": template,
        "payload": payload,
        "status": "pending",
    }
    if scheduled_for is not None:
        values["scheduled_for"] = scheduled_for
    stmt = (
        pg_insert(NotificationJob)
        .values(**values)
        .on_conflict_do_nothing(index_elements=["idempotency_key"])
        .returning(NotificationJob)
    )
    result = await db.execute(stmt)
    row = result.scalar_one_or_none()
    if row is None:
        logger.info("notification_enqueue_idempotent", key=idempotency_key)
    else:
        logger.info(
            "notification_enqueued",
            key=idempotency_key,
            channel=channel,
            template=template,
        )
    return row


async def claim_next_batch(db: AsyncSession, *, limit: int = 10) -> list[NotificationJob]:
    """Atomically claim up to ``limit`` pending jobs for processing.

    Uses ``SELECT ... FOR UPDATE SKIP LOCKED`` so multiple workers can run
    without stepping on each other. Claimed rows are flipped to 'processing'
    in the same transaction — the caller commits and then dispatches.
    """
    # FOR UPDATE SKIP LOCKED must be against a plain table (not a CTE), so
    # we issue the claim as two statements in one transaction. We compare
    # scheduled_for against clock_timestamp() rather than NOW() so jobs
    # enqueued inside the same transaction (common in tests, and harmless
    # in prod) become visible immediately.
    result = await db.execute(
        text("""
            SELECT id FROM notification_jobs
            WHERE status = 'pending' AND scheduled_for <= clock_timestamp()
            ORDER BY scheduled_for
            LIMIT :limit
            FOR UPDATE SKIP LOCKED
        """),
        {"limit": limit},
    )
    ids = [row[0] for row in result.fetchall()]
    if not ids:
        return []
    await db.execute(
        text(
            "UPDATE notification_jobs SET status = 'processing', updated_at = NOW() "
            "WHERE id = ANY(:ids)"
        ),
        {"ids": ids},
    )
    fetched = await db.execute(
        text("SELECT * FROM notification_jobs WHERE id = ANY(:ids)"),
        {"ids": ids},
    )
    rows = fetched.mappings().all()
    # Map rows back into ORM-ish objects via the model mapper.
    jobs: list[NotificationJob] = []
    for r in rows:
        payload = r["payload"]
        if isinstance(payload, str):
            payload = json.loads(payload)
        job = NotificationJob(
            id=r["id"],
            idempotency_key=r["idempotency_key"],
            user_id=r["user_id"],
            channel=r["channel"],
            template=r["template"],
            payload=payload,
            status=r["status"],
            attempts=r["attempts"],
            max_attempts=r["max_attempts"],
            scheduled_for=r["scheduled_for"],
            processed_at=r["processed_at"],
            last_error=r["last_error"],
        )
        jobs.append(job)
    return jobs


async def process_job(db: AsyncSession, job: NotificationJob) -> str:
    """Dispatch a single claimed job. Returns the new status.

    Callers commit the transaction after this returns — the DB row is
    updated inline.
    """
    try:
        if job.channel == "email":
            new_status = await _dispatch_email(job)
        elif job.channel == "sms":
            new_status = await _dispatch_sms(job)
        elif job.channel == "slack":
            new_status = await _dispatch_slack(db, job)
        else:
            new_status = "failed"
            job.last_error = f"unknown channel: {job.channel}"
    except Exception as exc:
        logger.exception(
            "notification_dispatch_failed",
            job_id=str(job.id),
            template=job.template,
        )
        new_status = "retry"
        job.last_error = f"{type(exc).__name__}: {exc}"[:1000]

    job.attempts += 1

    if new_status == "retry":
        if job.attempts >= job.max_attempts:
            job.status = "failed"
            job.processed_at = datetime.now(UTC)
        else:
            # Schedule next attempt with the next backoff bucket (or the last one).
            idx = min(job.attempts - 1, len(_BACKOFF_SECONDS) - 1)
            job.status = "pending"
            job.scheduled_for = datetime.now(UTC) + timedelta(seconds=_BACKOFF_SECONDS[idx])
    else:
        job.status = new_status
        job.processed_at = datetime.now(UTC)

    await db.execute(
        text("""
            UPDATE notification_jobs
            SET status = :status,
                attempts = :attempts,
                processed_at = :processed_at,
                last_error = :last_error,
                scheduled_for = :scheduled_for,
                updated_at = NOW()
            WHERE id = :id
        """),
        {
            "id": job.id,
            "status": job.status,
            "attempts": job.attempts,
            "processed_at": job.processed_at,
            "last_error": job.last_error,
            "scheduled_for": job.scheduled_for,
        },
    )
    return job.status


async def _dispatch_email(job: NotificationJob) -> str:
    payload = job.payload or {}
    to_email = payload.get("to_email")
    subject = payload.get("subject")
    html_body = payload.get("html_body")
    if not (to_email and subject and html_body):
        job.last_error = "email payload missing to_email/subject/html_body"
        return "failed"
    # email_service.send_email swallows its own exceptions and logs; if we
    # want true failure signal for retry, we'd need a non-swallowing variant.
    # For Phase 2 this is good enough — any catastrophic failure still
    # raises from to_thread, which our try/except catches.
    await email_service.send_email(to_email=to_email, subject=subject, html_body=html_body)
    return "delivered"


async def _dispatch_sms(job: NotificationJob) -> str:
    if not settings.twilio_messaging_service_sid:
        logger.info(
            "sms_skipped_not_configured",
            job_id=str(job.id),
            user_id=str(job.user_id) if job.user_id else None,
            template=job.template,
        )
        job.last_error = "sms_skipped_not_configured"
        return "skipped"

    payload = job.payload or {}
    to_number = payload.get("to_number")
    body = payload.get("body")
    if not (to_number and body):
        job.last_error = "sms payload missing to_number/body"
        return "failed"

    # Import lazily so the test environment doesn't need twilio wired up.
    from twilio.rest import Client  # type: ignore[import-untyped]

    client = Client(settings.twilio_account_sid, settings.twilio_auth_token)
    client.messages.create(
        messaging_service_sid=settings.twilio_messaging_service_sid,
        to=to_number,
        body=body,
    )
    return "delivered"


async def _dispatch_slack(db: AsyncSession, job: NotificationJob) -> str:
    """Dispatch via :mod:`services.slack_dispatch_service`.

    Permanent errors (4xx, missing creds) → ``failed`` (no retry).
    Transient errors (5xx, 429, connection) → re-raise so the outer
    try/except in :func:`process_job` flips status to ``retry`` and
    schedules the next attempt with the existing backoff buckets."""
    from services import slack_dispatch_service

    payload = job.payload or {}
    text_body = payload.get("text") or payload.get("body") or ""
    blocks = payload.get("blocks")
    if not text_body:
        job.last_error = "slack payload missing text"
        return "failed"

    try:
        await slack_dispatch_service.send(db=db, text_body=text_body, blocks=blocks)
    except slack_dispatch_service.PermanentSlackError as exc:
        # Credential not configured or upstream returned 4xx (channel
        # not found, invalid payload, etc.) — no retry, mark failed.
        if str(exc) == "slack_skipped_not_configured":
            job.last_error = "slack_skipped_not_configured"
            return "skipped"
        job.last_error = f"slack_permanent: {exc}"[:1000]
        return "failed"
    return "delivered"

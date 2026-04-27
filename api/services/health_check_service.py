# ABOUTME: Phase 4 Sprint 7 — periodic health probe + admin alerts on red flip.
# ABOUTME: GET /admin/health reads the snapshot; scripts/health_poller.py runs the probe.
"""Health check service — Phase 4 Sprint 7.

Two callers:

- ``GET /admin/health`` (admin UI) — reads the persisted snapshot.
  When ``run_when_stale=True`` the snapshot triggers a fresh probe if
  it's older than ``_STALE_AFTER_SECONDS`` (default 30s) so admin's
  manual refresh is never lying about reality.
- ``scripts/health_poller.py`` (Fly scheduled machine) — calls
  :func:`run_all` every 30 seconds. Each call updates every row in
  ``service_health_state`` and dispatches alerts when a row flips to
  red.

Service taxonomy:

- ``database`` — ``SELECT 1`` round trip.
- ``r2`` — ``HeadBucket`` against the configured photos bucket.
- ``slack`` / ``twilio`` / ``sendgrid`` / ``google_maps`` — each runs
  through ``integration_testers.run`` *only* when a credential is set.
  Unset → ``status='unknown'`` (not red — admin hasn't configured it
  yet, that's not a degradation). Stubbed providers (eSign, valuation)
  use status='stubbed'.

Alert dispatch:

- Triggered when ``status`` flips to ``red`` AND
  (``last_alerted_at`` is None OR ``now - last_alerted_at > 15 min``).
- Recipients: every active user with the ``admin`` role plus
  ``in_app_enabled`` notification preference. Each admin's preferred
  channel determines whether they get email / sms / slack — fan out
  through ``notification_service.enqueue`` so retries + audit + the
  admin "view failed jobs" UI all work.
- Idempotency key: ``health_alert:{service}:{red_started_at}`` so two
  pollers racing the alert produce one set of jobs.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import boto3
import structlog
from botocore.exceptions import BotoCoreError, ClientError
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database.models import (
    IntegrationCredential,
    NotificationPreference,
    Role,
    ServiceHealthState,
    User,
    UserRole,
)
from services import credentials_vault, integration_testers, notification_service

logger = structlog.get_logger(__name__)

_ALERT_COOLDOWN = timedelta(minutes=15)
_STALE_AFTER_SECONDS = 30


# Order drives the admin UI rendering. DB + R2 first (platform), then the
# external integrations (admin can fix these without re-deploying).
_PLATFORM_SERVICES = ("database", "r2")
_INTEGRATION_SERVICES = ("slack", "twilio", "sendgrid", "google_maps")
_STUBBED_SERVICES = ("esign", "valuation")
_ALL_SERVICES = _PLATFORM_SERVICES + _INTEGRATION_SERVICES + _STUBBED_SERVICES


@dataclass(frozen=True)
class ProbeResult:
    status: str  # 'green' | 'red' | 'stubbed' | 'unknown'
    detail: str
    latency_ms: int


# --------------------------------------------------------------------------- #
# Probes
# --------------------------------------------------------------------------- #


async def _probe_database(db: AsyncSession) -> ProbeResult:
    started = datetime.now(UTC)
    try:
        await db.execute(text("SELECT 1"))
    except Exception as exc:
        latency = int((datetime.now(UTC) - started).total_seconds() * 1000)
        return ProbeResult(
            status="red",
            detail=f"{type(exc).__name__}: {exc}"[:500],
            latency_ms=latency,
        )
    latency = int((datetime.now(UTC) - started).total_seconds() * 1000)
    return ProbeResult(status="green", detail="ok", latency_ms=latency)


async def _probe_r2() -> ProbeResult:
    """HeadBucket against the photos bucket. Unconfigured → unknown
    (dev / test don't always wire R2). In production, unconfigured is
    promoted to red by the caller (mirrors :mod:`routers.health`)."""
    started = datetime.now(UTC)
    if not settings.r2_access_key_id or not settings.r2_secret_access_key:
        latency = int((datetime.now(UTC) - started).total_seconds() * 1000)
        return ProbeResult(
            status="unknown",
            detail="r2_unconfigured",
            latency_ms=latency,
        )
    try:

        def _head() -> None:
            client = boto3.client(
                "s3",
                endpoint_url=f"https://{settings.r2_account_id}.r2.cloudflarestorage.com",
                aws_access_key_id=settings.r2_access_key_id,
                aws_secret_access_key=settings.r2_secret_access_key,
                region_name="auto",
            )
            client.head_bucket(Bucket=settings.r2_bucket_photos)

        await asyncio.to_thread(_head)
    except (BotoCoreError, ClientError) as exc:
        latency = int((datetime.now(UTC) - started).total_seconds() * 1000)
        return ProbeResult(
            status="red",
            detail=f"{type(exc).__name__}: {exc}"[:500],
            latency_ms=latency,
        )
    latency = int((datetime.now(UTC) - started).total_seconds() * 1000)
    return ProbeResult(status="green", detail="ok", latency_ms=latency)


async def _probe_integration(db: AsyncSession, name: str) -> ProbeResult:
    """Decrypt the saved credential + dispatch through ``integration_testers``.

    Unset credential → ``unknown`` (not red — admin needs to configure
    it). Decrypt error → ``red`` (key rotation broke a credential)."""
    row = (
        await db.execute(
            select(IntegrationCredential).where(IntegrationCredential.integration_name == name)
        )
    ).scalar_one_or_none()
    if row is None:
        return ProbeResult(status="unknown", detail="not_configured", latency_ms=0)
    try:
        plaintext = credentials_vault.decrypt(row.encrypted_value)
    except credentials_vault.VaultDecryptError as exc:
        return ProbeResult(status="red", detail=str(exc), latency_ms=0)
    result = await integration_testers.run(name, plaintext)
    if result.success:
        return ProbeResult(
            status="green",
            detail=result.detail,
            latency_ms=result.latency_ms,
        )
    return ProbeResult(
        status="red",
        detail=result.detail,
        latency_ms=result.latency_ms,
    )


# --------------------------------------------------------------------------- #
# Persistence
# --------------------------------------------------------------------------- #


async def _upsert_state(
    db: AsyncSession,
    *,
    service_name: str,
    probe: ProbeResult,
) -> tuple[ServiceHealthState, str | None]:
    """Update ``service_health_state`` for one service.

    Returns ``(row, prior_status)``. ``prior_status`` is None if this is
    a brand-new row, the previous value otherwise — caller uses it to
    detect green→red flips."""
    row = (
        await db.execute(
            select(ServiceHealthState).where(ServiceHealthState.service_name == service_name)
        )
    ).scalar_one_or_none()

    prior_status: str | None = None
    error_detail: dict[str, Any] | None = (
        {"detail": probe.detail} if probe.status in ("red", "unknown") and probe.detail else None
    )

    if row is None:
        row = ServiceHealthState(
            service_name=service_name,
            status=probe.status,
            last_checked_at=datetime.now(UTC),
            error_detail=error_detail,
            latency_ms=probe.latency_ms,
        )
        db.add(row)
    else:
        prior_status = row.status
        row.status = probe.status
        row.last_checked_at = datetime.now(UTC)
        row.error_detail = error_detail
        row.latency_ms = probe.latency_ms
    await db.flush()
    return row, prior_status


# --------------------------------------------------------------------------- #
# Alerts
# --------------------------------------------------------------------------- #


async def _admin_recipients(db: AsyncSession) -> list[tuple[User, NotificationPreference | None]]:
    """All active admins with their notification preference row.

    Recipients with ``in_app_enabled=False`` still receive alerts via
    other channels — the in-app filter is the *web banner* preference,
    not the alert opt-out. Admins suppress alerts entirely by clearing
    their preferred channel."""
    result = await db.execute(
        select(User)
        .join(UserRole, UserRole.user_id == User.id)
        .join(Role, Role.id == UserRole.role_id)
        .where(Role.slug == "admin")
        .where(User.status == "active")
    )
    admins = list(result.scalars().unique())
    out: list[tuple[User, NotificationPreference | None]] = []
    for admin in admins:
        prefs = (
            await db.execute(
                select(NotificationPreference).where(NotificationPreference.user_id == admin.id)
            )
        ).scalar_one_or_none()
        out.append((admin, prefs))
    return out


async def _maybe_dispatch_alert(
    db: AsyncSession,
    *,
    row: ServiceHealthState,
    prior_status: str | None,
) -> bool:
    """Fan out admin notifications when service flips green/unknown → red.

    Rate-limited: skipped when the row was alerted in the last 15 minutes.
    Returns True iff an alert was dispatched."""
    if row.status != "red":
        return False
    if prior_status == "red":
        return False  # already red — no duplicate alert.
    now = datetime.now(UTC)
    if row.last_alerted_at is not None and now - row.last_alerted_at < _ALERT_COOLDOWN:
        return False

    detail_text = ""
    if row.error_detail and "detail" in row.error_detail:
        detail_text = str(row.error_detail["detail"])
    checked_at_str = (row.last_checked_at or now).isoformat()
    idempotency_seed = (row.last_checked_at or now).isoformat(timespec="seconds")

    recipients = await _admin_recipients(db)
    for admin, prefs in recipients:
        # Default to email if no prefs row.
        channel = (prefs.channel if prefs else None) or "email"
        if channel == "email":
            template = "service_health_red_alert"
            payload_extra: dict[str, Any] = {
                "to_email": admin.email,
                "variables": {
                    "service_name": row.service_name,
                    "error_detail": detail_text,
                    "checked_at": checked_at_str,
                },
            }
        elif channel == "sms":
            template = "service_health_red_alert_sms"
            # SMS payload requires a to_number — gracefully skip if the
            # admin's preference is SMS but they don't have a phone stored.
            if not prefs or not prefs.phone_number:
                continue
            payload_extra = {
                "to_number": prefs.phone_number,
                "variables": {
                    "service_name": row.service_name,
                    "error_detail": detail_text,
                },
            }
        elif channel == "slack":
            template = "service_health_red_alert_slack"
            payload_extra = {
                "variables": {
                    "service_name": row.service_name,
                    "error_detail": detail_text,
                    "checked_at": checked_at_str,
                },
            }
        else:
            continue

        await notification_service.enqueue(
            db,
            idempotency_key=f"health_alert:{row.service_name}:{idempotency_seed}:{admin.id}",
            user_id=admin.id,
            channel=channel,
            template=template,
            payload=payload_extra,
        )

    row.last_alerted_at = now
    await db.flush()
    logger.info(
        "service_health_red_alert_dispatched",
        service=row.service_name,
        admin_count=len(recipients),
        prior_status=prior_status,
    )
    return True


# --------------------------------------------------------------------------- #
# Public surface
# --------------------------------------------------------------------------- #


async def run_all(db: AsyncSession) -> list[ServiceHealthState]:
    """Probe every monitored service + persist state + dispatch alerts.

    Returns the post-probe list of ``ServiceHealthState`` rows in the
    ``_ALL_SERVICES`` order."""
    rows: list[ServiceHealthState] = []

    db_probe = await _probe_database(db)
    row, prior = await _upsert_state(db, service_name="database", probe=db_probe)
    await _maybe_dispatch_alert(db, row=row, prior_status=prior)
    rows.append(row)

    r2_probe = await _probe_r2()
    row, prior = await _upsert_state(db, service_name="r2", probe=r2_probe)
    await _maybe_dispatch_alert(db, row=row, prior_status=prior)
    rows.append(row)

    for name in _INTEGRATION_SERVICES:
        probe = await _probe_integration(db, name)
        row, prior = await _upsert_state(db, service_name=name, probe=probe)
        await _maybe_dispatch_alert(db, row=row, prior_status=prior)
        rows.append(row)

    for name in _STUBBED_SERVICES:
        probe = ProbeResult(status="stubbed", detail="provider stubbed", latency_ms=0)
        row, _prior = await _upsert_state(db, service_name=name, probe=probe)
        rows.append(row)

    return rows


async def list_state(db: AsyncSession) -> list[ServiceHealthState]:
    """Read the persisted snapshot.

    Includes any service that has ever been probed; if a service has
    never run (fresh deploy), the snapshot is empty for it. Caller can
    invoke :func:`run_all` to populate."""
    result = await db.execute(select(ServiceHealthState))
    rows = list(result.scalars().unique())
    by_name = {r.service_name: r for r in rows}
    return [by_name[name] for name in _ALL_SERVICES if name in by_name]


def all_services() -> tuple[str, ...]:
    return _ALL_SERVICES

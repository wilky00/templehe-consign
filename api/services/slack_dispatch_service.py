# ABOUTME: Phase 4 Sprint 7 — Slack webhook dispatcher (resolves Phase 3 deferral).
# ABOUTME: notification_service routes channel='slack' jobs here.
"""Slack dispatch — Phase 4 Sprint 7.

Phase 3 left Slack as a no-op even though `channel='slack'` was a
documented pref. Sprint 7 wires the real dispatch path: the worker
loads the webhook URL from the credentials vault (integration_name
``slack``), POSTs the payload, and re-raises on transient HTTP failures
so the existing exponential-backoff retry loop in
``notification_service.process_job`` does its thing.

We classify failures conservatively:

- 5xx + connection errors → ``TransientSlackError`` → retry.
- 4xx (except 429) → permanent. Slack returns 4xx for "channel not
  found" / "invalid_payload" / etc.; retrying won't help, fail loudly
  so admin can see the dispatch in ``notification_jobs`` with status
  ``failed`` + the upstream detail in ``last_error``.
- 429 → transient (Slack throttles via Retry-After).

The webhook URL itself is treated as a credential — ``credentials_vault``
gives us an encrypted blob the admin set via the integrations UI. If
no Slack credential is saved, the dispatcher logs ``slack_skipped_not_configured``
and returns ``skipped`` so the job is not retried.
"""

from __future__ import annotations

import structlog
from httpx import AsyncClient, HTTPError, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import IntegrationCredential
from services import credentials_vault

logger = structlog.get_logger(__name__)


class TransientSlackError(Exception):
    """Retryable failure — 5xx, 429, or connection error."""


class PermanentSlackError(Exception):
    """Non-retryable failure — 4xx (except 429), invalid webhook URL, etc."""


async def _load_webhook_url(db: AsyncSession) -> str | None:
    row = (
        await db.execute(
            select(IntegrationCredential).where(IntegrationCredential.integration_name == "slack")
        )
    ).scalar_one_or_none()
    if row is None:
        return None
    return credentials_vault.decrypt(row.encrypted_value)


async def send(*, db: AsyncSession, text_body: str, blocks: list | None = None) -> None:
    """POST a message to the Slack webhook stored in the integrations vault.

    Raises :class:`TransientSlackError` on 5xx / 429 / connection errors,
    :class:`PermanentSlackError` on 4xx, and returns silently on 200 OK.
    Callers can also catch the unwrapped ``HTTPError`` if they want, but
    the wrapped exceptions are how the worker classifies retry vs fail.
    """
    webhook_url = await _load_webhook_url(db)
    if not webhook_url:
        logger.info("slack_skipped_not_configured")
        raise PermanentSlackError("slack_skipped_not_configured")

    payload: dict = {"text": text_body}
    if blocks:
        payload["blocks"] = blocks

    try:
        async with AsyncClient(timeout=10.0) as client:
            response: Response = await client.post(webhook_url, json=payload)
    except HTTPError as exc:
        # Connection error / DNS failure / timeout — retry.
        raise TransientSlackError(f"{type(exc).__name__}: {exc}") from exc

    if response.status_code == 200 and response.text.strip() == "ok":
        return
    if response.status_code in (429, 500, 502, 503, 504):
        raise TransientSlackError(
            f"Slack returned HTTP {response.status_code}: {response.text[:200]}"
        )
    raise PermanentSlackError(f"Slack returned HTTP {response.status_code}: {response.text[:200]}")

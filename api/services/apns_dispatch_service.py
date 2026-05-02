# ABOUTME: Phase 5 Sprint 2 — APNs push notification dispatcher.
# ABOUTME: Signs JWTs with Apple AuthKey from the credentials vault; HTTP/2 to api.push.apple.com.
"""APNs dispatch service — Phase 5 Sprint 2.

Sends iOS push notifications via Apple's HTTP/2 API using JWT-based
provider authentication (token auth, not TLS cert auth).

Credential format (stored in the integration credentials vault under the
name ``apns``):

    {
        "private_key": "-----BEGIN PRIVATE KEY-----\\n...\\n-----END PRIVATE KEY-----\\n",
        "key_id": "XXXXXXXXXX",
        "team_id": "YYYYYYYYYY"
    }

Failure classification:
- 200 → success
- 410 Unregistered / 400 BadDeviceToken → permanent failure; caller
  should soft-delete the device_token row (token will never work again).
- 4xx (other) → permanent failure; do not retry.
- 5xx / connection error → transient; raises ``TransientAPNsError`` so
  the caller's retry loop picks it up.
- Missing vault credential → ``skipped`` (APNs not yet provisioned).

JWT lifecycle: Apple accepts tokens issued within the last 60 minutes. We
sign a fresh token per-call at our scale. Caching is a future optimisation
if throughput warrants it.
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Any

import jwt
import structlog
from httpx import AsyncClient, HTTPError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import IntegrationCredential
from services import credentials_vault

logger = structlog.get_logger(__name__)

_APNS_TOPIC = "com.templehe.appraiser"
_APNS_HOST_PRODUCTION = "https://api.push.apple.com"
_APNS_HOST_SANDBOX = "https://api.sandbox.push.apple.com"


class TransientAPNsError(Exception):
    """Retryable failure — 5xx or connection error."""


class PermanentAPNsError(Exception):
    """Non-retryable failure — bad token, 4xx, etc."""


async def _load_credential(db: AsyncSession) -> dict | None:
    """Return the parsed APNs credential JSON, or None if not configured."""
    row = (
        await db.execute(
            select(IntegrationCredential).where(IntegrationCredential.integration_name == "apns")
        )
    ).scalar_one_or_none()
    if row is None:
        return None
    plaintext = credentials_vault.decrypt(row.encrypted_value)
    return json.loads(plaintext)


def _sign_jwt(cred: dict) -> str:
    """Sign an APNs provider JWT. Valid for up to 60 minutes."""
    return jwt.encode(
        {"iss": cred["team_id"], "iat": int(time.time())},
        cred["private_key"],
        algorithm="ES256",
        headers={"kid": cred["key_id"]},
    )


def _apns_host(device_environment: str) -> str:
    if device_environment == "production":
        return _APNS_HOST_PRODUCTION
    return _APNS_HOST_SANDBOX


async def send(
    db: AsyncSession,
    *,
    token: str,
    device_environment: str,
    title: str,
    body: str,
    data: dict[str, Any] | None = None,
    device_token_id: uuid.UUID | None = None,
) -> str:
    """Send one APNs push notification. Returns "delivered", "failed", or "skipped".

    ``device_token_id`` is used to soft-delete the device_token row on
    permanent failure (BadDeviceToken / Unregistered). Pass it whenever
    the caller has it; without it the token row is not cleaned up.

    Raises :class:`TransientAPNsError` on 5xx / connection failures so
    the notification worker's retry loop takes over.
    """
    cred = await _load_credential(db)
    if cred is None:
        logger.info("apns_skipped_not_configured", token_prefix=token[:8])
        return "skipped"

    signed_jwt = _sign_jwt(cred)
    host = _apns_host(device_environment)
    url = f"{host}/3/device/{token}"

    payload: dict[str, Any] = {
        "aps": {
            "alert": {"title": title, "body": body},
            "sound": "default",
        }
    }
    if data:
        payload.update(data)

    headers = {
        "authorization": f"bearer {signed_jwt}",
        "apns-topic": _APNS_TOPIC,
        "apns-push-type": "alert",
        "apns-priority": "10",
        "content-type": "application/json",
    }

    try:
        async with AsyncClient(http2=True) as client:
            resp = await client.post(url, json=payload, headers=headers, timeout=10.0)
    except HTTPError as exc:
        raise TransientAPNsError(f"APNs connection error: {exc}") from exc

    if resp.status_code == 200:
        logger.info(
            "apns_delivered",
            token_prefix=token[:8],
            environment=device_environment,
        )
        return "delivered"

    # Parse APNs error reason from response body.
    try:
        reason = resp.json().get("reason", "unknown")
    except Exception:
        reason = "unparseable"

    permanent_reasons = {"BadDeviceToken", "Unregistered", "MissingDeviceToken"}
    is_permanent = resp.status_code == 410 or (
        resp.status_code == 400 and reason in permanent_reasons
    )

    if is_permanent:
        logger.warning(
            "apns_permanent_failure",
            token_prefix=token[:8],
            status=resp.status_code,
            reason=reason,
        )
        if device_token_id is not None:
            from services import device_token_service

            await device_token_service.revoke_by_id(db, token_id=device_token_id)
        return "failed"

    if resp.status_code >= 500:
        raise TransientAPNsError(f"APNs 5xx: {resp.status_code} {reason}")

    # Other 4xx — permanent, no retry.
    logger.error(
        "apns_4xx_failure",
        token_prefix=token[:8],
        status=resp.status_code,
        reason=reason,
    )
    return "failed"

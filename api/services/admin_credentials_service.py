# ABOUTME: Phase 4 Sprint 7 — admin-side store/reveal/test for integration credentials.
# ABOUTME: Reveal requires step-up (password + TOTP); plaintext is never logged.
"""Admin credentials service — Phase 4 Sprint 7.

Three operations the admin UI needs:

1. ``store(name, plaintext, actor)`` — encrypt + upsert. Audit log
   records ``integration_credential_set`` with ``actor_id`` /
   ``actor_role`` but NEVER the plaintext (or even a hash of it —
   reversal-resistance + audit utility wins both).

2. ``reveal(name, actor, password, totp_code)`` — step-up auth gate.
   Verifies the actor's password + TOTP fresh against ``users``;
   passes only when the actor has 2FA enabled (admin must, per
   security baseline §1). Rate-limited to 10 reveals per actor per
   hour via the same ``rate_limit_counters`` table the auth flow uses.
   Audit log records ``integration_credential_revealed``.

3. ``test(name)`` — load + decrypt + dispatch to the per-integration
   tester. Updates ``integration_credentials.last_tested_*`` so the
   admin UI can render the badge without a fresh test. Audit log
   records ``integration_credential_tested``.

The plaintext only lives in the function frame for the duration of the
operation. We don't return plaintext from store/test; only reveal does,
and it's wrapped in a step-up gate.

The reveal step-up rejects the actor when:
- they have no password set (Google SSO admin should switch to 2FA-enabled
  password before revealing — failure mode is operational, not silent).
- they don't have TOTP enabled.
- the supplied password is wrong (audit + rate-limit counter).
- the supplied TOTP code is wrong (audit + rate-limit counter).

Failures throw :class:`StepUpFailed` with a generic detail so the admin
UI can render "step-up failed — wrong password or TOTP" without leaking
which one was wrong.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import pyotp
import structlog
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import AuditLog, IntegrationCredential, User
from services import credentials_vault, integration_testers
from services.auth_service import _decrypt_totp_secret, verify_password

logger = structlog.get_logger(__name__)


_REVEAL_LIMIT_PER_HOUR = 10
_REVEAL_WINDOW_SECONDS = 3600


# --------------------------------------------------------------------------- #
# Errors
# --------------------------------------------------------------------------- #


class StepUpFailed(Exception):
    """Raised when reveal step-up auth fails — wrong password or TOTP."""


class StepUpRateLimited(Exception):
    """Raised when an admin has exceeded the reveal rate limit."""


class UnknownIntegration(Exception):
    """Raised when the integration name isn't in the testers registry."""


class CredentialNotFound(Exception):
    """Raised when reveal/test is called against an unsaved credential."""


# --------------------------------------------------------------------------- #
# Public dataclasses
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class IntegrationMetadata:
    name: str
    is_set: bool
    set_by: uuid.UUID | None
    set_at: datetime | None
    last_tested_at: datetime | None
    last_test_status: str | None
    last_test_detail: str | None
    last_test_latency_ms: int | None


@dataclass(frozen=True)
class RevealResult:
    name: str
    plaintext: str
    revealed_at: datetime


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


async def _audit(
    db: AsyncSession,
    *,
    event_type: str,
    actor: User,
    target_name: str,
    after_state: dict[str, Any] | None = None,
) -> None:
    db.add(
        AuditLog(
            event_type=event_type,
            actor_id=actor.id,
            actor_role="admin",
            target_id=None,
            target_type="integration_credential",
            after_state={"integration_name": target_name, **(after_state or {})},
        )
    )


async def _check_reveal_rate_limit(db: AsyncSession, actor_id: uuid.UUID) -> None:
    """Increment the reveal counter; raises StepUpRateLimited at 10/hour.

    Reuses the same fixed-window pattern the auth flow uses — keyed off
    the actor's UUID, so an admin with a compromised password can't
    bulk-reveal credentials at scale even before the auth flow's
    account lockout fires."""
    now = datetime.now(UTC)
    window_start = now.replace(minute=0, second=0, microsecond=0)
    row_id = str(uuid.uuid4())
    key = f"integration_reveal:{actor_id}"
    result = await db.execute(
        text(
            "INSERT INTO rate_limit_counters (id, key, window_start, count) "
            "VALUES (:id, :key, :window_start, 1) "
            "ON CONFLICT (key, window_start) "
            "DO UPDATE SET count = rate_limit_counters.count + 1 "
            "RETURNING count"
        ),
        {"id": row_id, "key": key, "window_start": window_start},
    )
    count = result.scalar_one()
    await db.flush()
    if count > _REVEAL_LIMIT_PER_HOUR:
        raise StepUpRateLimited(
            f"reveal rate limit ({_REVEAL_LIMIT_PER_HOUR}/hour) exceeded for actor"
        )


# --------------------------------------------------------------------------- #
# list_metadata
# --------------------------------------------------------------------------- #


async def list_metadata(db: AsyncSession) -> list[IntegrationMetadata]:
    """Return one row per known integration — saved or not.

    Unsaved integrations show ``is_set=False`` so the admin UI renders
    a card with a Save button instead of hiding the integration.
    """
    rows = (
        (
            await db.execute(
                select(IntegrationCredential).order_by(IntegrationCredential.integration_name)
            )
        )
        .scalars()
        .all()
    )
    by_name = {row.integration_name: row for row in rows}

    out: list[IntegrationMetadata] = []
    for name in integration_testers.known_integrations():
        row = by_name.get(name)
        if row is None:
            out.append(
                IntegrationMetadata(
                    name=name,
                    is_set=False,
                    set_by=None,
                    set_at=None,
                    last_tested_at=None,
                    last_test_status=None,
                    last_test_detail=None,
                    last_test_latency_ms=None,
                )
            )
        else:
            out.append(
                IntegrationMetadata(
                    name=name,
                    is_set=True,
                    set_by=row.set_by,
                    set_at=row.set_at,
                    last_tested_at=row.last_tested_at,
                    last_test_status=row.last_test_status,
                    last_test_detail=row.last_test_detail,
                    last_test_latency_ms=row.last_test_latency_ms,
                )
            )
    return out


# --------------------------------------------------------------------------- #
# store
# --------------------------------------------------------------------------- #


async def store(
    db: AsyncSession,
    *,
    name: str,
    plaintext: str,
    actor: User,
) -> IntegrationMetadata:
    """Encrypt + upsert. Plaintext stays in this function frame only."""
    if not integration_testers.is_known(name):
        raise UnknownIntegration(name)
    if not plaintext or not plaintext.strip():
        raise ValueError("plaintext must not be empty")

    encrypted = credentials_vault.encrypt(plaintext)

    existing = (
        await db.execute(
            select(IntegrationCredential).where(IntegrationCredential.integration_name == name)
        )
    ).scalar_one_or_none()

    now = datetime.now(UTC)
    if existing is None:
        row = IntegrationCredential(
            integration_name=name,
            encrypted_value=encrypted,
            set_by=actor.id,
            set_at=now,
            # Saved → previous test result is no longer authoritative.
            last_tested_at=None,
            last_test_status=None,
            last_test_detail=None,
            last_test_latency_ms=None,
        )
        db.add(row)
    else:
        existing.encrypted_value = encrypted
        existing.set_by = actor.id
        existing.set_at = now
        existing.last_tested_at = None
        existing.last_test_status = None
        existing.last_test_detail = None
        existing.last_test_latency_ms = None
        row = existing

    await _audit(db, event_type="integration_credential_set", actor=actor, target_name=name)
    await db.flush()
    logger.info(
        "integration_credential_set",
        integration=name,
        actor_id=str(actor.id),
    )
    return IntegrationMetadata(
        name=row.integration_name,
        is_set=True,
        set_by=row.set_by,
        set_at=row.set_at,
        last_tested_at=row.last_tested_at,
        last_test_status=row.last_test_status,
        last_test_detail=row.last_test_detail,
        last_test_latency_ms=row.last_test_latency_ms,
    )


# --------------------------------------------------------------------------- #
# reveal
# --------------------------------------------------------------------------- #


async def reveal(
    db: AsyncSession,
    *,
    name: str,
    actor: User,
    password: str,
    totp_code: str,
) -> RevealResult:
    """Verify password + TOTP fresh, then return the plaintext.

    Failures raise :class:`StepUpFailed` with a generic detail so the
    UI doesn't leak which factor was wrong. Rate-limited to 10/hour
    per actor via :func:`_check_reveal_rate_limit`.
    """
    await _check_reveal_rate_limit(db, actor.id)

    if not actor.password_hash or not actor.totp_enabled or not actor.totp_secret_enc:
        await _audit(
            db,
            event_type="integration_credential_reveal_blocked",
            actor=actor,
            target_name=name,
            after_state={"reason": "actor_missing_password_or_totp"},
        )
        raise StepUpFailed("Reveal requires a password + active TOTP on your account.")

    if not verify_password(password, actor.password_hash):
        await _audit(
            db,
            event_type="integration_credential_reveal_failed",
            actor=actor,
            target_name=name,
            after_state={"reason": "wrong_password"},
        )
        raise StepUpFailed("Wrong password or TOTP code.")

    secret = _decrypt_totp_secret(actor.totp_secret_enc)
    if not pyotp.TOTP(secret).verify(totp_code, valid_window=1):
        await _audit(
            db,
            event_type="integration_credential_reveal_failed",
            actor=actor,
            target_name=name,
            after_state={"reason": "wrong_totp"},
        )
        raise StepUpFailed("Wrong password or TOTP code.")

    row = (
        await db.execute(
            select(IntegrationCredential).where(IntegrationCredential.integration_name == name)
        )
    ).scalar_one_or_none()
    if row is None:
        raise CredentialNotFound(name)

    plaintext = credentials_vault.decrypt(row.encrypted_value)

    await _audit(
        db,
        event_type="integration_credential_revealed",
        actor=actor,
        target_name=name,
    )
    await db.flush()
    logger.info(
        "integration_credential_revealed",
        integration=name,
        actor_id=str(actor.id),
    )
    return RevealResult(name=name, plaintext=plaintext, revealed_at=datetime.now(UTC))


# --------------------------------------------------------------------------- #
# test
# --------------------------------------------------------------------------- #


async def test_credential(
    db: AsyncSession,
    *,
    name: str,
    actor: User,
    extra_args: dict[str, Any] | None = None,
) -> integration_testers.TestResult:
    """Load + decrypt + dispatch to the per-integration tester.

    Updates ``integration_credentials.last_tested_*`` columns so the
    admin UI can render the badge without re-running the test.
    """
    if not integration_testers.is_known(name):
        raise UnknownIntegration(name)

    row = (
        await db.execute(
            select(IntegrationCredential).where(IntegrationCredential.integration_name == name)
        )
    ).scalar_one_or_none()
    if row is None:
        raise CredentialNotFound(name)

    plaintext = credentials_vault.decrypt(row.encrypted_value)
    extras = extra_args or {}
    result = await integration_testers.run(name, plaintext, **extras)

    row.last_tested_at = datetime.now(UTC)
    row.last_test_status = result.status
    row.last_test_detail = result.detail
    row.last_test_latency_ms = result.latency_ms

    await _audit(
        db,
        event_type="integration_credential_tested",
        actor=actor,
        target_name=name,
        after_state={
            "result_status": result.status,
            "latency_ms": result.latency_ms,
        },
    )
    await db.flush()
    logger.info(
        "integration_credential_tested",
        integration=name,
        result=result.status,
        latency_ms=result.latency_ms,
    )
    return result

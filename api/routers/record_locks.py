# ABOUTME: Record lock endpoints — acquire/heartbeat/release/override with audit trail.
# ABOUTME: Any authed user can acquire; manager-or-admin override released in spec §3.5.2.
from __future__ import annotations

import uuid

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.base import get_db
from database.models import AuditLog, EquipmentRecord, Role, User
from middleware.auth import get_current_user
from middleware.rbac import require_roles
from schemas.record_lock import LockAcquireRequest, LockConflictOut, LockInfoOut
from services import (
    notification_preferences_service,
    notification_service,
    record_lock_service,
)
from services.record_lock_service import (
    LockExpiredError,
    LockHeldError,
)

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/record-locks", tags=["record-locks"])

_ALLOWED_RECORD_TYPES = {"equipment_record"}


async def _role_slug(db: AsyncSession, user: User) -> str | None:
    result = await db.execute(select(Role.slug).where(Role.id == user.role_id))
    return result.scalar_one_or_none()


def _validate_record_type(record_type: str) -> None:
    if record_type not in _ALLOWED_RECORD_TYPES:
        raise HTTPException(
            status_code=422,
            detail=f"unsupported record_type: {record_type}",
        )


@router.post("", response_model=LockInfoOut)
async def acquire_lock(
    body: LockAcquireRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> LockInfoOut | JSONResponse:
    _validate_record_type(body.record_type)
    try:
        info = await record_lock_service.acquire(
            db,
            record_id=body.record_id,
            record_type=body.record_type,
            user_id=current_user.id,
        )
    except LockHeldError as exc:
        return JSONResponse(
            status_code=409,
            content=LockConflictOut(
                detail="record is locked by another user",
                locked_by=exc.info.locked_by,
                locked_at=exc.info.locked_at.isoformat(),
                expires_at=exc.info.expires_at.isoformat(),
            ).model_dump(mode="json"),
        )

    role = await _role_slug(db, current_user)
    db.add(
        AuditLog(
            event_type="record_lock.acquired",
            actor_id=current_user.id,
            actor_role=role,
            target_type=body.record_type,
            target_id=body.record_id,
            after_state={"expires_at": info.expires_at.isoformat()},
            ip_address=request.client.host if request.client else None,
        )
    )
    await db.flush()
    return LockInfoOut(**info.__dict__)


@router.put("/{record_id}/heartbeat", response_model=LockInfoOut)
async def heartbeat_lock(
    record_id: uuid.UUID,
    record_type: str = "equipment_record",
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> LockInfoOut:
    _validate_record_type(record_type)
    try:
        info = await record_lock_service.heartbeat(
            db,
            record_id=record_id,
            record_type=record_type,
            user_id=current_user.id,
        )
    except LockExpiredError as exc:
        raise HTTPException(status_code=404, detail="lock expired or not held") from exc
    return LockInfoOut(**info.__dict__)


@router.delete("/{record_id}", status_code=204)
async def release_lock(
    record_id: uuid.UUID,
    request: Request,
    record_type: str = "equipment_record",
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    _validate_record_type(record_type)
    removed = await record_lock_service.release(
        db,
        record_id=record_id,
        record_type=record_type,
        user_id=current_user.id,
    )
    if not removed:
        # Idempotent: release on a lock you don't own (or that's already gone)
        # is a no-op rather than an error so clients can safely fire-and-forget
        # on page unload.
        return

    role = await _role_slug(db, current_user)
    db.add(
        AuditLog(
            event_type="record_lock.released",
            actor_id=current_user.id,
            actor_role=role,
            target_type=record_type,
            target_id=record_id,
            ip_address=request.client.host if request.client else None,
        )
    )
    await db.flush()


@router.delete("/{record_id}/override", status_code=204)
async def override_lock(
    record_id: uuid.UUID,
    request: Request,
    record_type: str = "equipment_record",
    current_user: User = Depends(require_roles("sales_manager", "admin")),
    db: AsyncSession = Depends(get_db),
) -> None:
    _validate_record_type(record_type)
    prior = await record_lock_service.override(
        db,
        record_id=record_id,
        record_type=record_type,
    )
    if prior is None:
        raise HTTPException(status_code=404, detail="no lock to override")

    role = await _role_slug(db, current_user)
    db.add(
        AuditLog(
            event_type="record_lock.overridden",
            actor_id=current_user.id,
            actor_role=role,
            target_type=record_type,
            target_id=record_id,
            before_state={
                "locked_by": str(prior.locked_by),
                "locked_at": prior.locked_at.isoformat(),
                "expires_at": prior.expires_at.isoformat(),
            },
            ip_address=request.client.host if request.client else None,
        )
    )
    await db.flush()
    await _notify_prior_lock_holder(
        db,
        prior_user_id=prior.locked_by,
        record_id=record_id,
        record_type=record_type,
        manager_first_name=current_user.first_name or "a manager",
    )


async def _notify_prior_lock_holder(
    db: AsyncSession,
    *,
    prior_user_id: uuid.UUID,
    record_id: uuid.UUID,
    record_type: str,
    manager_first_name: str,
) -> None:
    """Spec Feature 3.5.2 — tell the user whose lock was just broken.

    Best-effort: skips silently if the user is gone or inactive. Channel
    resolves via the user's preferred channel; SMS dispatch falls back
    to email when no phone number is on file.
    """
    prior = (await db.execute(select(User).where(User.id == prior_user_id))).scalar_one_or_none()
    if prior is None or prior.status != "active":
        return

    ref = await _record_reference(db, record_id=record_id, record_type=record_type)
    resolved = await notification_preferences_service.resolve_channel(db, user=prior)
    idem = f"lock_overridden:{record_id}:{prior_user_id}"

    if resolved.channel == "sms" and resolved.destination:
        await notification_service.enqueue(
            db,
            idempotency_key=idem,
            user_id=prior.id,
            channel="sms",
            template="record_lock_overridden",
            payload={
                "to_number": resolved.destination,
                "body": (
                    f"TempleHE: your editing lock on {ref} was released by {manager_first_name}."
                ),
                "reference_number": ref,
            },
        )
        return

    if not resolved.destination:
        return

    subject = f"Your editing lock on {ref} was released"
    body = (
        f"<p>Hi {prior.first_name or 'team'},</p>"
        f"<p>Your editing lock on <strong>{ref}</strong> was released "
        f"by {manager_first_name} so the record could be edited.</p>"
        "<p>Reopen the record from the sales dashboard if you still need to make changes.</p>"
    )
    await notification_service.enqueue(
        db,
        idempotency_key=idem,
        user_id=prior.id,
        channel="email",
        template="record_lock_overridden",
        payload={
            "to_email": resolved.destination,
            "subject": subject,
            "html_body": body,
            "reference_number": ref,
        },
    )


async def _record_reference(db: AsyncSession, *, record_id: uuid.UUID, record_type: str) -> str:
    """Best-effort human-readable label for the locked record."""
    if record_type != "equipment_record":
        return str(record_id)
    ref = (
        await db.execute(
            select(EquipmentRecord.reference_number).where(EquipmentRecord.id == record_id)
        )
    ).scalar_one_or_none()
    return ref or str(record_id)

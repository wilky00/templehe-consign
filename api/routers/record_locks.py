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
from database.models import AuditLog, Role, User
from middleware.auth import get_current_user
from middleware.rbac import require_roles
from schemas.record_lock import LockAcquireRequest, LockConflictOut, LockInfoOut
from services import record_lock_service
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

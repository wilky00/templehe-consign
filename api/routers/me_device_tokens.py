# ABOUTME: Phase 5 Sprint 1 — POST/DELETE/GET /api/v1/me/device-token (APNs/FCM registration).
# ABOUTME: Gated to appraiser/admin/sales/sales_manager (mirrors /ios/config's gate).
from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from database.base import get_db
from database.models import User
from middleware.rbac import require_roles
from schemas.device_token import (
    DeviceTokenListResponse,
    DeviceTokenOut,
    DeviceTokenRegisterRequest,
    DeviceTokenRevokeRequest,
)
from services import device_token_service

router = APIRouter(prefix="/me/device-token", tags=["mobile"])

# Mirrors /ios/config — any field user who can fetch the iOS config
# can also register a push target. Customer role is excluded (no
# customer-facing app today). Phase 4 admin's "all field roles" gate.
_require_field_user = require_roles("appraiser", "admin", "sales", "sales_manager")


def _to_out(row) -> DeviceTokenOut:
    """Hide the full token; expose just a preview for UI distinction."""
    preview = row.token[-8:] if len(row.token) >= 8 else row.token
    return DeviceTokenOut(
        id=row.id,
        platform=row.platform,
        environment=row.environment,
        token_preview=preview,
        registered_at=row.registered_at,
        last_seen_at=row.last_seen_at,
    )


@router.post(
    "",
    response_model=DeviceTokenOut,
    status_code=status.HTTP_201_CREATED,
)
async def register_device_token(
    body: DeviceTokenRegisterRequest,
    current_user: User = Depends(_require_field_user),
    db: AsyncSession = Depends(get_db),
) -> DeviceTokenOut:
    """Register or refresh a device token. Idempotent on (user, token)."""
    row = await device_token_service.register(
        db,
        user=current_user,
        platform=body.platform,
        token=body.token,
        environment=body.environment,
    )
    return _to_out(row)


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_device_token(
    body: DeviceTokenRevokeRequest,
    current_user: User = Depends(_require_field_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Revoke one device token. Idempotent — no-op if already revoked.

    Returns 204 in both cases; the iOS client doesn't care whether the
    server-side row existed, only that it isn't active anymore."""
    await device_token_service.revoke(db, user=current_user, token=body.token)


@router.get("", response_model=DeviceTokenListResponse)
async def list_device_tokens(
    current_user: User = Depends(_require_field_user),
    db: AsyncSession = Depends(get_db),
) -> DeviceTokenListResponse:
    """List active device tokens for the current user.

    Useful for a "your registered devices" UI down the line; for now,
    Sprint 1 just exposes it so tests can assert post-registration state."""
    rows = await device_token_service.tokens_for_user(db, user_id=current_user.id)
    return DeviceTokenListResponse(tokens=[_to_out(r) for r in rows])

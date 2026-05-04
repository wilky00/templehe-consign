# ABOUTME: Phase 8 analytics event capture endpoint.
# ABOUTME: Accepts client-side events; silently drops events from staff roles.
from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database.base import get_db
from database.models import AnalyticsEvent, Role, User
from schemas.analytics import AnalyticsEventCreate, AnalyticsEventResponse

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["analytics"])

# Roles whose sessions we do not track — staff behavior would skew customer metrics.
_SKIP_ROLES = {"sales", "sales_manager", "admin", "appraiser", "reporting"}

_bearer = HTTPBearer(auto_error=False)


async def _optional_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: AsyncSession = Depends(get_db),
) -> User | None:
    """Return the current user if a valid Bearer token is present, else None."""
    if credentials is None:
        return None
    try:
        import jwt

        payload = jwt.decode(
            credentials.credentials,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
        )
    except Exception:
        return None
    if payload.get("type") != "access":
        return None
    user_id_str: str | None = payload.get("sub")
    if not user_id_str:
        return None
    import uuid

    result = await db.execute(select(User).where(User.id == uuid.UUID(user_id_str)))
    user = result.scalar_one_or_none()
    if user is None or user.status not in ("active", "pending_deletion"):
        return None
    return user


@router.post("/analytics/event", response_model=AnalyticsEventResponse)
async def record_event(
    body: AnalyticsEventCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(_optional_user),
) -> AnalyticsEventResponse:
    """Fire-and-forget analytics event from the frontend client.

    Events from staff roles are silently dropped. PII validation is handled
    by the schema validator on the metadata field.
    """
    if current_user is not None:
        role_row = (
            await db.execute(select(Role).where(Role.id == current_user.role_id))
        ).scalar_one_or_none()
        if role_row and role_row.slug in _SKIP_ROLES:
            return AnalyticsEventResponse(recorded=False)

    event = AnalyticsEvent(
        session_id=body.session_id,
        user_id=current_user.id if current_user else None,
        event_type=body.event_type,
        page=body.page,
        event_metadata=body.metadata,
    )
    db.add(event)
    await db.commit()
    return AnalyticsEventResponse(recorded=True)

# ABOUTME: GET/PUT /me/notification-preferences — preferred channel per logged-in user.
# ABOUTME: 404 when role is hidden via app_config; 403 on PUT for read-only roles (customers).
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.base import get_db
from database.models import Role, User
from middleware.auth import CurrentUserDep
from schemas.notification_preferences import (
    NotificationPreferenceOut,
    NotificationPreferenceUpdate,
)
from services import notification_preferences_service

router = APIRouter(prefix="/me/notification-preferences", tags=["customer"])


async def _role_slug(db: AsyncSession, user: User) -> str:
    slug = (await db.execute(select(Role.slug).where(Role.id == user.role_id))).scalar_one_or_none()
    if slug is None:
        raise HTTPException(status_code=403, detail="role not resolved")
    return slug


def _to_out(
    *,
    channel: str,
    phone_number: str | None,
    slack_user_id: str | None,
    read_only: bool,
) -> NotificationPreferenceOut:
    return NotificationPreferenceOut(
        channel=channel,  # type: ignore[arg-type]
        phone_number=phone_number,
        slack_user_id=slack_user_id,
        read_only=read_only,
    )


@router.get("", response_model=NotificationPreferenceOut)
async def get_preferences(
    current_user: CurrentUserDep,
    db: AsyncSession = Depends(get_db),
) -> NotificationPreferenceOut:
    role = await _role_slug(db, current_user)
    if await notification_preferences_service.is_hidden_for_role(db, role_slug=role):
        # 404 (not 403) so the page is invisible to clients that aren't
        # supposed to see it — same hide-by-existence pattern as other
        # role-gated routes.
        raise HTTPException(status_code=404, detail="not found")

    pref = await notification_preferences_service.get_for_user(db, user_id=current_user.id)
    read_only = notification_preferences_service.is_read_only_for_role(role)
    if pref is None:
        return _to_out(
            channel="email",
            phone_number=None,
            slack_user_id=None,
            read_only=read_only,
        )
    return _to_out(
        channel=pref.channel,
        phone_number=pref.phone_number,
        slack_user_id=pref.slack_user_id,
        read_only=read_only,
    )


@router.put("", response_model=NotificationPreferenceOut)
async def put_preferences(
    body: NotificationPreferenceUpdate,
    current_user: CurrentUserDep,
    db: AsyncSession = Depends(get_db),
) -> NotificationPreferenceOut:
    role = await _role_slug(db, current_user)
    if await notification_preferences_service.is_hidden_for_role(db, role_slug=role):
        raise HTTPException(status_code=404, detail="not found")
    if notification_preferences_service.is_read_only_for_role(role):
        raise HTTPException(
            status_code=403,
            detail="your role cannot edit notification preferences",
        )

    pref = await notification_preferences_service.upsert_for_user(
        db,
        user_id=current_user.id,
        channel=body.channel,
        phone_number=body.phone_number,
        slack_user_id=body.slack_user_id,
    )
    return _to_out(
        channel=pref.channel,
        phone_number=pref.phone_number,
        slack_user_id=pref.slack_user_id,
        read_only=False,
    )

# ABOUTME: Phase 5 Sprint 2 — GET /api/v1/me/appointments (upcoming calendar events for appraisers).
# ABOUTME: iOS dashboard data source — enriched with customer + sales rep contact info.
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from database.base import get_db
from database.models import User
from middleware.rbac import require_roles
from schemas.appraiser import AppointmentListResponse
from services import appraiser_appointments_service

router = APIRouter(prefix="/me/appointments", tags=["mobile"])

_require_appraiser = require_roles("appraiser", "admin")


@router.get("", response_model=AppointmentListResponse)
async def list_appointments(
    days: int = Query(default=30, ge=1, le=90),
    current_user: User = Depends(_require_appraiser),
    db: AsyncSession = Depends(get_db),
) -> AppointmentListResponse:
    """Upcoming non-cancelled appointments for the authenticated appraiser.

    Returns events from now through ``days`` days ahead, ordered by
    ``scheduled_at`` ascending. The ``days`` parameter is capped at 90
    to prevent unbounded queries."""
    appointments = await appraiser_appointments_service.list_for_appraiser(
        db,
        user_id=current_user.id,
        days_ahead=days,
    )
    return AppointmentListResponse(appointments=appointments, days_ahead=days)

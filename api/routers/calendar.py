# ABOUTME: Phase 3 Sprint 4 — /calendar/events HTTP surface; sales+ RBAC; 409 has next-available.
# ABOUTME: Per Feature 3.4.1, sales / sales_manager / admin all author; audit log captures who.
from __future__ import annotations

import uuid
from datetime import UTC, datetime

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from database.base import get_db
from database.models import CalendarEvent, EquipmentRecord, Role, User
from middleware.rbac import require_roles
from schemas.calendar import (
    CalendarEventCreate,
    CalendarEventCustomer,
    CalendarEventEquipment,
    CalendarEventListResponse,
    CalendarEventOut,
    CalendarEventPatch,
)
from services import calendar_service

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/calendar", tags=["calendar"])

_require_sales = require_roles("sales", "sales_manager", "admin")


async def _acting_role_slug(db: AsyncSession, user: User) -> str:
    result = await db.execute(select(Role.slug).where(Role.id == user.role_id))
    slug = result.scalar_one_or_none()
    if slug is None:
        raise HTTPException(status_code=403, detail="role not resolved")
    return slug


def _to_out(event: CalendarEvent) -> CalendarEventOut:
    record = event.equipment_record
    customer_payload = None
    equipment_payload = None
    if record is not None:
        equipment_payload = CalendarEventEquipment(
            id=record.id,
            reference_number=record.reference_number,
            make=record.customer_make,
            model=record.customer_model,
            location_text=record.customer_location_text,
        )
        if record.customer is not None:
            customer_payload = CalendarEventCustomer(
                id=record.customer.id,
                name=record.customer.submitter_name,
                business_name=record.customer.business_name,
            )
    return CalendarEventOut(
        id=event.id,
        equipment_record_id=event.equipment_record_id,
        appraiser_id=event.appraiser_id,
        scheduled_at=event.scheduled_at,
        duration_minutes=event.duration_minutes,
        site_address=event.site_address,
        cancelled_at=event.cancelled_at,
        customer=customer_payload,
        equipment=equipment_payload,
    )


def _conflict_response(conflict: calendar_service.CalendarConflict) -> JSONResponse:
    body = {
        "detail": conflict.message,
        "next_available_at": conflict.next_available_at.isoformat()
        if conflict.next_available_at
        else None,
        "conflicting_event_id": str(conflict.conflicting_event_id)
        if conflict.conflicting_event_id
        else None,
    }
    return JSONResponse(status_code=409, content=body)


def _ensure_aware(value: datetime) -> datetime:
    """Pydantic gives us a naive datetime when the input has no offset.

    Treat that as UTC so DB writes are consistent with timezone-aware
    schemas elsewhere.
    """
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


# --------------------------------------------------------------------------- #
# Endpoints
# --------------------------------------------------------------------------- #


async def _hydrate_event(db: AsyncSession, event_id: uuid.UUID) -> CalendarEvent:
    """Re-fetch with relationships eager-loaded so serialization doesn't lazy-load.

    Calendar events live alongside async session edges; touching
    ``event.equipment_record.customer`` mid-request without a greenlet
    blows up. Pull everything we need in one shot.
    """
    return (
        await db.execute(
            select(CalendarEvent)
            .options(
                selectinload(CalendarEvent.equipment_record).selectinload(EquipmentRecord.customer),
            )
            .where(CalendarEvent.id == event_id)
        )
    ).scalar_one()


@router.get("/events", response_model=CalendarEventListResponse)
async def list_events(
    start: datetime = Query(...),
    end: datetime = Query(...),
    appraiser_id: uuid.UUID | None = Query(default=None),
    _user: User = Depends(_require_sales),
    db: AsyncSession = Depends(get_db),
) -> CalendarEventListResponse:
    if end <= start:
        raise HTTPException(status_code=422, detail="end must be after start")
    events = await calendar_service.list_events(
        db,
        start=_ensure_aware(start),
        end=_ensure_aware(end),
        appraiser_id=appraiser_id,
    )
    return CalendarEventListResponse(
        events=[_to_out(e) for e in events],
        total=len(events),
    )


@router.post("/events", status_code=201)
async def create_event(
    body: CalendarEventCreate,
    current_user: User = Depends(_require_sales),
    db: AsyncSession = Depends(get_db),
):
    role_slug = await _acting_role_slug(db, current_user)
    result = await calendar_service.create_event(
        db,
        actor=current_user,
        actor_role=role_slug,
        record_id=body.equipment_record_id,
        appraiser_id=body.appraiser_id,
        scheduled_at=_ensure_aware(body.scheduled_at),
        duration_minutes=body.duration_minutes,
        site_address=body.site_address,
    )
    if isinstance(result, calendar_service.CalendarConflict):
        return _conflict_response(result)
    event = await _hydrate_event(db, result.id)
    return _to_out(event).model_dump(mode="json")


@router.patch("/events/{event_id}")
async def update_event(
    event_id: uuid.UUID,
    body: CalendarEventPatch,
    current_user: User = Depends(_require_sales),
    db: AsyncSession = Depends(get_db),
):
    role_slug = await _acting_role_slug(db, current_user)
    result = await calendar_service.update_event(
        db,
        actor=current_user,
        actor_role=role_slug,
        event_id=event_id,
        appraiser_id=body.appraiser_id,
        scheduled_at=_ensure_aware(body.scheduled_at) if body.scheduled_at else None,
        duration_minutes=body.duration_minutes,
        site_address=body.site_address,
        set_site_address="site_address" in body.model_fields_set,
    )
    if isinstance(result, calendar_service.CalendarConflict):
        return _conflict_response(result)
    event = await _hydrate_event(db, result.id)
    return _to_out(event).model_dump(mode="json")


@router.delete("/events/{event_id}")
async def cancel_event(
    event_id: uuid.UUID,
    current_user: User = Depends(_require_sales),
    db: AsyncSession = Depends(get_db),
):
    role_slug = await _acting_role_slug(db, current_user)
    result = await calendar_service.cancel_event(
        db,
        actor=current_user,
        actor_role=role_slug,
        event_id=event_id,
    )
    event = await _hydrate_event(db, result.id)
    return _to_out(event).model_dump(mode="json")

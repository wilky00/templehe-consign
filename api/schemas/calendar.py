# ABOUTME: Phase 3 Sprint 4 — request/response shapes for the shared calendar API.
# ABOUTME: 409 conflict body carries `next_available_at` so the UI can offer one-click reschedule.
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class CalendarEventCreate(BaseModel):
    """Body for POST /calendar/events."""

    equipment_record_id: uuid.UUID
    appraiser_id: uuid.UUID
    scheduled_at: datetime
    duration_minutes: int = Field(default=60, ge=15, le=480)
    site_address: str | None = None


class CalendarEventPatch(BaseModel):
    """Body for PATCH /calendar/events/{id}.

    Sparse update — every field optional. ``site_address: None`` clears
    the address; an absent field leaves the existing value untouched.
    """

    model_config = ConfigDict(extra="forbid")

    appraiser_id: uuid.UUID | None = None
    scheduled_at: datetime | None = None
    duration_minutes: int | None = Field(default=None, ge=15, le=480)
    site_address: str | None = None


class CalendarEventCustomer(BaseModel):
    id: uuid.UUID
    name: str | None
    business_name: str | None


class CalendarEventEquipment(BaseModel):
    id: uuid.UUID
    reference_number: str | None
    make: str | None
    model: str | None
    location_text: str | None


class CalendarEventOut(BaseModel):
    id: uuid.UUID
    equipment_record_id: uuid.UUID
    appraiser_id: uuid.UUID
    scheduled_at: datetime
    duration_minutes: int
    site_address: str | None
    cancelled_at: datetime | None
    customer: CalendarEventCustomer | None
    equipment: CalendarEventEquipment | None


class CalendarEventListResponse(BaseModel):
    events: list[CalendarEventOut]
    total: int


class CalendarConflictResponse(BaseModel):
    """Body returned with a 409 from POST / PATCH on conflict."""

    detail: str
    next_available_at: datetime | None
    conflicting_event_id: uuid.UUID | None

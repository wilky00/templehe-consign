# ABOUTME: Phase 5 Sprint 2 — request/response schemas for appraiser-specific endpoints.
# ABOUTME: AppointmentDetail is the iOS dashboard card payload; extended by later sprints.
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel


class AppointmentDetail(BaseModel):
    calendar_event_id: uuid.UUID
    equipment_record_id: uuid.UUID
    reference_number: str | None
    scheduled_at: datetime
    duration_minutes: int
    site_address: str | None
    record_status: str
    customer_make: str | None
    customer_model: str | None
    customer_year: int | None
    # Contact info for the iOS dashboard "Call" actions.
    customer_name: str | None
    customer_phone: str | None
    sales_rep_name: str | None
    sales_rep_phone: str | None
    sales_rep_email: str | None


class AppointmentListResponse(BaseModel):
    appointments: list[AppointmentDetail]
    days_ahead: int

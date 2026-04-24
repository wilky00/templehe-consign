# ABOUTME: Pydantic schemas for customer-initiated change requests.
# ABOUTME: Used by api/routers/equipment.py — POST/GET /change-requests.
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ChangeRequestCreate(BaseModel):
    request_type: str = Field(..., min_length=1, max_length=30)
    customer_notes: str | None = Field(default=None, max_length=5000)


class ChangeRequestOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    equipment_record_id: uuid.UUID
    request_type: str
    customer_notes: str | None = None
    status: str
    submitted_at: datetime
    resolved_at: datetime | None = None

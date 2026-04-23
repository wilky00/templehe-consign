# ABOUTME: Pydantic schemas for customer-side equipment intake + list/detail views.
# ABOUTME: Used by api/routers/equipment.py.
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

_RUNNING_STATUS = frozenset({"running", "partially_running", "not_running"})
_OWNERSHIP_TYPE = frozenset({"owned", "financed", "leased", "unknown"})


class IntakePhotoIn(BaseModel):
    """Photo metadata submitted with an intake.

    The client uploads the blob to R2 via signed URL (Sprint 3) and passes
    the resulting storage_key here. Sprint 2 accepts + persists the
    metadata only; no blob verification yet.
    """

    storage_key: str = Field(..., min_length=1, max_length=255)
    caption: str | None = Field(default=None, max_length=1000)
    display_order: int = Field(default=0, ge=0, le=99)


class IntakeSubmission(BaseModel):
    """Customer intake payload — `POST /me/equipment`.

    Category is optional: customer may not know what their machine is.
    Make/model/year/serial are all optional strings; the appraisal
    submission (Phase 5) carries the verified version.
    """

    category_id: uuid.UUID | None = None
    make: str | None = Field(default=None, max_length=100)
    model: str | None = Field(default=None, max_length=100)
    year: int | None = Field(default=None, ge=1900, le=2100)
    serial_number: str | None = Field(default=None, max_length=100)
    hours: int | None = Field(default=None, ge=0, le=1_000_000)
    running_status: str | None = None
    ownership_type: str | None = None
    location_text: str | None = Field(default=None, max_length=255)
    description: str | None = Field(default=None, max_length=5000)
    photos: list[IntakePhotoIn] = Field(default_factory=list, max_length=20)

    @field_validator("running_status")
    @classmethod
    def _valid_running(cls, v: str | None) -> str | None:
        if v is None:
            return v
        v = v.strip().lower()
        if v not in _RUNNING_STATUS:
            raise ValueError(
                "running_status must be one of: running, partially_running, not_running"
            )
        return v

    @field_validator("ownership_type")
    @classmethod
    def _valid_ownership(cls, v: str | None) -> str | None:
        if v is None:
            return v
        v = v.strip().lower()
        if v not in _OWNERSHIP_TYPE:
            raise ValueError("ownership_type must be one of: owned, financed, leased, unknown")
        return v

    @field_validator("make", "model", "serial_number", "location_text", "description")
    @classmethod
    def _strip_or_null(cls, v: str | None) -> str | None:
        if v is None:
            return v
        v = v.strip()
        return v or None


class IntakePhotoOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    storage_key: str
    caption: str | None = None
    display_order: int
    uploaded_at: datetime


class EquipmentRecordOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    reference_number: str
    status: str
    category_id: uuid.UUID | None = None
    make: str | None = None
    model: str | None = None
    year: int | None = None
    serial_number: str | None = None
    hours: int | None = None
    running_status: str | None = None
    ownership_type: str | None = None
    location_text: str | None = None
    description: str | None = None
    submitted_at: datetime | None = None
    created_at: datetime
    photos: list[IntakePhotoOut] = Field(default_factory=list)

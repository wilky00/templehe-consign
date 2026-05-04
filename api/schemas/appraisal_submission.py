# ABOUTME: Phase 5 Sprint 4 — Pydantic request/response shapes for appraisal submissions.
# ABOUTME: Covers draft create/update, component score upsert, and the submitted-state response.
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field

# --------------------------------------------------------------------------- #
# Inbound
# --------------------------------------------------------------------------- #


class SubmissionCreateRequest(BaseModel):
    equipment_record_id: uuid.UUID


class InspectionAnswerIn(BaseModel):
    prompt_id: uuid.UUID
    prompt_version: int
    value: str | bool | int | float | None = None


class ComponentScoreIn(BaseModel):
    component_id: uuid.UUID
    score: float = Field(ge=0.0, le=5.0)
    notes: str | None = None


class SubmissionUpdateRequest(BaseModel):
    category_id: uuid.UUID | None = None
    make: str | None = Field(default=None, max_length=100)
    model: str | None = Field(default=None, max_length=100)
    year: int | None = Field(default=None, ge=1900, le=2100)
    hours_condition: str | None = None
    running_status: str | None = None
    serial_number: str | None = None
    title_status: str | None = None
    field_values: list[InspectionAnswerIn] | None = None
    component_scores: list[ComponentScoreIn] | None = None
    marketability_rating: str | None = None
    transport_notes: str | None = None
    listing_notes: str | None = None
    comparable_sales_data: list[dict] | None = None
    red_flags: list[dict] | None = None


# --------------------------------------------------------------------------- #
# Outbound
# --------------------------------------------------------------------------- #


class ComponentScoreOut(BaseModel):
    id: uuid.UUID
    component_id: uuid.UUID
    component_name: str
    raw_score: float
    weight_at_time_of_scoring: Decimal
    notes: str | None

    model_config = {"from_attributes": True}


class SubmissionOut(BaseModel):
    id: uuid.UUID
    equipment_record_id: uuid.UUID
    appraiser_id: uuid.UUID | None
    status: str
    category_id: uuid.UUID | None
    category_version: int | None
    make: str | None
    model: str | None
    year: int | None
    hours_condition: str | None
    running_status: str | None
    serial_number: str | None
    title_status: str | None
    overall_score: float | None
    score_band: str | None
    management_review_required: bool
    hold_for_title_review: bool
    review_notes: str | None
    marketability_rating: str | None
    transport_notes: str | None
    listing_notes: str | None
    approved_purchase_offer: Decimal | None
    suggested_consignment_price: Decimal | None
    rejection_notes: str | None
    approved_by_id: uuid.UUID | None
    approved_at: datetime | None
    field_values: list | dict | None
    red_flags: list | None
    comparable_sales_data: list | None
    component_scores: list[ComponentScoreOut]
    submitted_at: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class SubmissionListResponse(BaseModel):
    submissions: list[SubmissionOut]
    total: int

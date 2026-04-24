# ABOUTME: Request/response shapes for the sales rep dashboard, record view, cascade, publish, resolution.
# ABOUTME: The dashboard groups records by customer; individual record view is a richer equipment payload.
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class EquipmentRowOut(BaseModel):
    id: uuid.UUID
    reference_number: str | None
    status: str
    make: str | None
    model: str | None
    year: int | None
    serial_number: str | None
    submitted_at: datetime | None
    assigned_sales_rep_id: uuid.UUID | None
    assigned_appraiser_id: uuid.UUID | None


class CustomerGroupOut(BaseModel):
    customer_id: uuid.UUID
    business_name: str | None
    submitter_name: str
    cell_phone: str | None
    business_phone: str | None
    business_phone_ext: str | None
    state: str | None
    first_submission_at: datetime | None
    total_items: int
    assigned_sales_rep_id: uuid.UUID | None
    records: list[EquipmentRowOut]


class DashboardResponse(BaseModel):
    customers: list[CustomerGroupOut]
    total_customers: int
    total_records: int


class StatusEventSummary(BaseModel):
    from_status: str | None
    to_status: str
    changed_by: uuid.UUID | None
    note: str | None
    created_at: datetime


class ChangeRequestSummary(BaseModel):
    id: uuid.UUID
    request_type: str
    customer_notes: str | None
    status: str
    resolution_notes: str | None
    resolved_by: uuid.UUID | None
    submitted_at: datetime
    resolved_at: datetime | None


class EquipmentDetailOut(BaseModel):
    id: uuid.UUID
    reference_number: str | None
    status: str
    make: str | None
    model: str | None
    year: int | None
    serial_number: str | None
    hours: int | None
    running_status: str | None
    ownership_type: str | None
    location_text: str | None
    description: str | None
    submitted_at: datetime | None
    created_at: datetime
    assigned_sales_rep_id: uuid.UUID | None
    assigned_appraiser_id: uuid.UUID | None
    customer_id: uuid.UUID
    customer_business_name: str | None
    customer_submitter_name: str
    customer_cell_phone: str | None
    customer_business_phone: str | None
    customer_email: str
    has_signed_contract: bool
    has_appraisal_report: bool
    public_listing_status: str | None
    status_history: list[StatusEventSummary]
    change_requests: list[ChangeRequestSummary]


class AssignmentPatch(BaseModel):
    """Partial update. Pass None to clear an assignment, omit to leave unchanged.
    The router + service acquire-lock check happens before the write."""

    assigned_sales_rep_id: uuid.UUID | None = Field(default=None)
    assigned_appraiser_id: uuid.UUID | None = Field(default=None)
    # Sentinel dict of explicitly-set keys so we can distinguish "unset"
    # from "set to null". Pydantic exposes this via ``model_fields_set``
    # on the instance — callers check that before applying.

    model_config = ConfigDict(extra="forbid")


class CascadePatch(BaseModel):
    assigned_sales_rep_id: uuid.UUID | None = Field(default=None)
    assigned_appraiser_id: uuid.UUID | None = Field(default=None)
    model_config = ConfigDict(extra="forbid")


class CascadeResult(BaseModel):
    updated_record_ids: list[uuid.UUID]
    skipped_record_ids: list[uuid.UUID]
    skipped_reason: str | None = None


class ChangeRequestResolve(BaseModel):
    status: Literal["resolved", "rejected"]
    resolution_notes: str | None = Field(default=None, max_length=2000)
    model_config = ConfigDict(extra="forbid")


class ChangeRequestResolveOut(BaseModel):
    id: uuid.UUID
    status: str
    resolution_notes: str | None
    resolved_by: uuid.UUID | None
    resolved_at: datetime | None
    equipment_record_id: uuid.UUID
    equipment_record_status: str


class PublishResponse(BaseModel):
    equipment_record_id: uuid.UUID
    status: str
    public_listing_id: uuid.UUID
    published_at: datetime

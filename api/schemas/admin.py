# ABOUTME: Admin panel request/response shapes — operations dashboard + manual transitions.
# ABOUTME: Dedicated to /admin/* endpoints; keeps Phase 4 surface separate from sales schemas.
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class AdminOperationsRow(BaseModel):
    id: uuid.UUID
    reference_number: str | None
    status: str
    status_display: str
    days_in_status: int
    customer_id: uuid.UUID
    customer_name: str
    business_name: str | None
    state: str | None
    make: str | None
    model: str | None
    year: int | None
    assigned_sales_rep_id: uuid.UUID | None
    assigned_sales_rep_name: str | None
    assigned_appraiser_id: uuid.UUID | None
    assigned_appraiser_name: str | None
    is_overdue: bool
    submitted_at: datetime | None
    updated_at: datetime


class AdminOperationsResponse(BaseModel):
    rows: list[AdminOperationsRow]
    total: int
    page: int
    per_page: int


class ManualTransitionRequest(BaseModel):
    to_status: str = Field(min_length=1, max_length=40)
    reason: str = Field(min_length=1, max_length=2000)
    send_notifications: bool | None = Field(
        default=None,
        description=(
            "When None, dispatch follows the registry defaults for the "
            "destination status. When True/False, both customer + sales-rep "
            "notifications are forced on/off for this transition."
        ),
    )


class ManualTransitionResponse(BaseModel):
    record_id: uuid.UUID
    from_status: str
    to_status: str
    notifications_dispatched: bool
    audit_log_id: uuid.UUID


SortField = Literal[
    "updated_at",
    "submitted_at",
    "days_in_status",
    "customer_name",
    "status",
]
SortDirection = Literal["asc", "desc"]


# --- Customer admin (Sprint 2) --------------------------------------------- #


class AdminCustomerEquipmentSummary(BaseModel):
    id: uuid.UUID
    reference_number: str | None
    status: str
    make: str | None
    model: str | None
    year: int | None
    deleted_at: datetime | None


class AdminCustomerOut(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID | None
    user_email: str | None
    invite_email: str | None
    business_name: str | None
    submitter_name: str
    title: str | None
    address_street: str | None
    address_city: str | None
    address_state: str | None
    address_zip: str | None
    business_phone: str | None
    business_phone_ext: str | None
    cell_phone: str | None
    is_walkin: bool
    is_deleted: bool
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None
    equipment_records: list[AdminCustomerEquipmentSummary] = Field(default_factory=list)


class AdminCustomerListResponse(BaseModel):
    customers: list[AdminCustomerOut]
    total: int
    page: int
    per_page: int


class AdminCustomerCreate(BaseModel):
    """Walk-in customer creation — admin types details for someone who
    hasn't registered. ``invite_email`` is required; the admin can later
    click "Send Portal Invite" to email a registration link."""

    submitter_name: str = Field(min_length=1, max_length=200)
    invite_email: str = Field(min_length=3, max_length=255)
    business_name: str | None = Field(default=None, max_length=200)
    title: str | None = Field(default=None, max_length=100)
    address_street: str | None = Field(default=None, max_length=255)
    address_city: str | None = Field(default=None, max_length=100)
    address_state: str | None = Field(default=None, max_length=2)
    address_zip: str | None = Field(default=None, max_length=10)
    business_phone: str | None = Field(default=None, max_length=20)
    business_phone_ext: str | None = Field(default=None, max_length=10)
    cell_phone: str | None = Field(default=None, max_length=20)


class AdminCustomerPatch(BaseModel):
    submitter_name: str | None = Field(default=None, max_length=200)
    business_name: str | None = Field(default=None, max_length=200)
    title: str | None = Field(default=None, max_length=100)
    address_street: str | None = Field(default=None, max_length=255)
    address_city: str | None = Field(default=None, max_length=100)
    address_state: str | None = Field(default=None, max_length=2)
    address_zip: str | None = Field(default=None, max_length=10)
    business_phone: str | None = Field(default=None, max_length=20)
    business_phone_ext: str | None = Field(default=None, max_length=10)
    cell_phone: str | None = Field(default=None, max_length=20)
    invite_email: str | None = Field(default=None, max_length=255)


class SendInviteResponse(BaseModel):
    customer_id: uuid.UUID
    invite_email: str
    sent_at: datetime


# --- User deactivation (Sprint 2) ------------------------------------------ #


class DeactivateUserRequest(BaseModel):
    reassign_to_id: uuid.UUID | None = Field(
        default=None,
        description=(
            "Required when the user has open equipment records or future "
            "calendar events. Must be an active user with an overlapping "
            "role (sales rep replacement → another sales rep; appraiser → "
            "another appraiser)."
        ),
    )


class DeactivateUserOpenWork(BaseModel):
    """409 payload when admin tries to deactivate a user with open
    work but didn't pick a reassignment target. Lists the impacted
    counts so the SPA modal can show "this user has N records assigned"
    before asking for the new assignee."""

    detail: str
    open_record_count: int
    future_event_count: int


class DeactivateUserResponse(BaseModel):
    user_id: uuid.UUID
    reassigned_records: list[uuid.UUID] = Field(default_factory=list)
    reassigned_events: list[uuid.UUID] = Field(default_factory=list)
    new_status: str

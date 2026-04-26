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

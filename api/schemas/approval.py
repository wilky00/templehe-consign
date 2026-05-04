# ABOUTME: Phase 6 Sprint 2 — request/response schemas for the manager approval workflow.
# ABOUTME: Queue items are lightweight; detail view reuses SubmissionOut from appraisal_submission.
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel


class ApprovalQueueItemOut(BaseModel):
    submission_id: uuid.UUID
    equipment_record_id: uuid.UUID
    reference_number: str | None
    make: str | None
    model: str | None
    year: int | None
    overall_score: Decimal | None
    score_band: str | None
    marketability_rating: str | None
    appraiser_name: str | None
    submitted_at: datetime | None
    management_review_required: bool
    hold_for_title_review: bool
    red_flags: list | None


class ApprovalQueueResponse(BaseModel):
    items: list[ApprovalQueueItemOut]
    total: int


class ApprovalDecisionRequest(BaseModel):
    purchase_offer: Decimal
    consignment_price: Decimal
    notes: str | None = None
    title_review_confirmed: bool = False


class RejectionDecisionRequest(BaseModel):
    rejection_notes: str
    send_back: bool = False

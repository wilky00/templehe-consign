# ABOUTME: Phase 6 Sprint 2 — manager approval queue endpoints.
# ABOUTME: Restricted to sales_manager and admin roles; surfaces submitted appraisals for review.
from __future__ import annotations

import uuid

import structlog
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from database.base import get_db
from database.models import User
from middleware.rbac import require_roles
from schemas.approval import (
    ApprovalDecisionRequest,
    ApprovalQueueItemOut,
    ApprovalQueueResponse,
    RejectionDecisionRequest,
)
from schemas.appraisal_submission import SubmissionOut
from services import approval_service

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/manager/approvals", tags=["manager"])

_require_manager = require_roles("sales_manager", "admin")


def _queue_item_to_out(item: dict) -> ApprovalQueueItemOut:
    return ApprovalQueueItemOut(**item)


def _submission_to_out(submission) -> SubmissionOut:
    component_scores = [
        {
            "id": cs.id,
            "component_id": cs.category_component_id,
            "component_name": cs.component.name if cs.component else "",
            "raw_score": cs.raw_score,
            "weight_at_time_of_scoring": cs.weight_at_time_of_scoring,
            "notes": cs.notes,
        }
        for cs in submission.component_scores
    ]
    return SubmissionOut(
        id=submission.id,
        equipment_record_id=submission.equipment_record_id,
        appraiser_id=submission.appraiser_id,
        status=submission.status,
        category_id=submission.category_id,
        category_version=submission.category_version,
        make=submission.make,
        model=submission.model,
        year=submission.year,
        hours_condition=submission.hours_condition,
        running_status=submission.running_status,
        serial_number=submission.serial_number,
        title_status=submission.title_status,
        overall_score=submission.overall_score,
        score_band=submission.score_band,
        management_review_required=submission.management_review_required,
        hold_for_title_review=submission.hold_for_title_review,
        review_notes=submission.review_notes,
        marketability_rating=submission.marketability_rating,
        transport_notes=submission.transport_notes,
        listing_notes=submission.listing_notes,
        approved_purchase_offer=submission.approved_purchase_offer,
        suggested_consignment_price=submission.suggested_consignment_price,
        rejection_notes=submission.rejection_notes,
        approved_by_id=submission.approved_by_id,
        approved_at=submission.approved_at,
        field_values=submission.field_values,
        red_flags=submission.red_flags,
        comparable_sales_data=submission.comparable_sales_data,
        component_scores=component_scores,
        submitted_at=submission.submitted_at,
        created_at=submission.created_at,
        updated_at=submission.updated_at,
    )


@router.get("", response_model=ApprovalQueueResponse)
async def get_approval_queue(
    current_user: User = Depends(_require_manager),
    db: AsyncSession = Depends(get_db),
) -> ApprovalQueueResponse:
    """List all appraisal submissions awaiting manager approval, oldest first."""
    items = await approval_service.get_queue(db)
    return ApprovalQueueResponse(
        items=[_queue_item_to_out(item) for item in items],
        total=len(items),
    )


@router.get("/{submission_id}", response_model=SubmissionOut)
async def get_approval_detail(
    submission_id: uuid.UUID,
    current_user: User = Depends(_require_manager),
    db: AsyncSession = Depends(get_db),
) -> SubmissionOut:
    """Return the full submission detail for a manager review."""
    try:
        submission = await approval_service._fetch(db, submission_id=submission_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _submission_to_out(submission)


@router.post("/{submission_id}/approve", response_model=SubmissionOut)
async def approve_submission(
    submission_id: uuid.UUID,
    body: ApprovalDecisionRequest,
    current_user: User = Depends(_require_manager),
    db: AsyncSession = Depends(get_db),
) -> SubmissionOut:
    """Approve a submitted appraisal.

    Sets the purchase offer and consignment price, advances the equipment
    record to approved_pending_esign, and notifies the assigned sales rep.
    If hold_for_title_review is set on the submission, title_review_confirmed
    must be true or the request is rejected with 422.
    """
    try:
        submission = await approval_service.approve(
            db,
            submission_id=submission_id,
            approving_user=current_user,
            purchase_offer=body.purchase_offer,
            consignment_price=body.consignment_price,
            notes=body.notes,
            title_review_confirmed=body.title_review_confirmed,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _submission_to_out(submission)


@router.post("/{submission_id}/reject", response_model=SubmissionOut)
async def reject_submission(
    submission_id: uuid.UUID,
    body: RejectionDecisionRequest,
    current_user: User = Depends(_require_manager),
    db: AsyncSession = Depends(get_db),
) -> SubmissionOut:
    """Reject a submitted appraisal.

    If send_back is true, the equipment record returns to new_request and
    the appraiser is notified to re-inspect. If false, the record moves to
    declined (terminal). The assigned sales rep is notified in both cases.
    """
    try:
        submission = await approval_service.reject(
            db,
            submission_id=submission_id,
            rejecting_user=current_user,
            rejection_notes=body.rejection_notes,
            send_back=body.send_back,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _submission_to_out(submission)

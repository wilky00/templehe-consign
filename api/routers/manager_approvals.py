# ABOUTME: Phase 6 Sprint 2 — manager approval queue endpoints.
# ABOUTME: Restricted to sales_manager and admin roles; surfaces submitted appraisals for review.
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from database.base import AsyncSessionLocal, get_db
from database.models import (
    AppraisalSubmission,
    ChangeRequest,
    Customer,
    EquipmentRecord,
    User,
)
from middleware.rbac import require_roles
from schemas.appraisal_submission import SubmissionOut
from schemas.approval import (
    ApprovalDecisionRequest,
    ApprovalQueueItemOut,
    ApprovalQueueResponse,
    RejectionDecisionRequest,
)
from services import approval_service, pdf_generation_worker

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/manager/approvals", tags=["manager"])


async def _pdf_background(submission_id: uuid.UUID, actor_id: uuid.UUID) -> None:
    """Run PDF generation in its own DB session — called as a FastAPI BackgroundTask."""
    async with AsyncSessionLocal() as db:
        try:
            await pdf_generation_worker.generate_and_store_best_effort(
                db, submission_id=submission_id, actor_id=actor_id
            )
            await db.commit()
        except Exception:
            await db.rollback()
            logger.exception("pdf_background_task_failed", submission_id=str(submission_id))

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


class PriceChangeQueueItemOut(BaseModel):
    change_request_id: uuid.UUID
    equipment_record_id: uuid.UUID
    reference_number: str | None
    make_model: str | None
    approved_price: Decimal | None
    proposed_price: Decimal | None
    submitted_at: datetime | None
    customer_email: str | None


class PriceChangeQueueResponse(BaseModel):
    items: list[PriceChangeQueueItemOut]
    total: int


class PriceChangeApprovalOut(BaseModel):
    change_request_id: uuid.UUID
    status: str
    resolved_at: datetime | None
    new_consignment_price: float | None


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


@router.get("/price-changes", response_model=PriceChangeQueueResponse)
async def get_price_change_queue(
    current_user: User = Depends(_require_manager),
    db: AsyncSession = Depends(get_db),
) -> PriceChangeQueueResponse:
    """List pending change requests that require manager re-approval due to price threshold."""
    result = await db.execute(
        select(ChangeRequest)
        .where(
            ChangeRequest.requires_manager_reapproval.is_(True),
            ChangeRequest.status == "pending",
        )
        .options(
            selectinload(ChangeRequest.equipment_record)
            .selectinload(EquipmentRecord.customer)
            .selectinload(Customer.user)
        )
        .order_by(ChangeRequest.submitted_at.asc())
    )
    changes = list(result.scalars().all())

    items: list[PriceChangeQueueItemOut] = []
    for change in changes:
        record = change.equipment_record
        customer_user = record.customer.user if (record and record.customer) else None

        sub_result = await db.execute(
            select(AppraisalSubmission).where(
                AppraisalSubmission.equipment_record_id == change.equipment_record_id,
                AppraisalSubmission.status == "approved",
            )
        )
        sub = sub_result.scalar_one_or_none()

        make_model = None
        if sub:
            parts = [sub.make, sub.model]
            make_model = " ".join(p for p in parts if p) or None

        items.append(
            PriceChangeQueueItemOut(
                change_request_id=change.id,
                equipment_record_id=change.equipment_record_id,
                reference_number=record.reference_number if record else None,
                make_model=make_model,
                approved_price=sub.suggested_consignment_price if sub else None,
                proposed_price=change.proposed_consignment_price,
                submitted_at=change.submitted_at,
                customer_email=customer_user.email if customer_user else None,
            )
        )

    return PriceChangeQueueResponse(items=items, total=len(items))


@router.post(
    "/price-changes/{change_request_id}/approve",
    response_model=PriceChangeApprovalOut,
)
async def approve_price_change(
    change_request_id: uuid.UUID,
    current_user: User = Depends(_require_manager),
    db: AsyncSession = Depends(get_db),
) -> PriceChangeApprovalOut:
    """Re-approve a price change that exceeded the manager-approval threshold.

    Resolves the ChangeRequest, updates the submission's consignment price to
    the proposed price, and writes an audit log entry.
    """
    try:
        change = await approval_service.approve_price_change(
            db,
            change_request_id=change_request_id,
            approving_user=current_user,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return PriceChangeApprovalOut(
        change_request_id=change.id,
        status=change.status,
        resolved_at=change.resolved_at,
        new_consignment_price=change.proposed_consignment_price,
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
    background_tasks: BackgroundTasks,
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

    background_tasks.add_task(_pdf_background, submission_id, current_user.id)

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

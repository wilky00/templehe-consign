# ABOUTME: Phase 5 Sprint 4 — appraisal submission CRUD + submit endpoints.
# ABOUTME: Appraiser-scoped; admin can read all. Draft lifecycle: create → update* → submit.
from __future__ import annotations

import uuid

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from database.base import get_db
from database.models import User
from middleware.rbac import require_roles
from schemas.appraisal_submission import (
    SubmissionCreateRequest,
    SubmissionListResponse,
    SubmissionOut,
    SubmissionUpdateRequest,
)
from services import appraisal_submission_service

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/appraisal-submissions", tags=["mobile"])

_require_appraiser = require_roles("appraiser", "admin")


def _submission_to_out(submission) -> SubmissionOut:
    """Map an ORM submission to the response schema."""
    component_scores = []
    for cs in submission.component_scores:
        component_scores.append(
            {
                "id": cs.id,
                "component_id": cs.category_component_id,
                "component_name": cs.component.name if cs.component else "",
                "raw_score": cs.raw_score,
                "weight_at_time_of_scoring": cs.weight_at_time_of_scoring,
                "notes": cs.notes,
            }
        )
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
        marketability_rating=submission.marketability_rating,
        transport_notes=submission.transport_notes,
        listing_notes=submission.listing_notes,
        field_values=submission.field_values,
        red_flags=submission.red_flags,
        comparable_sales_data=submission.comparable_sales_data,
        component_scores=component_scores,
        submitted_at=submission.submitted_at,
        created_at=submission.created_at,
        updated_at=submission.updated_at,
    )


@router.post("", response_model=SubmissionOut, status_code=201)
async def create_draft(
    body: SubmissionCreateRequest,
    current_user: User = Depends(_require_appraiser),
    db: AsyncSession = Depends(get_db),
) -> SubmissionOut:
    """Create a new draft submission for an equipment record.

    Returns 409 if a draft already exists for the record."""
    try:
        submission = await appraisal_submission_service.create_draft(
            db,
            equipment_record_id=body.equipment_record_id,
            appraiser=current_user,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await db.refresh(submission, attribute_names=["component_scores"])
    return _submission_to_out(submission)


@router.get("", response_model=SubmissionListResponse)
async def list_submissions(
    status: str | None = Query(default=None),
    current_user: User = Depends(_require_appraiser),
    db: AsyncSession = Depends(get_db),
) -> SubmissionListResponse:
    """List the current appraiser's own submissions, newest first."""
    try:
        submissions = await appraisal_submission_service.list_mine(
            db, appraiser=current_user, status_filter=status
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return SubmissionListResponse(
        submissions=[_submission_to_out(s) for s in submissions],
        total=len(submissions),
    )


@router.get("/{submission_id}", response_model=SubmissionOut)
async def get_submission(
    submission_id: uuid.UUID,
    current_user: User = Depends(_require_appraiser),
    db: AsyncSession = Depends(get_db),
) -> SubmissionOut:
    try:
        submission = await appraisal_submission_service.get(
            db, submission_id=submission_id, user=current_user
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return _submission_to_out(submission)


@router.patch("/{submission_id}", response_model=SubmissionOut)
async def update_submission(
    submission_id: uuid.UUID,
    body: SubmissionUpdateRequest,
    current_user: User = Depends(_require_appraiser),
    db: AsyncSession = Depends(get_db),
) -> SubmissionOut:
    """Update draft fields. Recalculates overall score when component_scores is provided."""
    try:
        submission = await appraisal_submission_service.update_draft(
            db, submission_id=submission_id, body=body, user=current_user
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _submission_to_out(submission)


@router.post("/{submission_id}/submit", response_model=SubmissionOut)
async def submit_submission(
    submission_id: uuid.UUID,
    current_user: User = Depends(_require_appraiser),
    db: AsyncSession = Depends(get_db),
) -> SubmissionOut:
    """Transition a draft to submitted status with a version snapshot."""
    try:
        submission = await appraisal_submission_service.submit(
            db, submission_id=submission_id, appraiser=current_user
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _submission_to_out(submission)

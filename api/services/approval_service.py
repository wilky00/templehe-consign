# ABOUTME: Phase 6 Sprint 2 — manager approval workflow for appraisal submissions.
# ABOUTME: Provides queue listing, approve, and reject operations for sales_manager/admin roles.
"""Manager approval workflow.

Public surface:

- :func:`get_queue` — list all submissions awaiting manager review.
- :func:`approve` — approve a submission, populate pricing, advance record status.
- :func:`reject` — reject a submission; optionally send back for re-appraisal.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

import structlog
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from database.models import (
    AppraisalSubmission,
    AuditLog,
    ChangeRequest,
    ComponentScore,
    EquipmentRecord,
    User,
)
from services import (
    equipment_status_service,
    esign_service,
    notification_service,
    user_roles_service,
)
from services.equipment_status_machine import Status

logger = structlog.get_logger(__name__)


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #


async def get_queue(db: AsyncSession) -> list[dict]:
    """Return all submissions currently awaiting manager approval, oldest first."""
    stmt = text("""
        SELECT
            s.id              AS submission_id,
            er.id             AS equipment_record_id,
            er.reference_number,
            s.make,
            s.model,
            s.year,
            s.overall_score,
            s.score_band,
            s.marketability_rating,
            s.management_review_required,
            s.hold_for_title_review,
            s.red_flags,
            s.submitted_at,
            u.first_name,
            u.last_name
        FROM equipment_records er
        JOIN appraisal_submissions s ON (
            s.equipment_record_id = er.id
            AND s.status = 'submitted'
            AND s.deleted_at IS NULL
        )
        LEFT JOIN users u ON u.id = s.appraiser_id
        WHERE er.status = :status
          AND er.deleted_at IS NULL
        ORDER BY s.submitted_at ASC
    """)
    result = await db.execute(stmt, {"status": Status.APPRAISAL_COMPLETE.value})
    rows = result.mappings().all()
    return [
        {
            "submission_id": row["submission_id"],
            "equipment_record_id": row["equipment_record_id"],
            "reference_number": row["reference_number"],
            "make": row["make"],
            "model": row["model"],
            "year": row["year"],
            "overall_score": row["overall_score"],
            "score_band": row["score_band"],
            "marketability_rating": row["marketability_rating"],
            "appraiser_name": (
                f"{row['first_name']} {row['last_name']}" if row["first_name"] is not None else None
            ),
            "submitted_at": row["submitted_at"],
            "management_review_required": row["management_review_required"],
            "hold_for_title_review": row["hold_for_title_review"],
            "red_flags": row["red_flags"],
        }
        for row in rows
    ]


async def approve(
    db: AsyncSession,
    *,
    submission_id: uuid.UUID,
    approving_user: User,
    purchase_offer: Decimal,
    consignment_price: Decimal,
    notes: str | None = None,
    title_review_confirmed: bool = False,
) -> AppraisalSubmission:
    """Approve a submitted appraisal.

    Sets pricing fields, transitions AppraisalSubmission → approved and
    EquipmentRecord → approved_pending_esign. Writes an audit log entry.

    Raises :exc:`LookupError` if the submission is not found.
    Raises :exc:`ValueError` if the submission is not in 'submitted' status,
    or if title hold is present and ``title_review_confirmed`` is false.
    """
    result = await db.execute(
        select(AppraisalSubmission)
        .where(
            AppraisalSubmission.id == submission_id,
            AppraisalSubmission.deleted_at.is_(None),
        )
        .with_for_update()
    )
    submission = result.scalar_one_or_none()
    if submission is None:
        raise LookupError(f"Submission {submission_id} not found")
    if submission.status != "submitted":
        raise ValueError(f"Cannot approve: submission status is '{submission.status}'")
    if submission.hold_for_title_review and not title_review_confirmed:
        raise ValueError(
            "This submission has a title hold — set title_review_confirmed to true to proceed."
        )

    record = await db.get(EquipmentRecord, submission.equipment_record_id)
    if record is None:
        raise LookupError(f"Equipment record for submission {submission_id} not found")

    before = {"submission_status": submission.status, "record_status": record.status}

    submission.approved_purchase_offer = purchase_offer
    submission.suggested_consignment_price = consignment_price
    if notes:
        prior = submission.review_notes or ""
        submission.review_notes = f"{prior}\n{notes}".strip() if prior else notes
    submission.approved_by_id = approving_user.id
    submission.approved_at = datetime.now(UTC)
    submission.status = "approved"
    await db.flush()

    # record_transition also fires the sales_rep_approved_pending_esign notification
    await equipment_status_service.record_transition(
        db,
        record=record,
        to_status=Status.APPROVED_PENDING_ESIGN.value,
        changed_by=approving_user,
    )

    actor_role = await _resolve_actor_role(db, approving_user)
    db.add(
        AuditLog(
            event_type="appraisal_submission.approved",
            actor_id=approving_user.id,
            actor_role=actor_role,
            target_type="appraisal_submission",
            target_id=submission.id,
            before_state=before,
            after_state={
                "submission_status": "approved",
                "record_status": Status.APPROVED_PENDING_ESIGN.value,
                "approved_purchase_offer": str(purchase_offer),
                "suggested_consignment_price": str(consignment_price),
            },
        )
    )
    await db.flush()

    logger.info(
        "appraisal_approved",
        submission_id=str(submission_id),
        approving_user_id=str(approving_user.id),
    )

    # Dispatch eSign contract — best-effort; failures are logged but don't
    # roll back the approval so the record isn't left in a broken state.
    try:
        await esign_service.dispatch_contract(db, equipment_record=record)
    except Exception:
        logger.exception("esign_dispatch_failed", record_id=str(record.id))

    return await _fetch(db, submission_id=submission_id)


async def reject(
    db: AsyncSession,
    *,
    submission_id: uuid.UUID,
    rejecting_user: User,
    rejection_notes: str,
    send_back: bool = False,
) -> AppraisalSubmission:
    """Reject a submitted appraisal.

    If ``send_back`` is true, the equipment record returns to 'new_request'
    and the appraiser receives a notification. Otherwise the record moves to
    'declined' (terminal). Either way, the assigned sales rep is notified.

    Raises :exc:`LookupError` if the submission is not found.
    Raises :exc:`ValueError` if the submission is not in 'submitted' status.
    """
    result = await db.execute(
        select(AppraisalSubmission)
        .where(
            AppraisalSubmission.id == submission_id,
            AppraisalSubmission.deleted_at.is_(None),
        )
        .with_for_update()
    )
    submission = result.scalar_one_or_none()
    if submission is None:
        raise LookupError(f"Submission {submission_id} not found")
    if submission.status != "submitted":
        raise ValueError(f"Cannot reject: submission status is '{submission.status}'")

    record = await db.get(EquipmentRecord, submission.equipment_record_id)
    if record is None:
        raise LookupError(f"Equipment record for submission {submission_id} not found")

    before = {"submission_status": submission.status, "record_status": record.status}

    submission.rejection_notes = rejection_notes
    submission.status = "rejected"
    await db.flush()

    new_record_status = Status.NEW_REQUEST.value if send_back else Status.DECLINED.value
    await equipment_status_service.record_transition(
        db,
        record=record,
        to_status=new_record_status,
        changed_by=rejecting_user,
        note=rejection_notes,
    )

    ref = record.reference_number or str(record.id)
    make = submission.make or "Unknown"
    model = submission.model or "equipment"
    payload = {
        "reference_number": ref,
        "make": make,
        "model": model,
        "rejection_notes": rejection_notes,
        "send_back": send_back,
    }

    if send_back and submission.appraiser_id is not None:
        await notification_service.enqueue(
            db,
            idempotency_key=f"rejection-appraiser-{submission_id}",
            user_id=submission.appraiser_id,
            channel="email",
            template="appraisal_rejected_appraiser_email",
            payload=payload,
        )

    if record.assigned_sales_rep_id is not None:
        await notification_service.enqueue(
            db,
            idempotency_key=f"rejection-sales-rep-{submission_id}",
            user_id=record.assigned_sales_rep_id,
            channel="email",
            template="appraisal_rejected_sales_rep_email",
            payload=payload,
        )

    actor_role = await _resolve_actor_role(db, rejecting_user)
    db.add(
        AuditLog(
            event_type="appraisal_submission.rejected",
            actor_id=rejecting_user.id,
            actor_role=actor_role,
            target_type="appraisal_submission",
            target_id=submission.id,
            before_state=before,
            after_state={
                "submission_status": "rejected",
                "record_status": new_record_status,
                "rejection_notes": rejection_notes,
                "send_back": send_back,
            },
        )
    )
    await db.flush()

    logger.info(
        "appraisal_rejected",
        submission_id=str(submission_id),
        rejecting_user_id=str(rejecting_user.id),
        send_back=send_back,
    )

    return await _fetch(db, submission_id=submission_id)


async def approve_price_change(
    db: AsyncSession,
    *,
    change_request_id: uuid.UUID,
    approving_user: User,
) -> ChangeRequest:
    """Approve a manager-required price change re-approval.

    Resolves the ChangeRequest, clears the re-approval flag, updates the
    associated AppraisalSubmission's suggested_consignment_price to the
    proposed price, and writes an audit log entry.

    Raises :exc:`LookupError` if the change request is not found.
    Raises :exc:`ValueError` if the change request is not pending or does not
    have ``requires_manager_reapproval`` set.
    """
    result = await db.execute(
        select(ChangeRequest).where(ChangeRequest.id == change_request_id).with_for_update()
    )
    change = result.scalar_one_or_none()
    if change is None:
        raise LookupError(f"Change request {change_request_id} not found")
    if change.status != "pending":
        raise ValueError(f"Cannot re-approve: change request status is '{change.status}'")
    if not change.requires_manager_reapproval:
        raise ValueError("This change request does not require manager re-approval.")

    sub_result = await db.execute(
        select(AppraisalSubmission).where(
            AppraisalSubmission.equipment_record_id == change.equipment_record_id,
            AppraisalSubmission.status == "approved",
            AppraisalSubmission.deleted_at.is_(None),
        )
    )
    submission = sub_result.scalar_one_or_none()

    before = {
        "change_status": change.status,
        "approved_price": str(submission.suggested_consignment_price) if submission else None,
    }

    change.status = "resolved"
    change.resolved_by = approving_user.id
    change.resolved_at = datetime.now(UTC)
    change.requires_manager_reapproval = False
    if change.proposed_consignment_price is not None:
        change.resolution_notes = (
            f"Manager re-approved price change to ${change.proposed_consignment_price}"
        )
        if submission is not None:
            submission.suggested_consignment_price = change.proposed_consignment_price

    await db.flush()

    actor_role = await _resolve_actor_role(db, approving_user)
    db.add(
        AuditLog(
            event_type="change_request.price_reapproved",
            actor_id=approving_user.id,
            actor_role=actor_role,
            target_type="change_request",
            target_id=change.id,
            before_state=before,
            after_state={
                "change_status": "resolved",
                "new_price": (
                    str(change.proposed_consignment_price)
                    if change.proposed_consignment_price
                    else None
                ),
            },
        )
    )
    await db.flush()

    logger.info(
        "price_change_reapproved",
        change_request_id=str(change_request_id),
        approving_user_id=str(approving_user.id),
    )

    return change


# --------------------------------------------------------------------------- #
# Private helpers
# --------------------------------------------------------------------------- #


async def _fetch(db: AsyncSession, *, submission_id: uuid.UUID) -> AppraisalSubmission:
    result = await db.execute(
        select(AppraisalSubmission)
        .options(
            selectinload(AppraisalSubmission.component_scores).selectinload(
                ComponentScore.component
            )
        )
        .where(
            AppraisalSubmission.id == submission_id,
            AppraisalSubmission.deleted_at.is_(None),
        )
    )
    submission = result.scalar_one_or_none()
    if submission is None:
        raise LookupError(f"Submission {submission_id} not found")
    return submission


async def _resolve_actor_role(db: AsyncSession, user: User) -> str:
    roles = await user_roles_service.role_slugs_for_user(db, user=user)
    if "admin" in roles:
        return "admin"
    if "sales_manager" in roles:
        return "sales_manager"
    return "unknown"

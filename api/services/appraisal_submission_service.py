# ABOUTME: Phase 5 Sprint 4 — create/update/submit appraisal submission drafts.
# ABOUTME: Version snapshot at submit uses SELECT FOR UPDATE to prevent concurrent supersede races.
"""Appraisal submission service — draft lifecycle + version-snapshot submit.

Public surface:

- :func:`create_draft` — start a new draft for an equipment record.
- :func:`update_draft` — update scalar fields, inspection answers, and/or
  component scores; recalculates overall score on every score change.
- :func:`get` — fetch a single submission with RBAC (appraiser sees own;
  admin sees all).
- :func:`list_mine` — list an appraiser's own submissions, ordered newest
  first.
- :func:`submit` — transition draft → submitted with a version snapshot
  captured inside a SELECT FOR UPDATE transaction.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from database.models import (
    AppraisalPhoto,
    AppraisalSubmission,
    CategoryComponent,
    CategoryInspectionPrompt,
    CategoryPhotoSlot,
    CategoryRedFlagRule,
    ComponentScore,
    Customer,
    EquipmentCategory,
    EquipmentRecord,
    NotificationPreference,
    Role,
    User,
)
from schemas.appraisal_submission import ComponentScoreIn, SubmissionUpdateRequest
from services import (
    equipment_status_service,
    notification_service,
    red_flag_service,
    scoring_service,
    user_roles_service,
)
from services.equipment_status_machine import Status

logger = structlog.get_logger(__name__)

_VALID_STATUSES = frozenset({"draft", "submitted", "under_review", "approved", "rejected"})


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #


async def create_draft(
    db: AsyncSession,
    *,
    equipment_record_id: uuid.UUID,
    appraiser: User,
) -> AppraisalSubmission:
    """Create a new draft.

    Raises :exc:`ValueError` if a draft already exists for the record.
    The partial unique index in the DB is the last line of defence, but
    checking here gives a clean 409-able error instead of a 500.
    """
    existing = await db.execute(
        select(AppraisalSubmission).where(
            AppraisalSubmission.equipment_record_id == equipment_record_id,
            AppraisalSubmission.status == "draft",
            AppraisalSubmission.deleted_at.is_(None),
        )
    )
    if existing.scalar_one_or_none():
        raise ValueError("A draft already exists for this equipment record")

    submission = AppraisalSubmission(
        equipment_record_id=equipment_record_id,
        appraiser_id=appraiser.id,
        status="draft",
    )
    db.add(submission)
    await db.flush()
    logger.info(
        "appraisal_draft_created",
        submission_id=str(submission.id),
        appraiser_id=str(appraiser.id),
    )
    return submission


async def update_draft(
    db: AsyncSession,
    *,
    submission_id: uuid.UUID,
    body: SubmissionUpdateRequest,
    user: User,
) -> AppraisalSubmission:
    """Update a draft in place.

    Only drafts can be updated — raises :exc:`ValueError` for any other
    status. Recalculates overall score whenever ``component_scores`` is
    present in the payload.
    """
    submission = await _get_for_write(db, submission_id=submission_id, user=user)
    if submission.status != "draft":
        raise ValueError(f"Only drafts can be updated; status is '{submission.status}'")

    _apply_scalar_fields(submission, body)

    if body.field_values is not None:
        submission.field_values = [a.model_dump() for a in body.field_values]

    if body.component_scores is not None:
        await _upsert_component_scores(db, submission=submission, scores=body.component_scores)
        await db.flush()
        # Reload the scores relationship so the scoring call has fresh data
        await db.refresh(submission, attribute_names=["component_scores"])
        result = scoring_service.calculate_overall(
            {
                str(cs.category_component_id): (
                    float(cs.raw_score),
                    float(cs.weight_at_time_of_scoring),
                )
                for cs in submission.component_scores
            }
        )
        submission.overall_score = result.overall
        submission.score_band = result.band

    await db.flush()
    return await _fetch(db, submission_id=submission_id)


async def get(
    db: AsyncSession,
    *,
    submission_id: uuid.UUID,
    user: User,
) -> AppraisalSubmission:
    submission = await _fetch(db, submission_id=submission_id)
    await _check_access(db, submission=submission, user=user)
    return submission


async def list_mine(
    db: AsyncSession,
    *,
    appraiser: User,
    status_filter: str | None = None,
) -> list[AppraisalSubmission]:
    stmt = (
        select(AppraisalSubmission)
        .options(
            selectinload(AppraisalSubmission.component_scores).selectinload(
                ComponentScore.component
            )
        )
        .where(
            AppraisalSubmission.appraiser_id == appraiser.id,
            AppraisalSubmission.deleted_at.is_(None),
        )
    )
    if status_filter:
        if status_filter not in _VALID_STATUSES:
            raise ValueError(f"Invalid status filter: {status_filter!r}")
        stmt = stmt.where(AppraisalSubmission.status == status_filter)
    result = await db.execute(stmt.order_by(AppraisalSubmission.created_at.desc()))
    return list(result.scalars().all())


async def submit(
    db: AsyncSession,
    *,
    submission_id: uuid.UUID,
    appraiser: User,
) -> AppraisalSubmission:
    """Transition draft → submitted with a version snapshot.

    Locks the submission row with SELECT FOR UPDATE so that an admin
    supersede landing mid-transaction reads consistently — the snapshot
    reflects whichever version was current when the lock was acquired.
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

    await _check_access(db, submission=submission, user=appraiser)

    if submission.status != "draft":
        raise ValueError(f"Cannot submit: status is '{submission.status}', expected 'draft'")

    if submission.category_id:
        await _snapshot_versions(db, submission=submission)
        await _validate_required_photos(db, submission=submission)

    # Server-side red flag evaluation — runs regardless of iOS client flags.
    red_flags = await red_flag_service.evaluate(db, submission)
    submission.management_review_required = red_flags.management_review_required
    submission.hold_for_title_review = red_flags.hold_for_title_review
    if red_flags.marketability_rating is not None:
        submission.marketability_rating = red_flags.marketability_rating
    if red_flags.review_notes is not None:
        submission.review_notes = red_flags.review_notes

    submission.status = "submitted"
    submission.submitted_at = datetime.now(UTC)
    await db.flush()

    # Transition the equipment record so it appears in the manager approval queue.
    record = await db.get(EquipmentRecord, submission.equipment_record_id)
    if record is not None:
        customer_user: User | None = None
        customer = await db.get(Customer, record.customer_id)
        if customer is not None and customer.user_id is not None:
            customer_user = await db.get(User, customer.user_id)
        await equipment_status_service.record_transition(
            db,
            record=record,
            to_status=Status.APPRAISAL_COMPLETE.value,
            changed_by=appraiser,
            customer=customer_user,
        )

    logger.info(
        "appraisal_submitted",
        submission_id=str(submission_id),
        appraiser_id=str(appraiser.id),
        management_review_required=red_flags.management_review_required,
    )

    if red_flags.management_review_required:
        await _notify_managers_review_required(db, submission=submission)

    return await _fetch(db, submission_id=submission_id)


# --------------------------------------------------------------------------- #
# Private helpers
# --------------------------------------------------------------------------- #


def _apply_scalar_fields(submission: AppraisalSubmission, body: SubmissionUpdateRequest) -> None:
    scalar_fields = (
        "category_id",
        "make",
        "model",
        "year",
        "hours_condition",
        "running_status",
        "serial_number",
        "title_status",
        "marketability_rating",
        "transport_notes",
        "listing_notes",
        "comparable_sales_data",
        "red_flags",
    )
    for field in scalar_fields:
        value = getattr(body, field, None)
        if value is not None:
            setattr(submission, field, value)


async def _upsert_component_scores(
    db: AsyncSession,
    *,
    submission: AppraisalSubmission,
    scores: list[ComponentScoreIn],
) -> None:
    component_ids = [s.component_id for s in scores]
    comp_result = await db.execute(
        select(CategoryComponent).where(CategoryComponent.id.in_(component_ids))
    )
    components_by_id = {c.id: c for c in comp_result.scalars().all()}

    existing_result = await db.execute(
        select(ComponentScore).where(ComponentScore.appraisal_submission_id == submission.id)
    )
    existing_by_component = {cs.category_component_id: cs for cs in existing_result.scalars().all()}

    for score_in in scores:
        component = components_by_id.get(score_in.component_id)
        if component is None:
            continue
        if score_in.component_id in existing_by_component:
            cs = existing_by_component[score_in.component_id]
            cs.raw_score = score_in.score
            cs.weight_at_time_of_scoring = component.weight_pct
            cs.notes = score_in.notes
        else:
            db.add(
                ComponentScore(
                    appraisal_submission_id=submission.id,
                    category_component_id=score_in.component_id,
                    raw_score=score_in.score,
                    weight_at_time_of_scoring=component.weight_pct,
                    notes=score_in.notes,
                )
            )


async def _snapshot_versions(
    db: AsyncSession,
    *,
    submission: AppraisalSubmission,
) -> None:
    """Capture category + prompt + rule versions inside the current transaction."""
    category = await db.get(EquipmentCategory, submission.category_id)
    submission.category_version = category.version if category else None

    prompts_result = await db.execute(
        select(CategoryInspectionPrompt).where(
            CategoryInspectionPrompt.category_id == submission.category_id,
            CategoryInspectionPrompt.replaced_at.is_(None),
        )
    )
    submission.prompt_version_set = {str(p.id): p.version for p in prompts_result.scalars().all()}

    rules_result = await db.execute(
        select(CategoryRedFlagRule).where(
            CategoryRedFlagRule.category_id == submission.category_id,
            CategoryRedFlagRule.replaced_at.is_(None),
        )
    )
    submission.rule_version_set = {str(r.id): r.version for r in rules_result.scalars().all()}


async def _validate_required_photos(
    db: AsyncSession,
    *,
    submission: AppraisalSubmission,
) -> None:
    """Raise ValueError if any required CategoryPhotoSlot is missing a finalized photo."""
    required_result = await db.execute(
        select(CategoryPhotoSlot.label).where(
            CategoryPhotoSlot.category_id == submission.category_id,
            CategoryPhotoSlot.required.is_(True),
            CategoryPhotoSlot.active.is_(True),
        )
    )
    required_labels = {row[0] for row in required_result.all()}
    if not required_labels:
        return

    captured_result = await db.execute(
        select(AppraisalPhoto.slot_label).where(
            AppraisalPhoto.appraisal_submission_id == submission.id,
            AppraisalPhoto.deleted_at.is_(None),
        )
    )
    captured_labels = {row[0] for row in captured_result.all()}
    missing = required_labels - captured_labels
    if missing:
        raise ValueError(f"Required photo slots not captured: {sorted(missing)}")


async def _fetch(
    db: AsyncSession,
    *,
    submission_id: uuid.UUID,
) -> AppraisalSubmission:
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


async def _get_for_write(
    db: AsyncSession,
    *,
    submission_id: uuid.UUID,
    user: User,
) -> AppraisalSubmission:
    submission = await _fetch(db, submission_id=submission_id)
    await _check_access(db, submission=submission, user=user)
    return submission


async def _check_access(
    db: AsyncSession,
    *,
    submission: AppraisalSubmission,
    user: User,
) -> None:
    """Raise PermissionError if user can't access the submission."""
    roles = await user_roles_service.role_slugs_for_user(db, user=user)
    if "admin" in roles:
        return
    if submission.appraiser_id != user.id:
        raise PermissionError("Access denied to submission")


async def _notify_managers_review_required(
    db: AsyncSession,
    *,
    submission: AppraisalSubmission,
) -> None:
    """Enqueue a management-review notification to every active sales_manager user."""
    # Look up the equipment record for display info.
    record = await db.get(EquipmentRecord, submission.equipment_record_id)
    reference_number = record.reference_number if record else str(submission.equipment_record_id)
    make = submission.make or "Unknown"
    model = submission.model or "equipment"
    red_flag_summary = (
        "; ".join(str(r) for r in (submission.red_flags or []))
        or "See management approval queue for details"
    )

    managers = (
        await db.execute(
            select(User)
            .join(Role, Role.id == User.role_id)
            .where(
                Role.slug == "sales_manager",
                User.status == "active",
            )
        )
    ).scalars().all()

    payload = {
        "reference_number": reference_number,
        "make": make,
        "model": model,
        "red_flag_summary": red_flag_summary,
    }

    for manager in managers:
        # Use email channel as default; the notification worker will respect
        # the manager's per-channel preferences via unified_notification_prefs_service.
        await notification_service.enqueue(
            db,
            idempotency_key=f"mgmt-review-{submission.id}-{manager.id}",
            user_id=manager.id,
            channel="email",
            template="management_review_flagged_email",
            payload=payload,
        )

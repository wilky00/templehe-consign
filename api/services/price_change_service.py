# ABOUTME: Phase 6 Sprint 3 — evaluates customer price changes against re-approval threshold.
# ABOUTME: Sets requires_manager_reapproval on ChangeRequest; notifies active sales_managers.
"""Price change re-approval service.

When a customer submits an ``update_consignment_price`` change request with a
``proposed_consignment_price``, this service:

1. Reads the current ``suggested_consignment_price`` from the approved
   ``AppraisalSubmission`` for the record.
2. Computes ``change_pct = |new - approved| / approved * 100``.
3. If ``change_pct > AppConfig('consignment_price_change_threshold_pct')``,
   sets ``ChangeRequest.requires_manager_reapproval = True`` and notifies
   active sales managers.
4. If no approved submission exists (e.g., record not yet approved), skips
   silently — no error because the threshold check is only meaningful
   after approval.
"""

from __future__ import annotations

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import AppraisalSubmission, ChangeRequest, Role, User, UserRole
from services import app_config_registry, notification_service

logger = structlog.get_logger(__name__)


async def evaluate(
    db: AsyncSession,
    *,
    change_request: ChangeRequest,
) -> None:
    """Evaluate whether a price change requires manager re-approval.

    Mutates ``change_request.requires_manager_reapproval`` in-place.
    Caller is responsible for flushing the session.
    """
    if change_request.proposed_consignment_price is None:
        return

    submission_result = await db.execute(
        select(AppraisalSubmission).where(
            AppraisalSubmission.equipment_record_id == change_request.equipment_record_id,
            AppraisalSubmission.status == "approved",
        )
    )
    submission = submission_result.scalar_one_or_none()
    if submission is None or submission.suggested_consignment_price is None:
        logger.info(
            "price_change_no_approved_submission",
            change_request_id=str(change_request.id),
        )
        return

    approved_price = float(submission.suggested_consignment_price)
    proposed_price = float(change_request.proposed_consignment_price)

    if approved_price == 0:
        return

    change_pct = abs(proposed_price - approved_price) / approved_price * 100

    threshold = await app_config_registry.get_typed(
        db, app_config_registry.CONSIGNMENT_PRICE_CHANGE_THRESHOLD_PCT.name
    )

    if change_pct <= threshold:
        return

    change_request.requires_manager_reapproval = True

    logger.info(
        "price_change_reapproval_required",
        change_request_id=str(change_request.id),
        change_pct=round(change_pct, 1),
        threshold=threshold,
    )

    record = change_request.equipment_record
    ref = record.reference_number if record else str(change_request.equipment_record_id)
    make_model = ""
    if record:
        approved_submissions = await db.execute(
            select(AppraisalSubmission).where(
                AppraisalSubmission.equipment_record_id == record.id,
                AppraisalSubmission.status == "approved",
            )
        )
        sub = approved_submissions.scalar_one_or_none()
        if sub:
            make_model = f"{sub.make or ''} {sub.model or ''}".strip()

    await _notify_managers(
        db,
        change_request=change_request,
        reference_number=ref,
        make_model=make_model,
        approved_price=approved_price,
        proposed_price=proposed_price,
        change_pct=round(change_pct, 1),
    )


async def _notify_managers(
    db: AsyncSession,
    *,
    change_request: ChangeRequest,
    reference_number: str,
    make_model: str,
    approved_price: float,
    proposed_price: float,
    change_pct: float,
) -> None:
    manager_role_result = await db.execute(
        select(Role).where(Role.slug == "sales_manager")
    )
    manager_role = manager_role_result.scalar_one_or_none()
    if manager_role is None:
        return

    managers_result = await db.execute(
        select(User)
        .join(UserRole, UserRole.user_id == User.id)
        .where(
            UserRole.role_id == manager_role.id,
            User.status == "active",
        )
    )
    managers = managers_result.scalars().all()

    for manager in managers:
        await notification_service.enqueue(
            db,
            idempotency_key=f"price_change_reapproval:{change_request.id}:{manager.id}",
            user_id=manager.id,
            channel="email",
            template="manager_price_change_reapproval",
            payload={
                "to_email": manager.email,
                "reference_number": reference_number,
                "make_model": make_model,
                "approved_price": f"{approved_price:.2f}",
                "proposed_price": f"{proposed_price:.2f}",
                "change_pct": f"{change_pct:.1f}",
            },
        )

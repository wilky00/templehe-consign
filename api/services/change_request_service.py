# ABOUTME: Customer-initiated change requests on an equipment record.
# ABOUTME: Persists the row + notifies the assigned sales rep or ops mailbox.
"""Change-request service.

Customer submits a change request (edit make/model, withdraw submission,
update location, etc.) via ``POST /me/equipment/{id}/change-requests``.
This service:

1. Writes the ``change_requests`` row (status='pending').
2. Notifies the assigned sales rep if one is set; otherwise enqueues
   an ops-mailbox notification so the request doesn't sit in limbo.
3. Returns the row for the router to serialize.

Accepted ``request_type`` values match the sales-rep workflow that Phase 3
will consume. Keeping them in sync is a Phase-3 task; for now the service
validates against a narrow allowlist.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import structlog
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from config import settings
from database.models import AuditLog, ChangeRequest, Customer, EquipmentRecord, User
from services import equipment_status_service, notification_service, sanitization

logger = structlog.get_logger(__name__)

_ALLOWED_REQUEST_TYPES = frozenset(
    {
        "edit_details",
        "update_location",
        "update_photos",
        "withdraw",
        "other",
    }
)


async def submit_change_request(
    db: AsyncSession,
    *,
    customer_user: User,
    record: EquipmentRecord,
    request_type: str,
    customer_notes: str | None,
) -> ChangeRequest:
    if request_type not in _ALLOWED_REQUEST_TYPES:
        raise HTTPException(
            status_code=422,
            detail=f"request_type must be one of: {sorted(_ALLOWED_REQUEST_TYPES)}",
        )
    clean_notes = sanitization.sanitize_plain(customer_notes)

    change = ChangeRequest(
        equipment_record_id=record.id,
        request_type=request_type,
        customer_notes=clean_notes,
        status="pending",
    )
    db.add(change)
    try:
        await db.flush()
    except IntegrityError as exc:
        # The partial unique index ux_change_requests_one_pending_per_record
        # surfaces as IntegrityError when a pending request already exists for
        # this record. Enforced at the DB so two concurrent submits can't both
        # land a pending row. Phase 2 Feature 2.4.1 / Phase 3 carry-over.
        await db.rollback()
        raise HTTPException(
            status_code=409,
            detail="A change request for this record is already pending. "
            "Wait for the sales team to resolve it before submitting another.",
        ) from exc

    await _notify_sales(
        db,
        customer_user=customer_user,
        record=record,
        change=change,
    )
    return change


async def _notify_sales(
    db: AsyncSession,
    *,
    customer_user: User,
    record: EquipmentRecord,
    change: ChangeRequest,
) -> None:
    """Resolve the recipient email and enqueue a notification.

    - If a sales rep is assigned and active, notify them directly.
    - Otherwise fall back to ``settings.sales_ops_email`` when configured,
      or log and continue when not (tests and fresh envs don't have one).
    """
    rep_email: str | None = None
    if record.assigned_sales_rep_id is not None:
        rep_result = await db.execute(select(User).where(User.id == record.assigned_sales_rep_id))
        rep = rep_result.scalar_one_or_none()
        if rep is not None and rep.status == "active":
            rep_email = rep.email

    if rep_email is None:
        fallback = getattr(settings, "sales_ops_email", "") or ""
        rep_email = fallback.strip() or None

    if rep_email is None:
        logger.info(
            "change_request_no_recipient",
            change_id=str(change.id),
            record_id=str(record.id),
        )
        return

    ref = record.reference_number or str(record.id)
    subject = f"Change request on {ref}: {change.request_type}"
    snippet = (change.customer_notes or "").replace("\n", " ")[:200]
    body = (
        f"<p>Customer {customer_user.email} submitted a change request "
        f"on equipment record <strong>{ref}</strong>.</p>"
        f"<p>Type: <strong>{change.request_type}</strong></p>"
        f"<p>Notes: {snippet or '(none)'}</p>"
        "<p>Open the sales console to review and respond.</p>"
    )
    await notification_service.enqueue(
        db,
        idempotency_key=f"change_request:{change.id}",
        user_id=record.assigned_sales_rep_id,
        channel="email",
        template="sales_change_request",
        payload={
            "to_email": rep_email,
            "subject": subject,
            "html_body": body,
            "change_request_id": str(change.id),
            "reference_number": ref,
        },
    )


async def list_change_requests_for_record(
    db: AsyncSession, record_id: uuid.UUID
) -> list[ChangeRequest]:
    result = await db.execute(
        select(ChangeRequest)
        .where(ChangeRequest.equipment_record_id == record_id)
        .order_by(ChangeRequest.submitted_at.desc())
    )
    return list(result.scalars().all())


async def resolve_change_request(
    db: AsyncSession,
    *,
    change_request_id: uuid.UUID,
    resolver: User,
    resolver_role_slug: str,
    new_status: str,
    resolution_notes: str | None,
) -> ChangeRequest:
    """Mark a pending change request as resolved or rejected.

    On ``status='resolved'`` + ``request_type='withdraw'``, the underlying
    equipment record's status transitions to ``withdrawn``. Both paths
    enqueue a customer-facing email via NotificationService summarizing
    the action taken (spec Feature 2.4.3). Audit event written either way.
    """
    if new_status not in ("resolved", "rejected"):
        raise HTTPException(
            status_code=422,
            detail="status must be 'resolved' or 'rejected'",
        )

    result = await db.execute(
        select(ChangeRequest)
        .where(ChangeRequest.id == change_request_id)
        .options(
            selectinload(ChangeRequest.equipment_record)
            .selectinload(EquipmentRecord.customer)
            .selectinload(Customer.user)
        )
    )
    change = result.scalar_one_or_none()
    if change is None:
        raise HTTPException(status_code=404, detail="change request not found")
    if change.status != "pending":
        raise HTTPException(
            status_code=409,
            detail=f"change request is already '{change.status}'; cannot re-resolve",
        )

    record = change.equipment_record
    customer = record.customer
    customer_user = customer.user

    clean_notes = sanitization.sanitize_plain(resolution_notes)

    change.status = new_status
    change.resolution_notes = clean_notes
    change.resolved_at = datetime.now(UTC)
    change.resolved_by = resolver.id
    db.add(change)

    # Withdraw-on-resolve is the one request type that doubles as a
    # terminal status change. Spec Feature 2.4.3: "If the request type was
    # Delete Listing [withdraw], resolution sets EquipmentRecord.status = withdrawn."
    if new_status == "resolved" and change.request_type == "withdraw":
        await equipment_status_service.record_transition(
            db,
            record=record,
            to_status="withdrawn",
            changed_by=resolver,
            note=(clean_notes or "Withdrawn via customer change request.")[:500],
            customer=customer_user,
        )

    # Customer-facing resolution email. Separate from the status-transition
    # email so we can surface the resolution notes and the request type.
    ref = record.reference_number or str(record.id)
    verb = "resolved" if new_status == "resolved" else "declined"
    subject = f"Your change request on {ref} was {verb}"
    notes_html = (
        f"<p><strong>Notes:</strong><br>{(clean_notes or '').replace(chr(10), '<br>')}</p>"
        if clean_notes
        else ""
    )
    body = (
        f"<p>Hi {customer_user.first_name},</p>"
        f"<p>Your <strong>{change.request_type}</strong> request on equipment record "
        f"<strong>{ref}</strong> has been <strong>{verb}</strong> by our sales team.</p>"
        f"{notes_html}"
        "<p>— The Temple Heavy Equipment team</p>"
    )
    await notification_service.enqueue(
        db,
        idempotency_key=f"change_request_resolution:{change.id}:{new_status}",
        user_id=customer_user.id,
        channel="email",
        template="customer_change_request_resolution",
        payload={
            "to_email": customer_user.email,
            "subject": subject,
            "html_body": body,
            "change_request_id": str(change.id),
            "reference_number": ref,
        },
    )

    db.add(
        AuditLog(
            event_type=f"change_request.{new_status}",
            actor_id=resolver.id,
            actor_role=resolver_role_slug,
            target_type="change_request",
            target_id=change.id,
            after_state={
                "equipment_record_id": str(record.id),
                "request_type": change.request_type,
                "resolution_notes": clean_notes,
            },
        )
    )
    await db.flush()
    return change

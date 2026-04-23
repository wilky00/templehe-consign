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

import structlog
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database.models import ChangeRequest, EquipmentRecord, User
from services import notification_service, sanitization

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
    await db.flush()

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

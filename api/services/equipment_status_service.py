# ABOUTME: Records equipment_records.status transitions and notifies the customer via email.
# ABOUTME: Called from tests + future Phase 3 sales-rep endpoints; compose-once, use-everywhere.
"""Status transition service.

``record_transition`` is the one entry point for any code that changes
``equipment_records.status``. It:

1. Validates the ``(from, to)`` edge against the canonical state machine
   in ``equipment_status_machine``. Phase 4-prework extracted the rules
   into that module so admin UI + the runtime read the same registry.
2. Writes an immutable ``status_events`` row.
3. Updates ``record.status`` and ``updated_at``.
4. Enqueues a customer-facing status-update email through
   ``NotificationService`` when the destination status warrants it
   (``equipment_status_machine.notifies_customer``).
5. Enqueues a sales-rep notification when the destination status
   warrants it (``equipment_status_machine.notifies_sales_rep``).

Email + SMS templates for the customer-facing and sales-rep
notifications live inline here. The plan to extract these into a
template registry is tracked in the Phase 4 dev plan; until then,
keeping them in one file keeps the mapping reviewable.
"""

from __future__ import annotations

import uuid

import structlog
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import EquipmentRecord, StatusEvent, User
from services import (
    equipment_status_machine,
    notification_preferences_service,
    notification_service,
)

logger = structlog.get_logger(__name__)


def _compose_email(
    *, user: User, record: EquipmentRecord, to_status: str, note: str | None
) -> tuple[str, str]:
    ref = record.reference_number or "(no reference yet)"
    subject = f"{equipment_status_machine.display_name(to_status)} — {ref}"

    note_html = f"<p>{note}</p>" if note else ""
    body = (
        f"<p>Hi {user.first_name},</p>"
        f"<p>The status of your equipment submission "
        f"(<strong>{ref}</strong>) has changed to <strong>{to_status}</strong>.</p>"
        f"{note_html}"
        "<p>You can see the full timeline from your customer portal.</p>"
        "<p>— The Temple Heavy Equipment team</p>"
    )
    return subject, body


async def record_transition(
    db: AsyncSession,
    *,
    record: EquipmentRecord,
    to_status: str,
    changed_by: User | None,
    note: str | None = None,
    customer: User | None = None,
) -> StatusEvent:
    """Apply a status transition.

    ``customer`` is the User whose email receives the notification.
    Typically resolved via ``record.customer.user`` in the caller; kept
    as an explicit arg so callers that already have the User object
    don't have to re-fetch it.
    """
    from_status = record.status
    if from_status == to_status:
        raise HTTPException(
            status_code=409,
            detail=f"Record is already in status '{to_status}'.",
        )
    if equipment_status_machine.is_forbidden_transition(from_status, to_status):
        raise HTTPException(
            status_code=409,
            detail=f"Cannot transition from '{from_status}' to '{to_status}'.",
        )

    event = StatusEvent(
        equipment_record_id=record.id,
        from_status=from_status,
        to_status=to_status,
        changed_by=changed_by.id if changed_by is not None else None,
        note=note,
    )
    db.add(event)
    record.status = to_status
    db.add(record)
    await db.flush()

    if customer is not None and equipment_status_machine.notifies_customer(to_status):
        subject, body = _compose_email(user=customer, record=record, to_status=to_status, note=note)
        await notification_service.enqueue(
            db,
            idempotency_key=_email_idempotency_key(record.id, to_status),
            user_id=customer.id,
            channel="email",
            template=f"status_{to_status}",
            payload={
                "to_email": customer.email,
                "subject": subject,
                "html_body": body,
                "reference_number": record.reference_number,
                "to_status": to_status,
            },
        )

    if (
        equipment_status_machine.notifies_sales_rep(to_status)
        and record.assigned_sales_rep_id is not None
    ):
        await _notify_sales_rep(db, record=record, to_status=to_status)
    return event


def _email_idempotency_key(record_id: uuid.UUID, to_status: str) -> str:
    """One email per (record, destination status). A bounce-back re-transition
    to the same status is blocked upstream, so this key never double-delivers."""
    return f"status_update:{record_id}:{to_status}"


def _sales_rep_idempotency_key(record_id: uuid.UUID, to_status: str) -> str:
    return f"sales_rep_status:{record_id}:{to_status}"


def _compose_sales_rep_email(
    *, rep: User, record: EquipmentRecord, to_status: str
) -> tuple[str, str]:
    ref = record.reference_number or str(record.id)
    make_model = (
        " ".join(part for part in (record.customer_make, record.customer_model) if part)
        or "your equipment record"
    )
    if to_status == "approved_pending_esign":
        subject = f"[Approved] Appraisal for {ref} — Ready for eSign"
        body = (
            f"<p>Hi {rep.first_name or 'team'},</p>"
            f"<p>The manager has approved the appraisal for "
            f"<strong>{ref}</strong> ({make_model}). The record is now "
            f"<strong>ready for eSign</strong>.</p>"
            "<p>Open the record in the sales dashboard to start the eSign flow.</p>"
        )
    elif to_status == "esigned_pending_publish":
        subject = f"[Signed] {ref} ready to publish"
        body = (
            f"<p>Hi {rep.first_name or 'team'},</p>"
            f"<p>The customer has signed the consignment agreement for "
            f"<strong>{ref}</strong> ({make_model}). The listing is "
            f"<strong>ready to publish</strong>.</p>"
            "<p>Open the record in the sales dashboard and tap "
            "<em>Publish Listing</em> when you're ready.</p>"
        )
    else:
        subject = f"Status update — {ref}"
        body = (
            f"<p>Hi {rep.first_name or 'team'},</p>"
            f"<p>Record <strong>{ref}</strong> moved to "
            f"<strong>{to_status}</strong>.</p>"
        )
    return subject, body


def _compose_sales_rep_sms(*, record: EquipmentRecord, to_status: str) -> str:
    ref = record.reference_number or str(record.id)
    if to_status == "approved_pending_esign":
        return f"Manager approved {ref}. Log in to initiate eSign."
    if to_status == "esigned_pending_publish":
        return f"TempleHE: customer signed {ref}. Ready to publish."
    return f"TempleHE: {ref} moved to {to_status}."


async def _notify_sales_rep(
    db: AsyncSession,
    *,
    record: EquipmentRecord,
    to_status: str,
) -> None:
    """Enqueue the sales-rep notification on the rep's preferred channel.

    No-ops silently if the rep user is missing/inactive — there's no good
    user-facing recovery for an orphan FK and we already wrote the audit
    trail upstream.
    """
    rep = (
        await db.execute(select(User).where(User.id == record.assigned_sales_rep_id))
    ).scalar_one_or_none()
    if rep is None or rep.status != "active":
        return

    resolved = await notification_preferences_service.resolve_channel(db, user=rep)
    idem = _sales_rep_idempotency_key(record.id, to_status)

    if resolved.channel == "sms" and resolved.destination:
        body = _compose_sales_rep_sms(record=record, to_status=to_status)
        await notification_service.enqueue(
            db,
            idempotency_key=idem,
            user_id=rep.id,
            channel="sms",
            template=f"sales_rep_{to_status}",
            payload={
                "to_number": resolved.destination,
                "body": body,
                "reference_number": record.reference_number,
                "to_status": to_status,
            },
        )
        return

    if not resolved.destination:
        # Email destination missing — caller's User row has no email.
        # Skip rather than enqueue a guaranteed-fail row.
        logger.warning(
            "sales_rep_notify_skipped_no_destination",
            user_id=str(rep.id),
            record_id=str(record.id),
            to_status=to_status,
        )
        return

    subject, body = _compose_sales_rep_email(rep=rep, record=record, to_status=to_status)
    await notification_service.enqueue(
        db,
        idempotency_key=idem,
        user_id=rep.id,
        channel="email",
        template=f"sales_rep_{to_status}",
        payload={
            "to_email": resolved.destination,
            "subject": subject,
            "html_body": body,
            "reference_number": record.reference_number,
            "to_status": to_status,
        },
    )

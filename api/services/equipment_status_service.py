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
    notification_templates,
    watchers_service,
)

logger = structlog.get_logger(__name__)


async def _compose_email(
    db,
    *,
    user: User,
    record: EquipmentRecord,
    to_status: str,
    note: str | None,
) -> tuple[str, str]:
    """Phase 4 Sprint 5 — delegates to the notification template
    registry so admin can edit the customer-facing status email copy
    without a redeploy. Variables match the previous inline composer
    so the rendered output is byte-equivalent absent an admin override."""
    ref = record.reference_number or "(no reference yet)"
    note_html = f"<p>{note}</p>" if note else ""
    rendered = await notification_templates.render_with_overrides(
        db,
        "status_update",
        variables={
            "first_name": user.first_name,
            "reference_number": ref,
            "to_status_display": equipment_status_machine.display_name(to_status),
            "to_status": to_status,
            "note_html": note_html,
        },
    )
    return rendered.subject or "", rendered.body


async def record_transition(
    db: AsyncSession,
    *,
    record: EquipmentRecord,
    to_status: str,
    changed_by: User | None,
    note: str | None = None,
    customer: User | None = None,
    notify_override: bool | None = None,
) -> StatusEvent:
    """Apply a status transition.

    ``customer`` is the User whose email receives the notification.
    Typically resolved via ``record.customer.user`` in the caller; kept
    as an explicit arg so callers that already have the User object
    don't have to re-fetch it.

    ``notify_override`` lets the caller force notification dispatch
    on/off regardless of the registry default. ``None`` (the default)
    follows ``notifies_customer``/``notifies_sales_rep``. Used by the
    Phase 4 admin manual-transition endpoint where the admin chooses
    whether to fan out emails for back-fill / data correction work.
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

    customer_should_notify = (
        notify_override
        if notify_override is not None
        else equipment_status_machine.notifies_customer(to_status)
    )
    sales_rep_should_notify = (
        notify_override
        if notify_override is not None
        else equipment_status_machine.notifies_sales_rep(to_status)
    )

    if customer is not None and customer_should_notify:
        subject, body = await _compose_email(
            db, user=customer, record=record, to_status=to_status, note=note
        )
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

    if sales_rep_should_notify and record.assigned_sales_rep_id is not None:
        await _notify_sales_rep(db, record=record, to_status=to_status)

    # Sprint 5: watchers receive the same customer-facing email when
    # the registry says this status is customer-facing. Skip when
    # notify_override is False (admin chose silent transition).
    if customer_should_notify:
        await _notify_watchers(db, record=record, to_status=to_status, note=note)
    return event


def _email_idempotency_key(record_id: uuid.UUID, to_status: str) -> str:
    """One email per (record, destination status). A bounce-back re-transition
    to the same status is blocked upstream, so this key never double-delivers."""
    return f"status_update:{record_id}:{to_status}"


def _sales_rep_idempotency_key(record_id: uuid.UUID, to_status: str) -> str:
    return f"sales_rep_status:{record_id}:{to_status}"


_SALES_REP_EMAIL_TEMPLATES = {
    "approved_pending_esign": "sales_rep_approved_pending_esign",
    "esigned_pending_publish": "sales_rep_esigned_pending_publish",
}
_SALES_REP_SMS_TEMPLATES = {
    "approved_pending_esign": "sales_rep_approved_pending_esign_sms",
    "esigned_pending_publish": "sales_rep_esigned_pending_publish_sms",
}


def _sales_rep_template_name(to_status: str, *, channel: str) -> str:
    table = _SALES_REP_EMAIL_TEMPLATES if channel == "email" else _SALES_REP_SMS_TEMPLATES
    fallback = "sales_rep_generic_status" if channel == "email" else "sales_rep_generic_status_sms"
    return table.get(to_status, fallback)


async def _compose_sales_rep_email(
    db,
    *,
    rep: User,
    record: EquipmentRecord,
    to_status: str,
) -> tuple[str, str]:
    ref = record.reference_number or str(record.id)
    make_model = (
        " ".join(part for part in (record.customer_make, record.customer_model) if part)
        or "your equipment record"
    )
    name = _sales_rep_template_name(to_status, channel="email")
    rendered = await notification_templates.render_with_overrides(
        db,
        name,
        variables={
            "first_name": rep.first_name or "team",
            "reference_number": ref,
            "make_model": make_model,
            "to_status": to_status,
        },
    )
    return rendered.subject or "", rendered.body


async def _compose_sales_rep_sms(db, *, record: EquipmentRecord, to_status: str) -> str:
    ref = record.reference_number or str(record.id)
    name = _sales_rep_template_name(to_status, channel="sms")
    rendered = await notification_templates.render_with_overrides(
        db,
        name,
        variables={"reference_number": ref, "to_status": to_status},
    )
    return rendered.body


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
        body = await _compose_sales_rep_sms(db, record=record, to_status=to_status)
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

    subject, body = await _compose_sales_rep_email(db, rep=rep, record=record, to_status=to_status)
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


async def _notify_watchers(
    db: AsyncSession,
    *,
    record: EquipmentRecord,
    to_status: str,
    note: str | None,
) -> None:
    """Phase 4 Sprint 5 — fan out the customer-facing status email to
    every watcher of this record. Each watcher gets the same template
    + variables; idempotency key includes the watcher user_id so two
    watchers each get one email.

    Skips inactive watchers + watchers without a destination on their
    preferred channel (notification_preferences_service.resolve_channel
    returns destination=None when there's nothing to deliver to)."""
    user_ids = await watchers_service.watcher_user_ids(db, record_id=record.id)
    if not user_ids:
        return
    note_html = f"<p>{note}</p>" if note else ""
    ref = record.reference_number or "(no reference yet)"
    rendered = await notification_templates.render_with_overrides(
        db,
        "status_update",
        variables={
            "first_name": "team",
            "reference_number": ref,
            "to_status_display": equipment_status_machine.display_name(to_status),
            "to_status": to_status,
            "note_html": note_html,
        },
    )
    for watcher_id in user_ids:
        watcher = (await db.execute(select(User).where(User.id == watcher_id))).scalar_one_or_none()
        if watcher is None or watcher.status != "active":
            continue
        resolved = await notification_preferences_service.resolve_channel(db, user=watcher)
        if not resolved.destination:
            continue
        await notification_service.enqueue(
            db,
            idempotency_key=f"status_watcher:{record.id}:{to_status}:{watcher_id}",
            user_id=watcher.id,
            channel="email" if resolved.channel != "sms" else "sms",
            template="status_update_watcher",
            payload={
                "to_email": resolved.destination if resolved.channel != "sms" else None,
                "to_number": resolved.destination if resolved.channel == "sms" else None,
                "subject": rendered.subject,
                "html_body": rendered.body,
                "body": rendered.body,
                "reference_number": record.reference_number,
                "to_status": to_status,
            },
        )

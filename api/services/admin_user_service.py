# ABOUTME: Phase 4 Sprint 2 — admin deactivates user; reassigns open records + future events.
# ABOUTME: Refuses 409 if open work exists w/o reassign target. Mirrors security baseline §11.
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import (
    AuditLog,
    CalendarEvent,
    EquipmentRecord,
    User,
)
from schemas.admin import DeactivateUserOpenWork, DeactivateUserResponse
from services import equipment_service, user_roles_service

# Statuses where a record is still in flight and needs a human owner.
# Mirrors equipment_status_machine — anything not terminal.
_OPEN_STATUSES_EXCLUDED = ("sold", "declined", "withdrawn")

# Roles that own work (records, calendar events). The customer role
# auto-granted at registration is portal-access only and doesn't count
# for reassignment overlap — picking another customer to take a sales
# rep's open records would be nonsensical.
_WORK_ROLES = frozenset({"sales", "sales_manager", "admin", "appraiser"})


async def deactivate_user(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    reassign_to_id: uuid.UUID | None,
    actor: User,
) -> DeactivateUserResponse:
    """Deactivate a user. If they own open records or future calendar
    events, ``reassign_to_id`` is required and must point to an active
    user holding at least one role in common with the leaving user."""
    target = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if target is None:
        raise HTTPException(status_code=404, detail="User not found.")
    if target.id == actor.id:
        raise HTTPException(
            status_code=409,
            detail="Admins cannot deactivate their own account from this endpoint.",
        )
    if target.status == "deactivated":
        raise HTTPException(status_code=409, detail="User is already deactivated.")

    open_records = await _open_records_assigned_to(db, user_id=target.id)
    future_events = await _future_events_for_appraiser(db, user_id=target.id)

    if (open_records or future_events) and reassign_to_id is None:
        raise HTTPException(
            status_code=409,
            detail=DeactivateUserOpenWork(
                detail=(
                    f"User has {len(open_records)} open record(s) and "
                    f"{len(future_events)} upcoming calendar event(s). "
                    "Pick a reassignment target."
                ),
                open_record_count=len(open_records),
                future_event_count=len(future_events),
            ).model_dump(),
        )

    reassignee: User | None = None
    if reassign_to_id is not None:
        reassignee = await _resolve_reassignee(db, reassign_to_id=reassign_to_id, target=target)

    reassigned_record_ids: list[uuid.UUID] = []
    if reassignee is not None and open_records:
        reassigned_record_ids = await _reassign_records(
            db, records=open_records, leaving=target, joining=reassignee, actor=actor
        )

    reassigned_event_ids: list[uuid.UUID] = []
    if reassignee is not None and future_events:
        reassigned_event_ids = await _reassign_events(
            db, events=future_events, leaving=target, joining=reassignee, actor=actor
        )

    target.status = "deactivated"
    db.add(target)
    await db.flush()
    db.add(
        AuditLog(
            event_type="user.admin_deactivated",
            actor_id=actor.id,
            actor_role="admin",
            target_type="user",
            target_id=target.id,
            before_state={"status": "active"},
            after_state={
                "status": "deactivated",
                "reassign_to_id": str(reassignee.id) if reassignee else None,
                "reassigned_record_ids": [str(rid) for rid in reassigned_record_ids],
                "reassigned_event_ids": [str(eid) for eid in reassigned_event_ids],
            },
        )
    )
    await db.flush()
    return DeactivateUserResponse(
        user_id=target.id,
        reassigned_records=reassigned_record_ids,
        reassigned_events=reassigned_event_ids,
        new_status="deactivated",
    )


async def _open_records_assigned_to(
    db: AsyncSession, *, user_id: uuid.UUID
) -> list[EquipmentRecord]:
    rows = (
        (
            await db.execute(
                select(EquipmentRecord)
                .where(
                    or_(
                        EquipmentRecord.assigned_sales_rep_id == user_id,
                        EquipmentRecord.assigned_appraiser_id == user_id,
                    )
                )
                .where(EquipmentRecord.deleted_at.is_(None))
                .where(EquipmentRecord.status.notin_(_OPEN_STATUSES_EXCLUDED))
            )
        )
        .scalars()
        .all()
    )
    return list(rows)


async def _future_events_for_appraiser(
    db: AsyncSession, *, user_id: uuid.UUID
) -> list[CalendarEvent]:
    now = datetime.now(UTC)
    rows = (
        (
            await db.execute(
                select(CalendarEvent)
                .where(CalendarEvent.appraiser_id == user_id)
                .where(CalendarEvent.scheduled_at >= now)
                .where(CalendarEvent.cancelled_at.is_(None))
            )
        )
        .scalars()
        .all()
    )
    return list(rows)


async def _resolve_reassignee(db: AsyncSession, *, reassign_to_id: uuid.UUID, target: User) -> User:
    reassignee = (
        await db.execute(select(User).where(User.id == reassign_to_id))
    ).scalar_one_or_none()
    if reassignee is None:
        raise HTTPException(status_code=422, detail="Reassignment target not found.")
    if reassignee.status != "active":
        raise HTTPException(status_code=422, detail="Reassignment target is not active.")
    if reassignee.id == target.id:
        raise HTTPException(
            status_code=422,
            detail="Cannot reassign to the user being deactivated.",
        )
    target_roles = await user_roles_service.role_slugs_for_user(db, user=target)
    new_roles = await user_roles_service.role_slugs_for_user(db, user=reassignee)
    target_work = target_roles & _WORK_ROLES
    new_work = new_roles & _WORK_ROLES
    if not (target_work & new_work):
        raise HTTPException(
            status_code=422,
            detail=(
                "Reassignment target does not share a work role with the leaving "
                "user. Pick a teammate who can take on this work."
            ),
        )
    return reassignee


async def _reassign_records(
    db: AsyncSession,
    *,
    records: list[EquipmentRecord],
    leaving: User,
    joining: User,
    actor: User,
) -> list[uuid.UUID]:
    """Move every open record from ``leaving`` to ``joining``. One audit
    log row per record so the trail tells exactly what moved + why."""
    moved: list[uuid.UUID] = []
    for rec in records:
        before = {
            "assigned_sales_rep_id": str(rec.assigned_sales_rep_id)
            if rec.assigned_sales_rep_id
            else None,
            "assigned_appraiser_id": str(rec.assigned_appraiser_id)
            if rec.assigned_appraiser_id
            else None,
        }
        if rec.assigned_sales_rep_id == leaving.id:
            rec.assigned_sales_rep_id = joining.id
        if rec.assigned_appraiser_id == leaving.id:
            rec.assigned_appraiser_id = joining.id
        db.add(rec)
        await db.flush()
        after = {
            "assigned_sales_rep_id": str(rec.assigned_sales_rep_id)
            if rec.assigned_sales_rep_id
            else None,
            "assigned_appraiser_id": str(rec.assigned_appraiser_id)
            if rec.assigned_appraiser_id
            else None,
        }
        db.add(
            AuditLog(
                event_type="equipment_record.deactivation_reassigned",
                actor_id=actor.id,
                actor_role="admin",
                target_type="equipment_record",
                target_id=rec.id,
                before_state=before,
                after_state={
                    **after,
                    "trigger_user_id": str(leaving.id),
                },
            )
        )
        await equipment_service.enqueue_assignment_notification(
            db,
            record=rec,
            assigned_user_id=joining.id,
            trigger="admin_deactivation",
        )
        moved.append(rec.id)
    await db.flush()
    return moved


async def _reassign_events(
    db: AsyncSession,
    *,
    events: list[CalendarEvent],
    leaving: User,
    joining: User,
    actor: User,
) -> list[uuid.UUID]:
    moved: list[uuid.UUID] = []
    for ev in events:
        before = {"appraiser_id": str(ev.appraiser_id)}
        ev.appraiser_id = joining.id
        db.add(ev)
        await db.flush()
        db.add(
            AuditLog(
                event_type="calendar_event.deactivation_reassigned",
                actor_id=actor.id,
                actor_role="admin",
                target_type="calendar_event",
                target_id=ev.id,
                before_state=before,
                after_state={
                    "appraiser_id": str(ev.appraiser_id),
                    "trigger_user_id": str(leaving.id),
                },
            )
        )
        moved.append(ev.id)
    await db.flush()
    return moved

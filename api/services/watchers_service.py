# ABOUTME: Phase 4 Sprint 5 — manage equipment_record_watchers + fan-out hook.
# ABOUTME: Watchers receive every status-update notification the customer would.
"""Equipment record watchers service.

Phase 4 admin (and later sales reps) can mark themselves or others as
*watchers* of an equipment record. Watchers don't own the record — the
primary assignee in ``equipment_records.assigned_sales_rep_id`` keeps
that role — but they receive a copy of every customer-facing
status-update notification so they can stay in the loop without
manually checking the dashboard.

The service is intentionally thin: add/remove/list. The fan-out
itself lives in ``equipment_status_service.record_transition``, which
calls ``notify_watchers`` after the customer + sales-rep dispatches.
"""

from __future__ import annotations

import uuid

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from database.models import EquipmentRecord, EquipmentRecordWatcher, User


async def list_watchers(db: AsyncSession, *, record_id: uuid.UUID) -> list[EquipmentRecordWatcher]:
    """Watchers for one record, eager-loading the user so callers can
    read ``.user.email`` / ``.user.first_name`` without a lazy-load."""
    rows = (
        (
            await db.execute(
                select(EquipmentRecordWatcher)
                .where(EquipmentRecordWatcher.record_id == record_id)
                .options(selectinload(EquipmentRecordWatcher.user))
                .order_by(EquipmentRecordWatcher.added_at)
            )
        )
        .scalars()
        .all()
    )
    return list(rows)


async def add_watcher(
    db: AsyncSession,
    *,
    record_id: uuid.UUID,
    user_id: uuid.UUID,
    added_by: uuid.UUID | None,
) -> EquipmentRecordWatcher:
    """Idempotent — re-adding an existing watcher returns the existing
    row without bumping ``added_at``. 422 if the record or user is
    missing/deleted."""
    record = (
        await db.execute(
            select(EquipmentRecord)
            .where(EquipmentRecord.id == record_id)
            .where(EquipmentRecord.deleted_at.is_(None))
        )
    ).scalar_one_or_none()
    if record is None:
        raise HTTPException(status_code=404, detail="Equipment record not found.")

    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if user is None or user.status != "active":
        raise HTTPException(status_code=422, detail="Watcher target user not found or inactive.")

    stmt = (
        pg_insert(EquipmentRecordWatcher.__table__)
        .values(record_id=record_id, user_id=user_id, added_by=added_by)
        .on_conflict_do_nothing(index_elements=["record_id", "user_id"])
    )
    await db.execute(stmt)
    await db.flush()
    # Re-fetch with user eager-loaded for the response shape.
    refreshed = (
        await db.execute(
            select(EquipmentRecordWatcher)
            .where(EquipmentRecordWatcher.record_id == record_id)
            .where(EquipmentRecordWatcher.user_id == user_id)
            .options(selectinload(EquipmentRecordWatcher.user))
        )
    ).scalar_one()
    return refreshed


async def remove_watcher(db: AsyncSession, *, record_id: uuid.UUID, user_id: uuid.UUID) -> bool:
    """Idempotent — returns True if a row was removed, False if the
    watcher didn't exist."""
    existing = (
        await db.execute(
            select(EquipmentRecordWatcher)
            .where(EquipmentRecordWatcher.record_id == record_id)
            .where(EquipmentRecordWatcher.user_id == user_id)
        )
    ).scalar_one_or_none()
    if existing is None:
        return False
    await db.delete(existing)
    await db.flush()
    return True


async def watcher_user_ids(db: AsyncSession, *, record_id: uuid.UUID) -> list[uuid.UUID]:
    """Cheap lookup for the dispatch fan-out — just the user_ids,
    no eager-load."""
    rows = (
        (
            await db.execute(
                select(EquipmentRecordWatcher.user_id).where(
                    EquipmentRecordWatcher.record_id == record_id
                )
            )
        )
        .scalars()
        .all()
    )
    return list(rows)

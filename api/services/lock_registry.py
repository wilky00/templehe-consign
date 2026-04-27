# ABOUTME: Phase 4 Sprint 5 — registry of resource types eligible for record_locks.
# ABOUTME: Replaces hardcoded "equipment_record" check + reference loader scattered in router.
"""Lockable resource registry.

Phase 1 hard-coded ``record_locks.record_type`` to a single value
(``"equipment_record"``) with the validator + reference loader living
inline in the router. Phase 4+ adds locks for other resources
(appraisal reports, customer profiles when admin edits them, etc.) —
one registry per type means the router stays a thin pass-through and
the lock-overridden notification can compose a sensible reference
string regardless of resource.

Each resource registers a ``LockableResource`` with:

- ``type`` — the value stored in ``record_locks.record_type``.
- ``display_name`` — for log lines + notifications.
- ``audit_prefix`` — prepended to ``audit_logs.event_type`` for lock
  acquire/refresh/override events.
- ``reference_loader(db, record_id) -> str`` — async function that
  returns a human-readable label (e.g. equipment record's
  ``reference_number``). Falls back to the UUID when the resource is
  missing.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import EquipmentRecord


@dataclass(frozen=True)
class LockableResource:
    type: str
    display_name: str
    audit_prefix: str
    reference_loader: Callable[[AsyncSession, uuid.UUID], Awaitable[str]]


_REGISTRY: dict[str, LockableResource] = {}


def register(resource: LockableResource) -> LockableResource:
    existing = _REGISTRY.get(resource.type)
    if existing is not None and existing != resource:
        raise RuntimeError(
            f"Lock resource type '{resource.type}' already registered with a "
            "different spec; rename or deduplicate."
        )
    _REGISTRY[resource.type] = resource
    return resource


def get(record_type: str) -> LockableResource:
    """Lookup a registered resource. Raises HTTPException 422 for
    unknown types so the router maps cleanly to a client error."""
    spec = _REGISTRY.get(record_type)
    if spec is None:
        raise HTTPException(
            status_code=422,
            detail=f"unsupported record_type: {record_type}",
        )
    return spec


def all_types() -> tuple[str, ...]:
    return tuple(sorted(_REGISTRY))


async def reference_for(db: AsyncSession, *, record_id: uuid.UUID, record_type: str) -> str:
    """Look up a human-readable label for a locked resource. Returns
    the UUID string when the resource is missing or the loader can't
    find a label."""
    spec = _REGISTRY.get(record_type)
    if spec is None:
        return str(record_id)
    try:
        return await spec.reference_loader(db, record_id)
    except Exception:  # noqa: BLE001 — best-effort label, never raise from notify path.
        return str(record_id)


# ---------------------------------------------------------------------------
# Built-in resources.
# ---------------------------------------------------------------------------


async def _equipment_record_reference(db: AsyncSession, record_id: uuid.UUID) -> str:
    ref = (
        await db.execute(
            select(EquipmentRecord.reference_number).where(EquipmentRecord.id == record_id)
        )
    ).scalar_one_or_none()
    return ref or str(record_id)


EQUIPMENT_RECORD = register(
    LockableResource(
        type="equipment_record",
        display_name="equipment record",
        audit_prefix="equipment_record.lock",
        reference_loader=_equipment_record_reference,
    )
)

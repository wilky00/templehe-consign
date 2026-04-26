# ABOUTME: Phase 4 Sprint 3 — admin-controlled intake form visibility + ordering.
# ABOUTME: Reads intake_fields_visible + intake_fields_order from AppConfig.
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from services import app_config_registry


async def visible_fields(db: AsyncSession) -> list[str]:
    """Return the intake field slugs the customer-facing form should
    render, in canonical order. Defaults to every canonical field
    (``INTAKE_FIELDS_CANONICAL``) when the AppConfig key is unset."""
    raw = await app_config_registry.get_typed(db, app_config_registry.INTAKE_FIELDS_VISIBLE.name)
    if not raw:
        return list(app_config_registry.INTAKE_FIELDS_CANONICAL)
    canonical = set(app_config_registry.INTAKE_FIELDS_CANONICAL)
    return [f for f in raw if f in canonical]


async def field_order(db: AsyncSession) -> list[str]:
    """Return the render order for the visible fields. Fields the admin
    didn't explicitly order render at the bottom in canonical order."""
    visible = await visible_fields(db)
    visible_set = set(visible)
    raw = await app_config_registry.get_typed(db, app_config_registry.INTAKE_FIELDS_ORDER.name)
    if not raw:
        return visible
    canonical = list(app_config_registry.INTAKE_FIELDS_CANONICAL)
    canonical_set = set(canonical)
    ordered = [f for f in raw if f in visible_set and f in canonical_set]
    seen = set(ordered)
    tail = [f for f in canonical if f in visible_set and f not in seen]
    return ordered + tail

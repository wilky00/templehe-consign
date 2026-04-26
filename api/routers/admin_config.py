# ABOUTME: Phase 4 Sprint 3 — admin reads + writes the AppConfig registry from the SPA.
# ABOUTME: Per-key validators run via set_typed; bad payloads surface as 422.
from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from database.base import get_db
from database.models import User
from middleware.rbac import require_roles
from schemas.admin import (
    AppConfigItem,
    AppConfigListResponse,
    AppConfigUpdateRequest,
)
from services import app_config_registry

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/admin/config", tags=["admin-config"])

_require_admin = require_roles("admin")


@router.get("", response_model=AppConfigListResponse)
async def list_config(
    _admin: User = Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
) -> AppConfigListResponse:
    """Every registered AppConfig key + its current typed value. Sorted
    by (category, name) so the admin form renders deterministically."""
    items: list[AppConfigItem] = []
    for spec in app_config_registry.all_specs():
        value = await app_config_registry.get_typed(db, spec.name)
        items.append(
            AppConfigItem(
                name=spec.name,
                category=spec.category,
                field_type=spec.field_type,
                description=spec.description,
                default=spec.default,
                value=value,
            )
        )
    return AppConfigListResponse(items=items)


@router.patch("/{key}", response_model=AppConfigItem)
async def update_config(
    key: str,
    body: AppConfigUpdateRequest,
    admin: User = Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
) -> AppConfigItem:
    """Validate + serialize + upsert one AppConfig key. The per-key
    validator on the KeySpec runs first; ValueError → 422 with the
    validator's message so the admin form can surface it inline."""
    try:
        spec = app_config_registry.get_spec(key)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Unknown config key: {key}") from exc

    try:
        await app_config_registry.set_typed(db, key, body.value, updated_by=admin.id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    new_value = await app_config_registry.get_typed(db, key)
    return AppConfigItem(
        name=spec.name,
        category=spec.category,
        field_type=spec.field_type,
        description=spec.description,
        default=spec.default,
        value=new_value,
    )

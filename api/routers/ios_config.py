# ABOUTME: Phase 4 Sprint 3 — iOS app config endpoint with deterministic config_version hash.
# ABOUTME: iOS caches the body, only re-fetches when the hash changes (Phase 5 will consume).
from __future__ import annotations

import hashlib
import json

import structlog
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.base import get_db
from database.models import (
    CategoryComponent,
    CategoryInspectionPrompt,
    CategoryRedFlagRule,
    EquipmentCategory,
    User,
)
from middleware.rbac import require_roles
from services import app_config_registry

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/ios", tags=["ios"])

# Phase 5 iOS app: appraisers (and admins for QA) hit this endpoint.
# Customers don't need it; locking down the role so the body
# (which leaks all categories + prompts) doesn't accidentally surface
# in any customer flow.
_require_field_user = require_roles("appraiser", "admin", "sales", "sales_manager")


@router.get("/config")
async def get_ios_config(
    _user: User = Depends(_require_field_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Returns the bundle the iOS app caches locally + a deterministic
    SHA-256 of the rest of the body. The app stores ``config_version``
    and only re-fetches when its cached hash differs from the server's.

    Bundle contents:
      - ``categories``         — active equipment categories, in display order
      - ``components``         — per-category scoring components + weights
      - ``inspection_prompts`` — current-version, active prompts (uses
        ``current_inspection_prompts``-style filter so superseded rows
        don't ship to device)
      - ``red_flag_rules``     — current-version, active red-flag rules
      - ``app_config``         — every registered AppConfig key + its
        live value (so the iOS app respects intake field visibility,
        calendar buffer, etc. without a redeploy)

    Phase 4 admin's category/prompt edits via Sprint 6 + AppConfig
    writes via Sprint 3 both bump this hash automatically — admin
    flips a key, iOS picks up the change at next app launch.
    """
    payload = await _build_body(db)
    payload["config_version"] = _hash_body(payload)
    return payload


async def _build_body(db: AsyncSession) -> dict:
    cats = await _fetch_categories(db)
    components = await _fetch_components(db)
    prompts = await _fetch_current_prompts(db)
    rules = await _fetch_current_rules(db)
    app_config_items = []
    for spec in app_config_registry.all_specs():
        value = await app_config_registry.get_typed(db, spec.name)
        app_config_items.append(
            {
                "name": spec.name,
                "category": spec.category,
                "field_type": spec.field_type,
                "value": value,
            }
        )
    return {
        "categories": cats,
        "components": components,
        "inspection_prompts": prompts,
        "red_flag_rules": rules,
        "app_config": app_config_items,
    }


async def _fetch_categories(db: AsyncSession) -> list[dict]:
    rows = (
        (
            await db.execute(
                select(EquipmentCategory)
                .where(
                    EquipmentCategory.status == "active",
                    EquipmentCategory.deleted_at.is_(None),
                )
                .order_by(EquipmentCategory.display_order, EquipmentCategory.id)
            )
        )
        .scalars()
        .all()
    )
    return [
        {
            "id": str(c.id),
            "name": c.name,
            "slug": c.slug,
            "display_order": c.display_order,
        }
        for c in rows
    ]


async def _fetch_components(db: AsyncSession) -> list[dict]:
    rows = (
        (
            await db.execute(
                select(CategoryComponent)
                .where(CategoryComponent.active.is_(True))
                .order_by(
                    CategoryComponent.category_id,
                    CategoryComponent.display_order,
                    CategoryComponent.id,
                )
            )
        )
        .scalars()
        .all()
    )
    return [
        {
            "id": str(c.id),
            "category_id": str(c.category_id),
            "name": c.name,
            # Numeric → str for stable JSON encoding (Decimal isn't JSON-
            # serializable by default and we hash the body deterministically).
            "weight_pct": str(c.weight_pct),
            "display_order": c.display_order,
        }
        for c in rows
    ]


async def _fetch_current_prompts(db: AsyncSession) -> list[dict]:
    rows = (
        (
            await db.execute(
                select(CategoryInspectionPrompt)
                .where(
                    CategoryInspectionPrompt.replaced_at.is_(None),
                    CategoryInspectionPrompt.active.is_(True),
                )
                .order_by(
                    CategoryInspectionPrompt.category_id,
                    CategoryInspectionPrompt.display_order,
                    CategoryInspectionPrompt.id,
                )
            )
        )
        .scalars()
        .all()
    )
    return [
        {
            "id": str(p.id),
            "category_id": str(p.category_id),
            "label": p.label,
            "response_type": p.response_type,
            "required": p.required,
            "display_order": p.display_order,
            "version": p.version,
        }
        for p in rows
    ]


async def _fetch_current_rules(db: AsyncSession) -> list[dict]:
    rows = (
        (
            await db.execute(
                select(CategoryRedFlagRule)
                .where(
                    CategoryRedFlagRule.replaced_at.is_(None),
                    CategoryRedFlagRule.active.is_(True),
                )
                .order_by(CategoryRedFlagRule.category_id, CategoryRedFlagRule.id)
            )
        )
        .scalars()
        .all()
    )
    return [
        {
            "id": str(r.id),
            "category_id": str(r.category_id),
            "label": r.label,
            "condition_field": r.condition_field,
            "condition_operator": r.condition_operator,
            "condition_value": r.condition_value,
            "actions": r.actions,
            "version": r.version,
        }
        for r in rows
    ]


def _hash_body(body: dict) -> str:
    """SHA-256 over the body with deterministic JSON encoding so the
    same content always hashes to the same string. ``sort_keys=True``
    + ``separators=(",", ":")`` removes whitespace + key-order
    nondeterminism."""
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

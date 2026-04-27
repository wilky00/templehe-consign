# ABOUTME: Phase 4 Sprint 6 — admin CRUD + export/import for equipment categories.
# ABOUTME: Wraps admin_category_service; admin-only; export emits JSON, import accepts JSON body.
from __future__ import annotations

import json
import uuid

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from database.base import get_db
from database.models import User
from middleware.rbac import require_roles
from schemas.admin import (
    AttachmentCreate,
    AttachmentPatch,
    CategoryCreate,
    CategoryDetail,
    CategoryExportPayload,
    CategoryImportResult,
    CategoryListResponse,
    CategoryOut,
    CategoryPatch,
    ComponentCreate,
    ComponentPatch,
    InspectionPromptCreate,
    InspectionPromptPatch,
    PhotoSlotCreate,
    PhotoSlotPatch,
    RedFlagRuleCreate,
    RedFlagRulePatch,
)
from services import admin_category_service

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/admin/categories", tags=["admin-categories"])

_require_admin = require_roles("admin")


@router.get("", response_model=CategoryListResponse)
async def list_categories(
    include_inactive: bool = Query(default=False),
    include_deleted: bool = Query(default=False),
    _admin: User = Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
) -> CategoryListResponse:
    cats = await admin_category_service.list_categories(
        db, include_inactive=include_inactive, include_deleted=include_deleted
    )
    return CategoryListResponse(categories=cats)


@router.post("", response_model=CategoryDetail, status_code=201)
async def create_category(
    payload: CategoryCreate,
    admin: User = Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
) -> CategoryDetail:
    return await admin_category_service.create_category(db, payload=payload, actor=admin)


@router.get("/{category_id}", response_model=CategoryDetail)
async def get_category(
    category_id: uuid.UUID,
    _admin: User = Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
) -> CategoryDetail:
    return await admin_category_service.get_category(db, category_id=category_id)


@router.patch("/{category_id}", response_model=CategoryDetail)
async def update_category(
    category_id: uuid.UUID,
    patch: CategoryPatch,
    admin: User = Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
) -> CategoryDetail:
    return await admin_category_service.update_category(
        db, category_id=category_id, patch=patch, actor=admin
    )


@router.post("/{category_id}/deactivate", response_model=CategoryDetail)
async def deactivate_category(
    category_id: uuid.UUID,
    admin: User = Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
) -> CategoryDetail:
    return await admin_category_service.deactivate_category(
        db, category_id=category_id, actor=admin
    )


@router.delete("/{category_id}", response_model=CategoryOut)
async def delete_category(
    category_id: uuid.UUID,
    admin: User = Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
) -> CategoryOut:
    return await admin_category_service.soft_delete_category(
        db, category_id=category_id, actor=admin
    )


# --- Components -------------------------------------------------------- #


@router.post("/{category_id}/components", response_model=CategoryDetail, status_code=201)
async def add_component(
    category_id: uuid.UUID,
    payload: ComponentCreate,
    admin: User = Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
) -> CategoryDetail:
    return await admin_category_service.add_component(
        db, category_id=category_id, payload=payload, actor=admin
    )


@router.patch("/{category_id}/components/{component_id}", response_model=CategoryDetail)
async def update_component(
    category_id: uuid.UUID,
    component_id: uuid.UUID,
    patch: ComponentPatch,
    admin: User = Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
) -> CategoryDetail:
    return await admin_category_service.update_component(
        db,
        category_id=category_id,
        component_id=component_id,
        patch=patch,
        actor=admin,
    )


# --- Inspection prompts ------------------------------------------------ #


@router.post(
    "/{category_id}/inspection-prompts",
    response_model=CategoryDetail,
    status_code=201,
)
async def add_inspection_prompt(
    category_id: uuid.UUID,
    payload: InspectionPromptCreate,
    admin: User = Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
) -> CategoryDetail:
    return await admin_category_service.add_inspection_prompt(
        db, category_id=category_id, payload=payload, actor=admin
    )


@router.patch(
    "/{category_id}/inspection-prompts/{prompt_id}",
    response_model=CategoryDetail,
)
async def update_inspection_prompt(
    category_id: uuid.UUID,
    prompt_id: uuid.UUID,
    patch: InspectionPromptPatch,
    admin: User = Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
) -> CategoryDetail:
    return await admin_category_service.update_inspection_prompt(
        db,
        category_id=category_id,
        prompt_id=prompt_id,
        patch=patch,
        actor=admin,
    )


# --- Red-flag rules ---------------------------------------------------- #


@router.post(
    "/{category_id}/red-flag-rules",
    response_model=CategoryDetail,
    status_code=201,
)
async def add_red_flag_rule(
    category_id: uuid.UUID,
    payload: RedFlagRuleCreate,
    admin: User = Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
) -> CategoryDetail:
    return await admin_category_service.add_red_flag_rule(
        db, category_id=category_id, payload=payload, actor=admin
    )


@router.patch(
    "/{category_id}/red-flag-rules/{rule_id}",
    response_model=CategoryDetail,
)
async def update_red_flag_rule(
    category_id: uuid.UUID,
    rule_id: uuid.UUID,
    patch: RedFlagRulePatch,
    admin: User = Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
) -> CategoryDetail:
    return await admin_category_service.update_red_flag_rule(
        db,
        category_id=category_id,
        rule_id=rule_id,
        patch=patch,
        actor=admin,
    )


# --- Attachments + photo slots ----------------------------------------- #


@router.post("/{category_id}/attachments", response_model=CategoryDetail, status_code=201)
async def add_attachment(
    category_id: uuid.UUID,
    payload: AttachmentCreate,
    admin: User = Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
) -> CategoryDetail:
    return await admin_category_service.add_attachment(
        db, category_id=category_id, payload=payload, actor=admin
    )


@router.patch("/{category_id}/attachments/{attachment_id}", response_model=CategoryDetail)
async def update_attachment(
    category_id: uuid.UUID,
    attachment_id: uuid.UUID,
    patch: AttachmentPatch,
    admin: User = Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
) -> CategoryDetail:
    return await admin_category_service.update_attachment(
        db,
        category_id=category_id,
        attachment_id=attachment_id,
        patch=patch,
        actor=admin,
    )


@router.post("/{category_id}/photo-slots", response_model=CategoryDetail, status_code=201)
async def add_photo_slot(
    category_id: uuid.UUID,
    payload: PhotoSlotCreate,
    admin: User = Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
) -> CategoryDetail:
    return await admin_category_service.add_photo_slot(
        db, category_id=category_id, payload=payload, actor=admin
    )


@router.patch("/{category_id}/photo-slots/{photo_slot_id}", response_model=CategoryDetail)
async def update_photo_slot(
    category_id: uuid.UUID,
    photo_slot_id: uuid.UUID,
    patch: PhotoSlotPatch,
    admin: User = Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
) -> CategoryDetail:
    return await admin_category_service.update_photo_slot(
        db,
        category_id=category_id,
        photo_slot_id=photo_slot_id,
        patch=patch,
        actor=admin,
    )


# --- Export / import --------------------------------------------------- #


@router.get("/{category_id}/export.json")
async def export_category(
    category_id: uuid.UUID,
    _admin: User = Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    payload = await admin_category_service.export_to_payload(db, category_id=category_id)
    body = json.loads(payload.model_dump_json())
    headers = {
        "Content-Disposition": f'attachment; filename="category-{payload.slug}.json"',
    }
    return JSONResponse(content=body, headers=headers)


@router.post("/import", response_model=CategoryImportResult)
async def import_category(
    payload: CategoryExportPayload,
    admin: User = Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
) -> CategoryImportResult:
    if not payload.slug:
        raise HTTPException(status_code=422, detail="Import payload requires a slug.")
    return await admin_category_service.import_from_payload(db, payload=payload, actor=admin)

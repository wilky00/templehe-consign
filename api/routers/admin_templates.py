# ABOUTME: Phase 4 Sprint 5 — admin reads + edits notification template overrides.
# ABOUTME: GET lists registered templates; PATCH writes / deletes the override row.
from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.base import get_db
from database.models import NotificationTemplateOverride, User
from middleware.rbac import require_roles
from schemas.admin import (
    NotificationTemplateListResponse,
    NotificationTemplateOut,
    NotificationTemplateOverrideRequest,
)
from services import notification_templates

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/admin/notification-templates", tags=["admin-templates"])

_require_admin = require_roles("admin")


async def _build_out(
    db: AsyncSession, spec: notification_templates.Template
) -> NotificationTemplateOut:
    override = (
        await db.execute(
            select(NotificationTemplateOverride).where(
                NotificationTemplateOverride.name == spec.name
            )
        )
    ).scalar_one_or_none()
    return NotificationTemplateOut(
        name=spec.name,
        channel=spec.channel,
        category=spec.category,
        description=spec.description,
        variables=list(spec.variables),
        subject_template=spec.subject_template,
        body_template=spec.body_template,
        has_override=override is not None,
        override_subject=override.subject_md if override else None,
        override_body=override.body_md if override else None,
    )


@router.get("", response_model=NotificationTemplateListResponse)
async def list_templates(
    _admin: User = Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
) -> NotificationTemplateListResponse:
    items = []
    for spec in notification_templates.all_specs():
        items.append(await _build_out(db, spec))
    return NotificationTemplateListResponse(templates=items)


@router.patch("/{name}", response_model=NotificationTemplateOut)
async def update_template_override(
    name: str,
    body: NotificationTemplateOverrideRequest,
    admin: User = Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
) -> NotificationTemplateOut:
    """Write or delete the override row for ``name``. Email templates
    accept both subject_md + body_md; SMS templates ignore subject_md.
    Pass ``delete=true`` to revert to the code default."""
    try:
        spec = notification_templates.get_spec(name)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Unknown template: {name}") from exc

    existing = (
        await db.execute(
            select(NotificationTemplateOverride).where(NotificationTemplateOverride.name == name)
        )
    ).scalar_one_or_none()

    if body.delete:
        if existing is not None:
            await db.delete(existing)
            await db.flush()
        return await _build_out(db, spec)

    if not body.body_md or not body.body_md.strip():
        raise HTTPException(status_code=422, detail="body_md is required.")
    if spec.channel == "email" and not (body.subject_md and body.subject_md.strip()):
        raise HTTPException(status_code=422, detail="subject_md is required for email templates.")

    if existing is None:
        db.add(
            NotificationTemplateOverride(
                name=name,
                subject_md=body.subject_md if spec.channel == "email" else None,
                body_md=body.body_md,
                updated_by=admin.id,
            )
        )
    else:
        existing.subject_md = body.subject_md if spec.channel == "email" else None
        existing.body_md = body.body_md
        existing.updated_by = admin.id
        db.add(existing)
    await db.flush()
    return await _build_out(db, spec)

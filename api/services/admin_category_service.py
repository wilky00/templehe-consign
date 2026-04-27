# ABOUTME: Phase 4 Sprint 6 — admin CRUD + export/import for equipment_categories.
# ABOUTME: Identity-affecting edits supersede; prompts + rules route through versioning service.
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from database.models import (
    AuditLog,
    CategoryAttachment,
    CategoryComponent,
    CategoryInspectionPrompt,
    CategoryPhotoSlot,
    CategoryRedFlagRule,
    EquipmentCategory,
    EquipmentRecord,
    User,
)
from schemas.admin import (
    AttachmentCreate,
    AttachmentPatch,
    CategoryAttachmentOut,
    CategoryComponentOut,
    CategoryCreate,
    CategoryDetail,
    CategoryExportPayload,
    CategoryImportResult,
    CategoryInspectionPromptOut,
    CategoryOut,
    CategoryPatch,
    CategoryPhotoSlotOut,
    CategoryRedFlagRuleOut,
    ComponentCreate,
    ComponentPatch,
    InspectionPromptCreate,
    InspectionPromptPatch,
    PhotoSlotCreate,
    PhotoSlotPatch,
    RedFlagRuleCreate,
    RedFlagRulePatch,
)
from services import category_versioning_service

# Components are scaled out of 100 in the admin UI; underlying column
# is Numeric(6,4). Floating-point sums can land at 99.9999998 — we
# tolerate a 0.5% gap before the warning fires.
_WEIGHT_WARNING_TOLERANCE = Decimal("0.5")
_WEIGHT_TARGET = Decimal("100")


def _serialize_category(cat: EquipmentCategory) -> CategoryOut:
    return CategoryOut(
        id=cat.id,
        name=cat.name,
        slug=cat.slug,
        status=cat.status,
        display_order=cat.display_order,
        version=cat.version,
        created_at=cat.created_at,
        updated_at=cat.updated_at,
        deleted_at=cat.deleted_at,
        replaced_at=cat.replaced_at,
    )


def _serialize_detail(cat: EquipmentCategory) -> CategoryDetail:
    components = sorted(cat.components or [], key=lambda c: (c.display_order, str(c.id)))
    # Only active components contribute to scoring weights — inactive ones
    # appear in the admin UI for re-enable but don't affect normalization.
    active_components = [c for c in components if c.active]
    weight_total = sum((c.weight_pct for c in active_components), Decimal("0"))
    # No warning when the category has no components yet — that's a
    # "not configured yet" state, not a misconfiguration.
    weight_warning = (
        len(active_components) > 0
        and abs(weight_total - _WEIGHT_TARGET) > _WEIGHT_WARNING_TOLERANCE
    )
    prompts = sorted(
        [p for p in (cat.inspection_prompts or []) if p.replaced_at is None],
        key=lambda p: (p.display_order, str(p.id)),
    )
    attachments = sorted(cat.attachments or [], key=lambda a: (a.display_order, str(a.id)))
    photo_slots = sorted(cat.photo_slots or [], key=lambda s: (s.display_order, str(s.id)))
    rules = [r for r in (cat.red_flag_rules or []) if r.replaced_at is None]

    base = _serialize_category(cat)
    return CategoryDetail(
        **base.model_dump(),
        components=[
            CategoryComponentOut(
                id=c.id,
                name=c.name,
                weight_pct=float(c.weight_pct),
                display_order=c.display_order,
                active=c.active,
            )
            for c in components
        ],
        inspection_prompts=[
            CategoryInspectionPromptOut(
                id=p.id,
                label=p.label,
                response_type=p.response_type,
                required=p.required,
                display_order=p.display_order,
                active=p.active,
                version=p.version,
            )
            for p in prompts
        ],
        attachments=[
            CategoryAttachmentOut(
                id=a.id,
                label=a.label,
                description=a.description,
                display_order=a.display_order,
                active=a.active,
            )
            for a in attachments
        ],
        photo_slots=[
            CategoryPhotoSlotOut(
                id=s.id,
                label=s.label,
                helper_text=s.helper_text,
                required=s.required,
                display_order=s.display_order,
                active=s.active,
            )
            for s in photo_slots
        ],
        red_flag_rules=[
            CategoryRedFlagRuleOut(
                id=r.id,
                label=r.label,
                condition_field=r.condition_field,
                condition_operator=r.condition_operator,
                condition_value=r.condition_value,
                actions=dict(r.actions or {}),
                active=r.active,
                version=r.version,
            )
            for r in rules
        ],
        weight_total=float(weight_total),
        weight_warning=weight_warning,
    )


async def _load_detail(db: AsyncSession, category_id: uuid.UUID) -> EquipmentCategory:
    stmt = (
        select(EquipmentCategory)
        .where(EquipmentCategory.id == category_id)
        .options(
            selectinload(EquipmentCategory.components),
            selectinload(EquipmentCategory.inspection_prompts),
            selectinload(EquipmentCategory.attachments),
            selectinload(EquipmentCategory.photo_slots),
            selectinload(EquipmentCategory.red_flag_rules),
        )
    )
    cat = (await db.execute(stmt)).scalar_one_or_none()
    if cat is None:
        raise HTTPException(status_code=404, detail="Category not found.")
    return cat


def _audit(
    db: AsyncSession,
    *,
    actor: User,
    event: str,
    target_id: uuid.UUID,
    before: dict | None,
    after: dict | None,
) -> None:
    db.add(
        AuditLog(
            event_type=event,
            actor_id=actor.id,
            actor_role="admin",
            target_type="equipment_category",
            target_id=target_id,
            before_state=before,
            after_state=after,
        )
    )


# --- Category-level CRUD --------------------------------------------------- #


async def list_categories(
    db: AsyncSession, *, include_inactive: bool = False, include_deleted: bool = False
) -> list[CategoryOut]:
    stmt = select(EquipmentCategory).where(EquipmentCategory.replaced_at.is_(None))
    if not include_deleted:
        stmt = stmt.where(EquipmentCategory.deleted_at.is_(None))
    if not include_inactive:
        stmt = stmt.where(EquipmentCategory.status == "active")
    stmt = stmt.order_by(EquipmentCategory.display_order, EquipmentCategory.name)
    rows = (await db.execute(stmt)).scalars().all()
    return [_serialize_category(c) for c in rows]


async def get_category(db: AsyncSession, *, category_id: uuid.UUID) -> CategoryDetail:
    cat = await _load_detail(db, category_id)
    return _serialize_detail(cat)


async def create_category(
    db: AsyncSession, *, payload: CategoryCreate, actor: User
) -> CategoryDetail:
    existing = await category_versioning_service.current_category_by_slug(db, slug=payload.slug)
    if existing is not None:
        raise HTTPException(status_code=409, detail=f"Slug '{payload.slug}' is already in use.")
    cat = EquipmentCategory(
        name=payload.name,
        slug=payload.slug,
        status="active",
        display_order=payload.display_order,
        created_by=actor.id,
    )
    db.add(cat)
    await db.flush()
    _audit(
        db,
        actor=actor,
        event="equipment_category.created",
        target_id=cat.id,
        before=None,
        after={"name": cat.name, "slug": cat.slug, "display_order": cat.display_order},
    )
    await db.flush()
    return await get_category(db, category_id=cat.id)


async def update_category(
    db: AsyncSession,
    *,
    category_id: uuid.UUID,
    patch: CategoryPatch,
    actor: User,
) -> CategoryDetail:
    cat = await _load_detail(db, category_id)
    if cat.replaced_at is not None or cat.deleted_at is not None:
        raise HTTPException(status_code=409, detail="Category is no longer current.")

    fields = patch.model_dump(exclude_unset=True)
    if not fields:
        raise HTTPException(status_code=400, detail="No fields to update.")

    if "slug" in fields and fields["slug"] != cat.slug:
        clash = await category_versioning_service.current_category_by_slug(db, slug=fields["slug"])
        if clash is not None and clash.id != cat.id:
            raise HTTPException(
                status_code=409,
                detail=f"Slug '{fields['slug']}' is already in use.",
            )

    before = {k: getattr(cat, k) for k in fields}
    successor = await category_versioning_service.supersede_category(
        db,
        existing=cat,
        new_name=fields.get("name"),
        new_slug=fields.get("slug"),
        new_display_order=fields.get("display_order"),
        new_status=fields.get("status"),
    )
    after = {k: getattr(successor, k) for k in fields}

    _audit(
        db,
        actor=actor,
        event="equipment_category.superseded",
        target_id=successor.id,
        before={"prior_id": str(cat.id), "prior_version": cat.version, **before},
        after={"version": successor.version, **after},
    )
    await db.flush()
    return await get_category(db, category_id=successor.id)


async def deactivate_category(
    db: AsyncSession, *, category_id: uuid.UUID, actor: User
) -> CategoryDetail:
    cat = await _load_detail(db, category_id)
    if cat.status == "inactive":
        return _serialize_detail(cat)
    return await update_category(
        db,
        category_id=category_id,
        patch=CategoryPatch(status="inactive"),
        actor=actor,
    )


async def soft_delete_category(
    db: AsyncSession, *, category_id: uuid.UUID, actor: User
) -> CategoryOut:
    """Hard-delete is rejected when ``equipment_records`` reference the
    category — admins should deactivate instead. This returns 409 with
    the in-use record count so the SPA can show the conflict."""
    cat = await _load_detail(db, category_id)
    if cat.deleted_at is not None:
        return _serialize_category(cat)

    in_use = (
        await db.execute(
            select(func.count())
            .select_from(EquipmentRecord)
            .where(
                EquipmentRecord.category_id == cat.id,
                EquipmentRecord.deleted_at.is_(None),
            )
        )
    ).scalar_one()
    if in_use > 0:
        raise HTTPException(
            status_code=409,
            detail=(
                f"{in_use} equipment record(s) still reference this category. "
                "Deactivate it instead, or reassign the records first."
            ),
        )

    cat.deleted_at = datetime.now(UTC)
    db.add(cat)
    await db.flush()
    _audit(
        db,
        actor=actor,
        event="equipment_category.soft_deleted",
        target_id=cat.id,
        before={"deleted_at": None},
        after={"deleted_at": cat.deleted_at.isoformat()},
    )
    await db.flush()
    return _serialize_category(cat)


# --- Components ------------------------------------------------------------ #


async def add_component(
    db: AsyncSession,
    *,
    category_id: uuid.UUID,
    payload: ComponentCreate,
    actor: User,
) -> CategoryDetail:
    await _load_detail(db, category_id)
    comp = CategoryComponent(
        category_id=category_id,
        name=payload.name,
        weight_pct=Decimal(str(payload.weight_pct)),
        display_order=payload.display_order,
        active=True,
    )
    db.add(comp)
    await db.flush()
    _audit(
        db,
        actor=actor,
        event="category_component.created",
        target_id=category_id,
        before=None,
        after={"component_id": str(comp.id), "name": comp.name, "weight_pct": str(comp.weight_pct)},
    )
    await db.flush()
    return await get_category(db, category_id=category_id)


async def update_component(
    db: AsyncSession,
    *,
    category_id: uuid.UUID,
    component_id: uuid.UUID,
    patch: ComponentPatch,
    actor: User,
) -> CategoryDetail:
    comp = (
        await db.execute(
            select(CategoryComponent).where(
                CategoryComponent.id == component_id,
                CategoryComponent.category_id == category_id,
            )
        )
    ).scalar_one_or_none()
    if comp is None:
        raise HTTPException(status_code=404, detail="Component not found.")
    fields = patch.model_dump(exclude_unset=True)
    if not fields:
        raise HTTPException(status_code=400, detail="No fields to update.")
    before = {k: (str(v) if isinstance(v := getattr(comp, k), Decimal) else v) for k in fields}
    if "weight_pct" in fields and fields["weight_pct"] is not None:
        fields["weight_pct"] = Decimal(str(fields["weight_pct"]))
    for k, v in fields.items():
        setattr(comp, k, v)
    db.add(comp)
    await db.flush()
    after = {k: (str(v) if isinstance(v := getattr(comp, k), Decimal) else v) for k in fields}
    _audit(
        db,
        actor=actor,
        event="category_component.updated",
        target_id=category_id,
        before={"component_id": str(comp.id), **before},
        after={"component_id": str(comp.id), **after},
    )
    await db.flush()
    return await get_category(db, category_id=category_id)


# --- Inspection prompts (versioned) --------------------------------------- #


async def add_inspection_prompt(
    db: AsyncSession,
    *,
    category_id: uuid.UUID,
    payload: InspectionPromptCreate,
    actor: User,
) -> CategoryDetail:
    await _load_detail(db, category_id)
    prompt = CategoryInspectionPrompt(
        category_id=category_id,
        label=payload.label,
        response_type=payload.response_type,
        required=payload.required,
        display_order=payload.display_order,
        active=True,
        version=1,
        replaced_at=None,
    )
    db.add(prompt)
    await db.flush()
    _audit(
        db,
        actor=actor,
        event="category_inspection_prompt.created",
        target_id=category_id,
        before=None,
        after={"prompt_id": str(prompt.id), "label": prompt.label, "version": prompt.version},
    )
    await db.flush()
    return await get_category(db, category_id=category_id)


async def update_inspection_prompt(
    db: AsyncSession,
    *,
    category_id: uuid.UUID,
    prompt_id: uuid.UUID,
    patch: InspectionPromptPatch,
    actor: User,
) -> CategoryDetail:
    """Identity-affecting edits supersede; flipping ``active`` is a
    pure UPDATE since the deactivation doesn't rewrite history."""
    existing = (
        await db.execute(
            select(CategoryInspectionPrompt).where(
                CategoryInspectionPrompt.id == prompt_id,
                CategoryInspectionPrompt.category_id == category_id,
            )
        )
    ).scalar_one_or_none()
    if existing is None:
        raise HTTPException(status_code=404, detail="Inspection prompt not found.")
    if existing.replaced_at is not None:
        raise HTTPException(status_code=409, detail="Inspection prompt is already superseded.")

    fields = patch.model_dump(exclude_unset=True)
    if not fields:
        raise HTTPException(status_code=400, detail="No fields to update.")

    # active toggle is non-versioned; route through UPDATE
    if set(fields.keys()) == {"active"}:
        existing.active = fields["active"]
        db.add(existing)
        await db.flush()
        _audit(
            db,
            actor=actor,
            event="category_inspection_prompt.activation_changed",
            target_id=category_id,
            before={"prompt_id": str(existing.id), "active": not fields["active"]},
            after={"prompt_id": str(existing.id), "active": fields["active"]},
        )
        await db.flush()
        return await get_category(db, category_id=category_id)

    successor = await category_versioning_service.supersede_inspection_prompt(
        db,
        existing=existing,
        new_label=fields.get("label"),
        new_response_type=fields.get("response_type"),
        new_required=fields.get("required"),
        new_display_order=fields.get("display_order"),
    )
    if "active" in fields and fields["active"] is not None:
        successor.active = fields["active"]
        db.add(successor)
        await db.flush()
    _audit(
        db,
        actor=actor,
        event="category_inspection_prompt.superseded",
        target_id=category_id,
        before={"prompt_id": str(existing.id), "version": existing.version},
        after={"prompt_id": str(successor.id), "version": successor.version},
    )
    await db.flush()
    return await get_category(db, category_id=category_id)


# --- Red-flag rules (versioned) ------------------------------------------- #


async def add_red_flag_rule(
    db: AsyncSession,
    *,
    category_id: uuid.UUID,
    payload: RedFlagRuleCreate,
    actor: User,
) -> CategoryDetail:
    await _load_detail(db, category_id)
    rule = CategoryRedFlagRule(
        category_id=category_id,
        label=payload.label,
        condition_field=payload.condition_field,
        condition_operator=payload.condition_operator,
        condition_value=payload.condition_value,
        actions=payload.actions,
        active=True,
        version=1,
        replaced_at=None,
    )
    db.add(rule)
    await db.flush()
    _audit(
        db,
        actor=actor,
        event="category_red_flag_rule.created",
        target_id=category_id,
        before=None,
        after={"rule_id": str(rule.id), "label": rule.label, "version": rule.version},
    )
    await db.flush()
    return await get_category(db, category_id=category_id)


async def update_red_flag_rule(
    db: AsyncSession,
    *,
    category_id: uuid.UUID,
    rule_id: uuid.UUID,
    patch: RedFlagRulePatch,
    actor: User,
) -> CategoryDetail:
    existing = (
        await db.execute(
            select(CategoryRedFlagRule).where(
                CategoryRedFlagRule.id == rule_id,
                CategoryRedFlagRule.category_id == category_id,
            )
        )
    ).scalar_one_or_none()
    if existing is None:
        raise HTTPException(status_code=404, detail="Red-flag rule not found.")
    if existing.replaced_at is not None:
        raise HTTPException(status_code=409, detail="Red-flag rule is already superseded.")

    fields = patch.model_dump(exclude_unset=True)
    if not fields:
        raise HTTPException(status_code=400, detail="No fields to update.")

    if set(fields.keys()) == {"active"}:
        existing.active = fields["active"]
        db.add(existing)
        await db.flush()
        _audit(
            db,
            actor=actor,
            event="category_red_flag_rule.activation_changed",
            target_id=category_id,
            before={"rule_id": str(existing.id), "active": not fields["active"]},
            after={"rule_id": str(existing.id), "active": fields["active"]},
        )
        await db.flush()
        return await get_category(db, category_id=category_id)

    successor = await category_versioning_service.supersede_red_flag_rule(
        db,
        existing=existing,
        new_condition_field=fields.get("condition_field"),
        new_condition_operator=fields.get("condition_operator"),
        new_condition_value=fields.get("condition_value"),
        new_actions=fields.get("actions"),
        new_label=fields.get("label"),
    )
    if "active" in fields and fields["active"] is not None:
        successor.active = fields["active"]
        db.add(successor)
        await db.flush()
    _audit(
        db,
        actor=actor,
        event="category_red_flag_rule.superseded",
        target_id=category_id,
        before={"rule_id": str(existing.id), "version": existing.version},
        after={"rule_id": str(successor.id), "version": successor.version},
    )
    await db.flush()
    return await get_category(db, category_id=category_id)


# --- Attachments + photo slots (non-versioned, simple UPDATE) ------------- #


async def add_attachment(
    db: AsyncSession,
    *,
    category_id: uuid.UUID,
    payload: AttachmentCreate,
    actor: User,
) -> CategoryDetail:
    await _load_detail(db, category_id)
    att = CategoryAttachment(
        category_id=category_id,
        label=payload.label,
        description=payload.description,
        display_order=payload.display_order,
        active=True,
    )
    db.add(att)
    await db.flush()
    _audit(
        db,
        actor=actor,
        event="category_attachment.created",
        target_id=category_id,
        before=None,
        after={"attachment_id": str(att.id), "label": att.label},
    )
    await db.flush()
    return await get_category(db, category_id=category_id)


async def update_attachment(
    db: AsyncSession,
    *,
    category_id: uuid.UUID,
    attachment_id: uuid.UUID,
    patch: AttachmentPatch,
    actor: User,
) -> CategoryDetail:
    att = (
        await db.execute(
            select(CategoryAttachment).where(
                CategoryAttachment.id == attachment_id,
                CategoryAttachment.category_id == category_id,
            )
        )
    ).scalar_one_or_none()
    if att is None:
        raise HTTPException(status_code=404, detail="Attachment not found.")
    fields = patch.model_dump(exclude_unset=True)
    if not fields:
        raise HTTPException(status_code=400, detail="No fields to update.")
    before = {k: getattr(att, k) for k in fields}
    for k, v in fields.items():
        setattr(att, k, v)
    db.add(att)
    await db.flush()
    after = {k: getattr(att, k) for k in fields}
    _audit(
        db,
        actor=actor,
        event="category_attachment.updated",
        target_id=category_id,
        before={"attachment_id": str(att.id), **before},
        after={"attachment_id": str(att.id), **after},
    )
    await db.flush()
    return await get_category(db, category_id=category_id)


async def add_photo_slot(
    db: AsyncSession,
    *,
    category_id: uuid.UUID,
    payload: PhotoSlotCreate,
    actor: User,
) -> CategoryDetail:
    await _load_detail(db, category_id)
    slot = CategoryPhotoSlot(
        category_id=category_id,
        label=payload.label,
        helper_text=payload.helper_text,
        required=payload.required,
        display_order=payload.display_order,
        active=True,
    )
    db.add(slot)
    await db.flush()
    _audit(
        db,
        actor=actor,
        event="category_photo_slot.created",
        target_id=category_id,
        before=None,
        after={"photo_slot_id": str(slot.id), "label": slot.label},
    )
    await db.flush()
    return await get_category(db, category_id=category_id)


async def update_photo_slot(
    db: AsyncSession,
    *,
    category_id: uuid.UUID,
    photo_slot_id: uuid.UUID,
    patch: PhotoSlotPatch,
    actor: User,
) -> CategoryDetail:
    slot = (
        await db.execute(
            select(CategoryPhotoSlot).where(
                CategoryPhotoSlot.id == photo_slot_id,
                CategoryPhotoSlot.category_id == category_id,
            )
        )
    ).scalar_one_or_none()
    if slot is None:
        raise HTTPException(status_code=404, detail="Photo slot not found.")
    fields = patch.model_dump(exclude_unset=True)
    if not fields:
        raise HTTPException(status_code=400, detail="No fields to update.")
    before = {k: getattr(slot, k) for k in fields}
    for k, v in fields.items():
        setattr(slot, k, v)
    db.add(slot)
    await db.flush()
    after = {k: getattr(slot, k) for k in fields}
    _audit(
        db,
        actor=actor,
        event="category_photo_slot.updated",
        target_id=category_id,
        before={"photo_slot_id": str(slot.id), **before},
        after={"photo_slot_id": str(slot.id), **after},
    )
    await db.flush()
    return await get_category(db, category_id=category_id)


# --- Export / import ------------------------------------------------------- #


async def export_to_payload(db: AsyncSession, *, category_id: uuid.UUID) -> CategoryExportPayload:
    cat = await _load_detail(db, category_id)
    return CategoryExportPayload(
        name=cat.name,
        slug=cat.slug,
        status=cat.status,
        display_order=cat.display_order,
        version=cat.version,
        replaced_at=cat.replaced_at,
        components=[
            {
                "name": c.name,
                "weight_pct": str(c.weight_pct),
                "display_order": c.display_order,
                "active": c.active,
            }
            for c in (cat.components or [])
        ],
        inspection_prompts=[
            {
                "label": p.label,
                "response_type": p.response_type,
                "required": p.required,
                "display_order": p.display_order,
                "active": p.active,
                "version": p.version,
                "replaced_at": p.replaced_at.isoformat() if p.replaced_at else None,
            }
            for p in (cat.inspection_prompts or [])
            if p.replaced_at is None
        ],
        attachments=[
            {
                "label": a.label,
                "description": a.description,
                "display_order": a.display_order,
                "active": a.active,
            }
            for a in (cat.attachments or [])
        ],
        photo_slots=[
            {
                "label": s.label,
                "helper_text": s.helper_text,
                "required": s.required,
                "display_order": s.display_order,
                "active": s.active,
            }
            for s in (cat.photo_slots or [])
        ],
        red_flag_rules=[
            {
                "label": r.label,
                "condition_field": r.condition_field,
                "condition_operator": r.condition_operator,
                "condition_value": r.condition_value,
                "actions": dict(r.actions or {}),
                "active": r.active,
                "version": r.version,
                "replaced_at": r.replaced_at.isoformat() if r.replaced_at else None,
            }
            for r in (cat.red_flag_rules or [])
            if r.replaced_at is None
        ],
    )


async def import_from_payload(
    db: AsyncSession, *, payload: CategoryExportPayload, actor: User
) -> CategoryImportResult:
    """Idempotent on slug. If no current category matches, create one.
    If one does, supersede prompts + rules whose body changed and add
    any new components / attachments / photo slots that don't already
    exist (matched by case-insensitive label). Existing items keep their
    IDs; nothing is deleted."""
    existing = await category_versioning_service.current_category_by_slug(db, slug=payload.slug)
    created = False
    if existing is None:
        existing = EquipmentCategory(
            name=payload.name,
            slug=payload.slug,
            status=payload.status,
            display_order=payload.display_order,
            created_by=actor.id,
        )
        db.add(existing)
        await db.flush()
        created = True

    existing = await _load_detail(db, existing.id)

    result = CategoryImportResult(category_id=existing.id, created=created)

    # Components — match on lowercase name; weight changes are a normal
    # UPDATE (component_scores already snapshots weight_at_time_of_scoring).
    by_name = {c.name.strip().lower(): c for c in (existing.components or [])}
    for c in payload.components:
        key = (c.get("name") or "").strip().lower()
        if not key:
            continue
        if key in by_name:
            comp = by_name[key]
            if comp.weight_pct != Decimal(str(c["weight_pct"])):
                comp.weight_pct = Decimal(str(c["weight_pct"]))
                db.add(comp)
        else:
            comp = CategoryComponent(
                category_id=existing.id,
                name=c["name"],
                weight_pct=Decimal(str(c["weight_pct"])),
                display_order=int(c.get("display_order", 0)),
                active=bool(c.get("active", True)),
            )
            db.add(comp)
            await db.flush()
            result.added_component_ids.append(comp.id)

    # Inspection prompts — match on lowercase label among current
    # versions. Body change → supersede; new label → insert.
    current_prompts = [p for p in (existing.inspection_prompts or []) if p.replaced_at is None]
    by_prompt_label = {p.label.strip().lower(): p for p in current_prompts}
    for p in payload.inspection_prompts:
        key = (p.get("label") or "").strip().lower()
        if not key:
            continue
        if key in by_prompt_label:
            curr = by_prompt_label[key]
            changed = (
                curr.response_type != p.get("response_type")
                or curr.required != p.get("required")
                or curr.display_order != p.get("display_order")
            )
            if changed:
                successor = await category_versioning_service.supersede_inspection_prompt(
                    db,
                    existing=curr,
                    new_response_type=p.get("response_type"),
                    new_required=p.get("required"),
                    new_display_order=p.get("display_order"),
                )
                result.superseded_prompt_ids.append(curr.id)
                result.added_prompt_ids.append(successor.id)
        else:
            new_prompt = CategoryInspectionPrompt(
                category_id=existing.id,
                label=p["label"],
                response_type=p["response_type"],
                required=bool(p.get("required", True)),
                display_order=int(p.get("display_order", 0)),
                active=bool(p.get("active", True)),
                version=1,
                replaced_at=None,
            )
            db.add(new_prompt)
            await db.flush()
            result.added_prompt_ids.append(new_prompt.id)

    # Attachments — match on lowercase label.
    by_att_label = {a.label.strip().lower(): a for a in (existing.attachments or [])}
    for a in payload.attachments:
        key = (a.get("label") or "").strip().lower()
        if not key or key in by_att_label:
            continue
        att = CategoryAttachment(
            category_id=existing.id,
            label=a["label"],
            description=a.get("description"),
            display_order=int(a.get("display_order", 0)),
            active=bool(a.get("active", True)),
        )
        db.add(att)
        await db.flush()
        result.added_attachment_ids.append(att.id)

    # Photo slots — match on lowercase label.
    by_slot_label = {s.label.strip().lower(): s for s in (existing.photo_slots or [])}
    for s in payload.photo_slots:
        key = (s.get("label") or "").strip().lower()
        if not key or key in by_slot_label:
            continue
        slot = CategoryPhotoSlot(
            category_id=existing.id,
            label=s["label"],
            helper_text=s.get("helper_text"),
            required=bool(s.get("required", True)),
            display_order=int(s.get("display_order", 0)),
            active=bool(s.get("active", True)),
        )
        db.add(slot)
        await db.flush()
        result.added_photo_slot_ids.append(slot.id)

    # Red-flag rules — match on lowercase label among current versions.
    current_rules = [r for r in (existing.red_flag_rules or []) if r.replaced_at is None]
    by_rule_label = {r.label.strip().lower(): r for r in current_rules}
    for r in payload.red_flag_rules:
        key = (r.get("label") or "").strip().lower()
        if not key:
            continue
        if key in by_rule_label:
            curr = by_rule_label[key]
            changed = (
                curr.condition_field != r.get("condition_field")
                or curr.condition_operator != r.get("condition_operator")
                or curr.condition_value != r.get("condition_value")
                or dict(curr.actions or {}) != dict(r.get("actions") or {})
            )
            if changed:
                successor = await category_versioning_service.supersede_red_flag_rule(
                    db,
                    existing=curr,
                    new_condition_field=r.get("condition_field"),
                    new_condition_operator=r.get("condition_operator"),
                    new_condition_value=r.get("condition_value"),
                    new_actions=r.get("actions"),
                )
                result.superseded_rule_ids.append(curr.id)
                result.added_rule_ids.append(successor.id)
        else:
            new_rule = CategoryRedFlagRule(
                category_id=existing.id,
                label=r["label"],
                condition_field=r["condition_field"],
                condition_operator=r["condition_operator"],
                condition_value=r.get("condition_value"),
                actions=r.get("actions") or {},
                active=bool(r.get("active", True)),
                version=1,
                replaced_at=None,
            )
            db.add(new_rule)
            await db.flush()
            result.added_rule_ids.append(new_rule.id)

    _audit(
        db,
        actor=actor,
        event="equipment_category.imported",
        target_id=existing.id,
        before={"created": False} if not created else None,
        after={
            "created": created,
            "added_components": [str(i) for i in result.added_component_ids],
            "superseded_prompts": [str(i) for i in result.superseded_prompt_ids],
            "added_prompts": [str(i) for i in result.added_prompt_ids],
            "superseded_rules": [str(i) for i in result.superseded_rule_ids],
            "added_rules": [str(i) for i in result.added_rule_ids],
            "added_attachments": [str(i) for i in result.added_attachment_ids],
            "added_photo_slots": [str(i) for i in result.added_photo_slot_ids],
        },
    )
    await db.flush()
    return result

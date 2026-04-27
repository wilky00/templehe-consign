# ABOUTME: Helpers for the version + replaced_at columns on prompt + red-flag tables.
# ABOUTME: "Current version" reads, "supersede in place" writes, "current at point in time" reads.
"""Category-asset versioning service.

``category_inspection_prompts`` and ``category_red_flag_rules`` carry
a ``version`` integer + ``replaced_at`` timestamp. Edits insert a new
row + flip ``replaced_at`` on the prior row instead of UPDATE-in-place,
so historical appraisals stay anchored to the prompt definition that
was current when they were authored.

Two read patterns:

- ``current_*`` — what should the iOS app show today? Returns rows
  with ``replaced_at IS NULL``.
- ``version_at(asset_id, instant)`` — what was current when this
  appraisal was authored? Returns the row whose ``replaced_at`` is
  either NULL or > ``instant``. Phase 7 PDF reports use this to
  reproduce historically accurate output.

One write pattern:

- ``supersede`` — caller passes the existing row + the new field
  values. We set ``replaced_at = NOW()`` on the existing row, insert
  a new row with ``version = old.version + 1`` and the new fields,
  and return the new row. Phase 4 admin write path is just this.

Phase 4 will surface CRUD on prompts + red-flag rules through this
module rather than inventing a parallel write path.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TypeVar

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import CategoryInspectionPrompt, CategoryRedFlagRule, EquipmentCategory

# Bound to the versioned models — all share the version + replaced_at columns.
Versioned = TypeVar(
    "Versioned",
    CategoryInspectionPrompt,
    CategoryRedFlagRule,
    EquipmentCategory,
)


async def current_inspection_prompts(
    db: AsyncSession, *, category_id: uuid.UUID
) -> list[CategoryInspectionPrompt]:
    """Active, current-version inspection prompts for ``category_id``.

    Filters to ``replaced_at IS NULL`` AND ``active = True`` so the
    iOS app sees the post-edit live set. Order: ``display_order`` then
    creation time.
    """
    stmt = (
        select(CategoryInspectionPrompt)
        .where(
            and_(
                CategoryInspectionPrompt.category_id == category_id,
                CategoryInspectionPrompt.replaced_at.is_(None),
                CategoryInspectionPrompt.active.is_(True),
            )
        )
        .order_by(CategoryInspectionPrompt.display_order, CategoryInspectionPrompt.id)
    )
    return list((await db.execute(stmt)).scalars().all())


async def current_red_flag_rules(
    db: AsyncSession, *, category_id: uuid.UUID
) -> list[CategoryRedFlagRule]:
    """Active, current-version red-flag rules for ``category_id``."""
    stmt = (
        select(CategoryRedFlagRule)
        .where(
            and_(
                CategoryRedFlagRule.category_id == category_id,
                CategoryRedFlagRule.replaced_at.is_(None),
                CategoryRedFlagRule.active.is_(True),
            )
        )
        .order_by(CategoryRedFlagRule.id)
    )
    return list((await db.execute(stmt)).scalars().all())


async def inspection_prompt_version_at(
    db: AsyncSession, *, prompt_id: uuid.UUID, instant: datetime
) -> CategoryInspectionPrompt | None:
    """Return the inspection-prompt row that was current at ``instant``.

    Use case: Phase 7 PDF report regenerated months after the appraisal
    needs the prompt label that was current at appraisal time, not the
    label after a later admin edit.
    """
    stmt = select(CategoryInspectionPrompt).where(
        and_(
            CategoryInspectionPrompt.id == prompt_id,
            or_(
                CategoryInspectionPrompt.replaced_at.is_(None),
                CategoryInspectionPrompt.replaced_at > instant,
            ),
        )
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def red_flag_rule_version_at(
    db: AsyncSession, *, rule_id: uuid.UUID, instant: datetime
) -> CategoryRedFlagRule | None:
    """Return the red-flag rule row that was current at ``instant``."""
    stmt = select(CategoryRedFlagRule).where(
        and_(
            CategoryRedFlagRule.id == rule_id,
            or_(
                CategoryRedFlagRule.replaced_at.is_(None),
                CategoryRedFlagRule.replaced_at > instant,
            ),
        )
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def supersede_inspection_prompt(
    db: AsyncSession,
    *,
    existing: CategoryInspectionPrompt,
    new_label: str | None = None,
    new_response_type: str | None = None,
    new_required: bool | None = None,
    new_display_order: int | None = None,
) -> CategoryInspectionPrompt:
    """Mark ``existing`` superseded and insert a successor row.

    Each ``new_*`` arg is optional — unset args inherit from the prior
    version. The successor uses a fresh UUID; the link between
    versions is implicit (the writer of ``field_values`` keeps the
    prompt_id of the version it answered).
    """
    now = datetime.now(UTC)
    existing.replaced_at = now
    db.add(existing)

    successor = CategoryInspectionPrompt(
        category_id=existing.category_id,
        label=new_label if new_label is not None else existing.label,
        response_type=(
            new_response_type if new_response_type is not None else existing.response_type
        ),
        required=new_required if new_required is not None else existing.required,
        display_order=(
            new_display_order if new_display_order is not None else existing.display_order
        ),
        active=existing.active,
        version=existing.version + 1,
        replaced_at=None,
    )
    db.add(successor)
    await db.flush()
    return successor


async def supersede_red_flag_rule(
    db: AsyncSession,
    *,
    existing: CategoryRedFlagRule,
    new_condition_field: str | None = None,
    new_condition_operator: str | None = None,
    new_condition_value: str | None = None,
    new_actions: dict | None = None,
    new_label: str | None = None,
) -> CategoryRedFlagRule:
    """Mark ``existing`` superseded and insert a successor row.

    Same shape as ``supersede_inspection_prompt``; see that docstring.
    """
    now = datetime.now(UTC)
    existing.replaced_at = now
    db.add(existing)

    successor = CategoryRedFlagRule(
        category_id=existing.category_id,
        condition_field=(
            new_condition_field if new_condition_field is not None else existing.condition_field
        ),
        condition_operator=(
            new_condition_operator
            if new_condition_operator is not None
            else existing.condition_operator
        ),
        condition_value=(
            new_condition_value if new_condition_value is not None else existing.condition_value
        ),
        actions=new_actions if new_actions is not None else existing.actions,
        label=new_label if new_label is not None else existing.label,
        active=existing.active,
        version=existing.version + 1,
        replaced_at=None,
    )
    db.add(successor)
    await db.flush()
    return successor


async def current_category_by_slug(db: AsyncSession, *, slug: str) -> EquipmentCategory | None:
    """Return the current, non-deleted category for ``slug`` if any.

    "Current" = ``replaced_at IS NULL AND deleted_at IS NULL``. This
    matches the partial unique index from migration 019 so the lookup
    is a single index seek.
    """
    stmt = select(EquipmentCategory).where(
        and_(
            EquipmentCategory.slug == slug,
            EquipmentCategory.replaced_at.is_(None),
            EquipmentCategory.deleted_at.is_(None),
        )
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def supersede_category(
    db: AsyncSession,
    *,
    existing: EquipmentCategory,
    new_name: str | None = None,
    new_slug: str | None = None,
    new_display_order: int | None = None,
    new_status: str | None = None,
) -> EquipmentCategory:
    """Mark ``existing`` superseded and insert a successor row.

    Use this for identity-affecting edits (rename, slug change, status flip)
    so historical appraisals stay anchored to the category definition they
    were authored against. Trivial display_order tweaks could in principle
    UPDATE in place; we still route them through supersede here for a
    single, predictable edit path.

    The successor inherits ``created_by`` and ``created_at`` from the
    prior version; ``updated_at`` is fresh.
    """
    now = datetime.now(UTC)
    existing.replaced_at = now
    db.add(existing)

    successor = EquipmentCategory(
        name=new_name if new_name is not None else existing.name,
        slug=new_slug if new_slug is not None else existing.slug,
        status=new_status if new_status is not None else existing.status,
        display_order=(
            new_display_order if new_display_order is not None else existing.display_order
        ),
        created_by=existing.created_by,
        version=existing.version + 1,
        replaced_at=None,
    )
    db.add(successor)
    await db.flush()
    return successor

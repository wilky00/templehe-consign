# ABOUTME: Integration tests for the inspection-prompt + red-flag-rule versioning helpers.
# ABOUTME: Exercises supersede + current vs version-at-instant reads against the live DB.
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import (
    CategoryInspectionPrompt,
    CategoryRedFlagRule,
    EquipmentCategory,
)
from services import category_versioning_service


@pytest.fixture
async def category(db_session: AsyncSession) -> EquipmentCategory:
    cat = EquipmentCategory(
        name=f"Test Category {uuid.uuid4().hex[:6]}",
        slug=f"test-cat-{uuid.uuid4().hex[:8]}",
    )
    db_session.add(cat)
    await db_session.flush()
    return cat


# ---------------------------------------------------------------------------
# Inspection prompts
# ---------------------------------------------------------------------------


async def test_new_prompt_starts_at_version_1(
    db_session: AsyncSession, category: EquipmentCategory
):
    prompt = CategoryInspectionPrompt(
        category_id=category.id,
        label="Hour meter reading?",
        response_type="text",
    )
    db_session.add(prompt)
    await db_session.flush()
    assert prompt.version == 1
    assert prompt.replaced_at is None


async def test_supersede_inserts_v2_and_marks_v1_replaced(
    db_session: AsyncSession, category: EquipmentCategory
):
    v1 = CategoryInspectionPrompt(
        category_id=category.id,
        label="Hour meter reading?",
        response_type="text",
    )
    db_session.add(v1)
    await db_session.flush()

    v2 = await category_versioning_service.supersede_inspection_prompt(
        db_session,
        existing=v1,
        new_label="Hours on meter?",
    )
    assert v2.version == 2
    assert v2.label == "Hours on meter?"
    assert v2.replaced_at is None
    # Inherited fields stay.
    assert v2.response_type == "text"
    assert v2.category_id == category.id

    # v1 is now superseded.
    await db_session.refresh(v1)
    assert v1.replaced_at is not None


async def test_current_inspection_prompts_returns_only_unsuperseded_active_rows(
    db_session: AsyncSession, category: EquipmentCategory
):
    keep = CategoryInspectionPrompt(category_id=category.id, label="Keep me", response_type="text")
    superseded = CategoryInspectionPrompt(
        category_id=category.id, label="Old", response_type="text"
    )
    inactive = CategoryInspectionPrompt(
        category_id=category.id, label="Off", response_type="text", active=False
    )
    db_session.add_all([keep, superseded, inactive])
    await db_session.flush()

    # Supersede one of them so we have a non-current row in the table.
    await category_versioning_service.supersede_inspection_prompt(
        db_session, existing=superseded, new_label="Newer"
    )

    current = await category_versioning_service.current_inspection_prompts(
        db_session, category_id=category.id
    )
    labels = {p.label for p in current}
    assert "Keep me" in labels
    assert "Newer" in labels
    assert "Old" not in labels  # superseded
    assert "Off" not in labels  # active=False


async def test_version_at_returns_pre_edit_row_for_pre_edit_instant(
    db_session: AsyncSession, category: EquipmentCategory
):
    v1 = CategoryInspectionPrompt(category_id=category.id, label="Original", response_type="text")
    db_session.add(v1)
    await db_session.flush()
    pre_edit = datetime.now(UTC) - timedelta(seconds=1)

    await category_versioning_service.supersede_inspection_prompt(
        db_session, existing=v1, new_label="Edited"
    )
    # v1 was current at pre_edit.
    historic = await category_versioning_service.inspection_prompt_version_at(
        db_session, prompt_id=v1.id, instant=pre_edit
    )
    assert historic is not None
    assert historic.id == v1.id
    assert historic.label == "Original"


async def test_version_at_returns_none_for_post_edit_lookup_of_old_version(
    db_session: AsyncSession, category: EquipmentCategory
):
    v1 = CategoryInspectionPrompt(category_id=category.id, label="Original", response_type="text")
    db_session.add(v1)
    await db_session.flush()
    await category_versioning_service.supersede_inspection_prompt(
        db_session, existing=v1, new_label="Edited"
    )
    far_future = datetime.now(UTC) + timedelta(hours=1)
    # v1's replaced_at is in the past; it's NOT current at far_future.
    result = await category_versioning_service.inspection_prompt_version_at(
        db_session, prompt_id=v1.id, instant=far_future
    )
    assert result is None


# ---------------------------------------------------------------------------
# Red-flag rules
# ---------------------------------------------------------------------------


async def test_supersede_red_flag_rule_inserts_v2(
    db_session: AsyncSession, category: EquipmentCategory
):
    v1 = CategoryRedFlagRule(
        category_id=category.id,
        condition_field="title_status",
        condition_operator="equals",
        condition_value="missing",
        actions={"hold_for_title_review": True},
        label="Missing title",
    )
    db_session.add(v1)
    await db_session.flush()

    v2 = await category_versioning_service.supersede_red_flag_rule(
        db_session,
        existing=v1,
        new_label="Title not on file",
    )
    assert v2.version == 2
    assert v2.label == "Title not on file"
    assert v2.condition_field == "title_status"
    assert v2.actions == {"hold_for_title_review": True}
    assert v2.replaced_at is None

    await db_session.refresh(v1)
    assert v1.replaced_at is not None


async def test_current_red_flag_rules_filters_superseded_and_inactive(
    db_session: AsyncSession, category: EquipmentCategory
):
    keep = CategoryRedFlagRule(
        category_id=category.id,
        condition_field="hours",
        condition_operator="equals",
        condition_value="0",
        actions={},
        label="Zero hours",
    )
    inactive = CategoryRedFlagRule(
        category_id=category.id,
        condition_field="hours",
        condition_operator="equals",
        condition_value="-1",
        actions={},
        label="Inactive",
        active=False,
    )
    superseded = CategoryRedFlagRule(
        category_id=category.id,
        condition_field="vin",
        condition_operator="is_false",
        condition_value=None,
        actions={},
        label="No VIN",
    )
    db_session.add_all([keep, inactive, superseded])
    await db_session.flush()
    await category_versioning_service.supersede_red_flag_rule(
        db_session, existing=superseded, new_label="No serial"
    )

    current = await category_versioning_service.current_red_flag_rules(
        db_session, category_id=category.id
    )
    labels = {r.label for r in current}
    assert "Zero hours" in labels
    assert "No serial" in labels
    assert "Inactive" not in labels
    assert "No VIN" not in labels


# ---------------------------------------------------------------------------
# Category-level supersede (Phase 4 Sprint 6)
# ---------------------------------------------------------------------------


async def test_supersede_category_inserts_v2_and_marks_v1_replaced(
    db_session: AsyncSession,
):
    slug = f"sup-{uuid.uuid4().hex[:8]}"
    v1 = EquipmentCategory(name="Skid Steers", slug=slug, status="active")
    db_session.add(v1)
    await db_session.flush()
    assert v1.version == 1
    assert v1.replaced_at is None

    v2 = await category_versioning_service.supersede_category(
        db_session, existing=v1, new_name="Skid Steer Loaders"
    )
    assert v2.version == 2
    assert v2.name == "Skid Steer Loaders"
    assert v2.slug == slug
    assert v2.replaced_at is None

    await db_session.refresh(v1)
    assert v1.replaced_at is not None


async def test_current_category_by_slug_returns_only_current(
    db_session: AsyncSession,
):
    slug = f"slugtest-{uuid.uuid4().hex[:8]}"
    v1 = EquipmentCategory(name="V1", slug=slug, status="active")
    db_session.add(v1)
    await db_session.flush()
    v2 = await category_versioning_service.supersede_category(
        db_session, existing=v1, new_name="V2"
    )

    found = await category_versioning_service.current_category_by_slug(db_session, slug=slug)
    assert found is not None
    assert found.id == v2.id
    assert found.name == "V2"


async def test_current_category_by_slug_skips_deleted(
    db_session: AsyncSession,
):
    slug = f"deleted-{uuid.uuid4().hex[:8]}"
    cat = EquipmentCategory(
        name="Soon to delete",
        slug=slug,
        status="active",
        deleted_at=datetime.now(UTC),
    )
    db_session.add(cat)
    await db_session.flush()

    found = await category_versioning_service.current_category_by_slug(db_session, slug=slug)
    assert found is None

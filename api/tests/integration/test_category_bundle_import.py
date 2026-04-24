# ABOUTME: Phase 2 Sprint 2 tests for scripts/import_category_bundle.
# ABOUTME: Verifies idempotency, child-table population, and the three starter categories.
from __future__ import annotations

import os
import sys

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# scripts/ is a sibling of api/; make it importable once per test process.
_SCRIPTS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "scripts"))
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from import_category_bundle import (  # noqa: E402
    CATEGORY_BUNDLE,
    import_bundle,
    import_category,
)

from database.models import (  # noqa: E402
    CategoryAttachment,
    CategoryComponent,
    CategoryInspectionPrompt,
    CategoryPhotoSlot,
    CategoryRedFlagRule,
    EquipmentCategory,
)

_STARTER_SLUGS = ("dozers", "backhoe-loaders", "articulated-dump-trucks")


# ---------------------------------------------------------------------------
# Seed-injected: the three starter categories already exist after `make dev`
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_seed_has_three_starter_categories(db_session: AsyncSession):
    result = await db_session.execute(
        select(EquipmentCategory).where(EquipmentCategory.slug.in_(_STARTER_SLUGS))
    )
    slugs = {c.slug for c in result.scalars().all()}
    assert slugs == set(_STARTER_SLUGS)


@pytest.mark.asyncio
async def test_seed_populates_all_child_tables_for_dozers(db_session: AsyncSession):
    cat_result = await db_session.execute(
        select(EquipmentCategory).where(EquipmentCategory.slug == "dozers")
    )
    cat = cat_result.scalar_one()

    comp = await db_session.execute(
        select(CategoryComponent).where(CategoryComponent.category_id == cat.id)
    )
    comps = list(comp.scalars().all())
    assert len(comps) == 8
    comp_names = [c.name for c in comps]
    assert "Engine" in comp_names
    assert "Undercarriage" in comp_names

    prompts = await db_session.execute(
        select(CategoryInspectionPrompt).where(CategoryInspectionPrompt.category_id == cat.id)
    )
    assert len(list(prompts.scalars().all())) == 10

    photos = await db_session.execute(
        select(CategoryPhotoSlot).where(CategoryPhotoSlot.category_id == cat.id)
    )
    photo_rows = list(photos.scalars().all())
    assert len(photo_rows) == 10
    assert all(p.required for p in photo_rows)

    attachments = await db_session.execute(
        select(CategoryAttachment).where(CategoryAttachment.category_id == cat.id)
    )
    assert len(list(attachments.scalars().all())) == 8

    rules = await db_session.execute(
        select(CategoryRedFlagRule).where(CategoryRedFlagRule.category_id == cat.id)
    )
    rule_rows = list(rules.scalars().all())
    assert len(rule_rows) == 5
    # Every rule has structured actions JSON — serves as a contract check.
    for r in rule_rows:
        assert isinstance(r.actions, dict)
        assert r.actions  # non-empty


# ---------------------------------------------------------------------------
# Importer behavior (idempotency + unknown slug)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_import_category_skips_when_slug_exists(db_session: AsyncSession):
    """Re-running the importer against an already-seeded slug must no-op."""
    inserted = await import_category(db_session, "dozers", CATEGORY_BUNDLE["dozers"])
    assert inserted is False

    # Component count did not double.
    cat_result = await db_session.execute(
        select(EquipmentCategory).where(EquipmentCategory.slug == "dozers")
    )
    cat = cat_result.scalar_one()
    comp = await db_session.execute(
        select(CategoryComponent).where(CategoryComponent.category_id == cat.id)
    )
    assert len(list(comp.scalars().all())) == 8


@pytest.mark.asyncio
async def test_import_bundle_unknown_slug_is_ignored(db_session: AsyncSession):
    inserted = await import_bundle(db_session, slugs=["not-a-real-category"])
    assert inserted == []


@pytest.mark.asyncio
async def test_component_weights_sum_close_to_100(db_session: AsyncSession):
    """Sanity: each category's component weights should roughly add to 100%.

    Rounding in the bundle CSV means exact 100 is not guaranteed, but we
    should be within 1 percentage point — a larger drift means a mapping
    bug in the importer.
    """
    for slug in _STARTER_SLUGS:
        cat_result = await db_session.execute(
            select(EquipmentCategory).where(EquipmentCategory.slug == slug)
        )
        cat = cat_result.scalar_one()
        comp_rows = await db_session.execute(
            select(CategoryComponent).where(CategoryComponent.category_id == cat.id)
        )
        total = sum(float(c.weight_pct) for c in comp_rows.scalars().all())
        assert 99.0 <= total <= 101.0, f"{slug} weights sum to {total}"

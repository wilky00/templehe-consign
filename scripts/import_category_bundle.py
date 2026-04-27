# ABOUTME: Seeds equipment_categories + child tables from the Heavy Equipment Appraisal Master Bundle.
# ABOUTME: Idempotent — skips a category entirely when its slug already exists. Phase 4 Admin Panel handles updates.
"""Importer for the starter-set equipment categories.

Reads component weights from the bundle scoring CSV and combines them
with hand-curated inspection prompts / photo slots / attachments pulled
from the checklist markdown. Kept inline as a single dict rather than
parsing the markdown at import time — makes the seed deterministic and
reviewable in source control.

Sprint 2 seeds three categories (Dozers, Backhoe Loaders, Articulated
Dump Trucks). The remaining 14 categories from the bundle land in
Phase 4 Admin Panel's bulk-import flow (see dev_plan/04).

Run via scripts/seed.py, or standalone:

    cd api && DATABASE_URL=postgresql+asyncpg://... \
        uv run python ../scripts/import_category_bundle.py
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from decimal import Decimal
from typing import Any

# Make api/ importable whether we're invoked from scripts/ or api/.
_HERE = os.path.dirname(os.path.abspath(__file__))
_API_DIR = os.path.join(os.path.dirname(_HERE), "api")
if _API_DIR not in sys.path:
    sys.path.insert(0, _API_DIR)

from sqlalchemy import select  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine  # noqa: E402
from sqlalchemy.pool import NullPool  # noqa: E402

from database.models import (  # noqa: E402
    CategoryAttachment,
    CategoryComponent,
    CategoryInspectionPrompt,
    CategoryPhotoSlot,
    CategoryRedFlagRule,
    EquipmentCategory,
)

logger = logging.getLogger("category_bundle")


# The bundle ships five shared red flag rules per category — same condition
# expressions, same actions, only the label differs by category. Kept in a
# helper so each category dict stays small.
def _shared_red_flags() -> list[dict[str, Any]]:
    return [
        {
            "condition_field": "structural_damage",
            "condition_operator": "is_true",
            "condition_value": None,
            "label": "Structural damage (cracks, poor repairs, bent frame/body/boom/blade)",
            "actions": {
                "set": {"management_review_required": True},
                "marketability_downgrade": 1,
            },
        },
        {
            "condition_field": "active_major_leak",
            "condition_operator": "is_true",
            "condition_value": None,
            "label": "Active major leak (hydraulic, engine, coolant, drivetrain)",
            "actions": {"set": {"management_review_required": True}},
        },
        {
            "condition_field": "missing_serial_plate",
            "condition_operator": "is_true",
            "condition_value": None,
            "label": "Missing or unreadable serial plate (identity risk)",
            "actions": {"set": {"hold_for_title_review": True}},
        },
        {
            "condition_field": "running_status",
            "condition_operator": "equals",
            "condition_value": "not_running",
            "label": "Unit is non-running",
            "actions": {
                "set": {
                    "management_review_required": True,
                    "marketability_rating": "salvage_risk",
                }
            },
        },
        {
            "condition_field": "hours_verified",
            "condition_operator": "is_false",
            "condition_value": None,
            "label": "Hours not verified — review meter history",
            "actions": {"append_review_note": "verify hours history"},
        },
    ]


# Component weights come from project_notes/heavy_equipment_appraisal_master_bundle/
# 03_implementation_package/06_scoring_and_rules_logic.csv rows of type
# component_weight. Inspection prompts / attachments / photo slots come from
# the per-category checklist markdown in 01_checklists/.
CATEGORY_BUNDLE: dict[str, dict[str, Any]] = {
    "dozers": {
        "name": "Dozers",
        "display_order": 10,
        "components": [
            ("Engine", "18.18"),
            ("Transmission/steering", "13.64"),
            ("Final drives", "10.91"),
            ("Undercarriage", "18.18"),
            ("Blade assembly", "10.91"),
            ("Ripper assembly", "5.45"),
            ("Hydraulic system", "13.64"),
            ("Cab/controls", "9.09"),
        ],
        "inspection_prompts": [
            "Cold start",
            "Blow-by",
            "Undercarriage wear",
            "Final drive noise/leaks",
            "Blade push arm wear",
            "Trunnion wear",
            "Ripper frame wear",
            "Steering response",
            "Hydraulic leaks",
            "Cab/AC condition",
        ],
        "attachments": [
            "PAT blade",
            "SU blade",
            "U blade",
            "Winch",
            "Single shank ripper",
            "Multi-shank ripper",
            "Sweeps",
            "Rear screen",
        ],
        "photo_slots": [
            "4 corner exterior",
            "Serial plate",
            "Hour meter",
            "Cab interior",
            "Engine compartment",
            "Both track sides",
            "Sprockets/idlers/rollers",
            "Blade cutting edge",
            "Ripper",
            "Visible leaks/damage",
        ],
    },
    "backhoe-loaders": {
        "name": "Backhoe Loaders",
        "display_order": 20,
        "components": [
            ("Engine", "19.05"),
            ("Transmission/driveline", "14.29"),
            ("Loader assembly", "9.52"),
            ("Backhoe assembly", "9.52"),
            ("Hydraulic system", "14.29"),
            ("Pins/bushings", "9.52"),
            ("Tires", "14.29"),
            ("Cab/controls", "9.52"),
        ],
        "inspection_prompts": [
            "Cold start",
            "Hydraulic drift",
            "Stabilizer hold",
            "Swing frame wear",
            "Boom/stick welds",
            "Pin looseness",
            "Bucket cutting edge",
            "4WD engagement",
            "Tire condition",
            "Cab controls",
        ],
        "attachments": [
            "General purpose bucket",
            "4-in-1 bucket",
            "Extendahoe",
            "Quick coupler",
            "Forks",
            "Hydraulic hammer circuit",
            "Thumb",
            "Auger",
        ],
        "photo_slots": [
            "4 corner exterior",
            "Serial plate",
            "Hour meter",
            "Cab or operator station",
            "Engine compartment",
            "Loader bucket edge",
            "Backhoe bucket teeth",
            "Outriggers",
            "Tires",
            "Visible leaks/damage",
        ],
    },
    "articulated-dump-trucks": {
        "name": "Articulated Dump Trucks",
        "display_order": 30,
        "components": [
            ("Engine", "18.69"),
            ("Transmission", "14.02"),
            ("Center hitch/articulation", "9.35"),
            ("Hydraulic system", "14.02"),
            ("Axles/differentials", "9.35"),
            ("Tires", "14.02"),
            ("Cab/interior", "9.35"),
            ("Body/chassis", "11.21"),
        ],
        "inspection_prompts": [
            "Cold start",
            "Exhaust smoke",
            "Fluid leaks",
            "Transmission shift quality",
            "Center hitch play",
            "Body floor wear",
            "Cylinder leakage",
            "Tire matching",
            "Brake performance",
            "Cab electronics",
        ],
        "attachments": [
            "Tailgate",
            "Body liner",
            "Heated body",
            "Payload weighing system",
            "Camera system",
            "Fire suppression",
        ],
        "photo_slots": [
            "4 corner exterior",
            "Serial plate",
            "Hour meter",
            "Cab interior",
            "Engine compartment",
            "Center hitch close-up",
            "All tires",
            "Dump body floor",
            "Visible leaks/damage",
        ],
    },
}


async def import_category(db: AsyncSession, slug: str, data: dict[str, Any]) -> bool:
    """Insert the category + all children if the slug is new. Returns True on insert.

    "Slug exists" means a current, non-deleted row with this slug — migration 019
    allows superseded rows to share a slug with their successor, so the lookup
    has to scope to ``replaced_at IS NULL AND deleted_at IS NULL``.
    """
    existing = await db.execute(
        select(EquipmentCategory).where(
            EquipmentCategory.slug == slug,
            EquipmentCategory.replaced_at.is_(None),
            EquipmentCategory.deleted_at.is_(None),
        )
    )
    if existing.scalar_one_or_none() is not None:
        logger.info("category_already_seeded slug=%s", slug)
        return False

    category = EquipmentCategory(
        name=data["name"],
        slug=slug,
        status="active",
        display_order=data.get("display_order", 0),
    )
    db.add(category)
    await db.flush()

    for order, (name, weight) in enumerate(data["components"]):
        db.add(
            CategoryComponent(
                category_id=category.id,
                name=name,
                weight_pct=Decimal(weight),
                display_order=order,
                active=True,
            )
        )
    for order, label in enumerate(data["inspection_prompts"]):
        db.add(
            CategoryInspectionPrompt(
                category_id=category.id,
                label=label,
                response_type="scale_1_5",
                required=True,
                display_order=order,
                active=True,
            )
        )
    for order, label in enumerate(data["attachments"]):
        db.add(
            CategoryAttachment(
                category_id=category.id,
                label=label,
                description=None,
                display_order=order,
                active=True,
            )
        )
    for order, label in enumerate(data["photo_slots"]):
        db.add(
            CategoryPhotoSlot(
                category_id=category.id,
                label=label,
                helper_text=None,
                required=True,
                display_order=order,
                active=True,
            )
        )
    for rule in _shared_red_flags():
        db.add(
            CategoryRedFlagRule(
                category_id=category.id,
                condition_field=rule["condition_field"],
                condition_operator=rule["condition_operator"],
                condition_value=rule["condition_value"],
                actions=rule["actions"],
                label=rule["label"],
                active=True,
            )
        )

    await db.flush()
    logger.info(
        "category_seeded slug=%s components=%d prompts=%d attachments=%d photos=%d",
        slug,
        len(data["components"]),
        len(data["inspection_prompts"]),
        len(data["attachments"]),
        len(data["photo_slots"]),
    )
    return True


async def import_bundle(db: AsyncSession, slugs: list[str] | None = None) -> list[str]:
    """Import the named slugs (or all CATEGORY_BUNDLE entries). Returns slugs actually inserted."""
    target = slugs if slugs is not None else list(CATEGORY_BUNDLE.keys())
    inserted = []
    for slug in target:
        if slug not in CATEGORY_BUNDLE:
            logger.warning("unknown_bundle_slug slug=%s", slug)
            continue
        if await import_category(db, slug, CATEGORY_BUNDLE[slug]):
            inserted.append(slug)
    return inserted


async def _main() -> None:
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        sys.exit("DATABASE_URL is required.")
    engine = create_async_engine(database_url, poolclass=NullPool, echo=False)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with session_factory() as session:
            inserted = await import_bundle(session)
            await session.commit()
        logger.info("bundle_import_complete inserted=%s", inserted)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(_main())

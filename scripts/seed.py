# ABOUTME: Idempotent database seeder — roles, equipment categories, app config, and admin user.
# ABOUTME: Run via `make seed`. Safe to run multiple times; uses INSERT ... ON CONFLICT DO NOTHING.
from __future__ import annotations

import asyncio
import os
import sys
import uuid

# Allow running from project root or scripts/ directly
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))

from passlib.context import CryptContext
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql+asyncpg://templehe:devpassword@localhost:5432/templehe")

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# --------------------------------------------------------------------------- #
# Seed data
# --------------------------------------------------------------------------- #

ROLES = [
    {"slug": "customer",      "display_name": "Customer"},
    {"slug": "sales",         "display_name": "Sales Representative"},
    {"slug": "appraiser",     "display_name": "Appraiser"},
    {"slug": "sales_manager", "display_name": "Sales Manager"},
    {"slug": "admin",         "display_name": "Administrator"},
    {"slug": "reporting",     "display_name": "Reporting User"},
]

# 15 default equipment categories
# TODO: populate components/prompts/photo_slots from business data CSVs (Phase 4 Admin Panel)
EQUIPMENT_CATEGORIES = [
    {"name": "Excavators",            "slug": "excavators",            "display_order": 1},
    {"name": "Dozers",                "slug": "dozers",                "display_order": 2},
    {"name": "Wheel Loaders",         "slug": "wheel-loaders",         "display_order": 3},
    {"name": "Motor Graders",         "slug": "motor-graders",         "display_order": 4},
    {"name": "Scrapers",              "slug": "scrapers",              "display_order": 5},
    {"name": "Articulated Trucks",    "slug": "articulated-trucks",    "display_order": 6},
    {"name": "Rigid Frame Trucks",    "slug": "rigid-frame-trucks",    "display_order": 7},
    {"name": "Compactors",            "slug": "compactors",            "display_order": 8},
    {"name": "Cranes",                "slug": "cranes",                "display_order": 9},
    {"name": "Forklifts",             "slug": "forklifts",             "display_order": 10},
    {"name": "Telescopic Handlers",   "slug": "telescopic-handlers",   "display_order": 11},
    {"name": "Skid Steers",           "slug": "skid-steers",           "display_order": 12},
    {"name": "Track Loaders",         "slug": "track-loaders",         "display_order": 13},
    {"name": "Backhoes",              "slug": "backhoes",              "display_order": 14},
    {"name": "Pipe Layers",           "slug": "pipe-layers",           "display_order": 15},
]

APP_CONFIG_DEFAULTS = [
    # Notifications
    {"key": "notifications.email_enabled",       "value": True,  "category": "notifications", "field_type": "boolean"},
    {"key": "notifications.sms_enabled",         "value": False, "category": "notifications", "field_type": "boolean"},
    {"key": "notifications.slack_enabled",       "value": False, "category": "notifications", "field_type": "boolean"},
    # Scheduling
    {"key": "scheduling.default_drive_time_buffer_minutes", "value": 30, "category": "scheduling", "field_type": "integer"},
    {"key": "scheduling.default_appointment_duration_minutes", "value": 60, "category": "scheduling", "field_type": "integer"},
    # Scoring
    {"key": "scoring.management_review_threshold", "value": 0.6,  "category": "scoring", "field_type": "decimal"},
    {"key": "scoring.low_marketability_threshold", "value": 0.4,  "category": "scoring", "field_type": "decimal"},
    # PDF
    {"key": "pdf.brand_logo_path",  "value": "", "category": "pdf", "field_type": "string"},
    {"key": "pdf.brand_color_hex",  "value": "#1a1a1a", "category": "pdf", "field_type": "string"},
    # Record locks
    {"key": "record_locks.ttl_minutes",       "value": 15, "category": "record_locks", "field_type": "integer"},
    {"key": "record_locks.heartbeat_seconds", "value": 60, "category": "record_locks", "field_type": "integer"},
]


# --------------------------------------------------------------------------- #
# Seeder
# --------------------------------------------------------------------------- #

async def seed(session: AsyncSession) -> None:
    print("Seeding roles...")
    for role in ROLES:
        await session.execute(
            text(
                "INSERT INTO roles (id, slug, display_name) "
                "VALUES (:id, :slug, :display_name) "
                "ON CONFLICT (slug) DO NOTHING"
            ),
            {"id": str(uuid.uuid4()), **role},
        )

    print("Seeding equipment categories...")
    for cat in EQUIPMENT_CATEGORIES:
        await session.execute(
            text(
                "INSERT INTO equipment_categories (id, name, slug, status, display_order) "
                "VALUES (:id, :name, :slug, 'active', :display_order) "
                "ON CONFLICT (slug) DO NOTHING"
            ),
            {"id": str(uuid.uuid4()), **cat},
        )

    print("Seeding app_config defaults...")
    for cfg in APP_CONFIG_DEFAULTS:
        import json
        await session.execute(
            text(
                "INSERT INTO app_config (id, key, value, category, field_type) "
                "VALUES (:id, :key, CAST(:value AS jsonb), :category, :field_type) "
                "ON CONFLICT (key) DO NOTHING"
            ),
            {
                "id": str(uuid.uuid4()),
                "key": cfg["key"],
                "value": json.dumps(cfg["value"]),
                "category": cfg["category"],
                "field_type": cfg["field_type"],
            },
        )

    admin_email = os.environ.get("SEED_ADMIN_EMAIL", "").strip()
    admin_password = os.environ.get("SEED_ADMIN_PASSWORD", "").strip()

    if admin_email and admin_password:
        print(f"Seeding admin user ({admin_email})...")
        # Look up admin role
        role_row = await session.execute(
            text("SELECT id FROM roles WHERE slug = 'admin'")
        )
        admin_role_id = role_row.scalar()
        if admin_role_id is None:
            print("ERROR: admin role not found — run seed after roles are committed")
            return

        password_hash = pwd_context.hash(admin_password)
        await session.execute(
            text(
                "INSERT INTO users "
                "(id, email, password_hash, first_name, last_name, role_id, status) "
                "VALUES (:id, :email, :password_hash, 'Admin', 'User', :role_id, 'active') "
                "ON CONFLICT (email) DO NOTHING"
            ),
            {
                "id": str(uuid.uuid4()),
                "email": admin_email,
                "password_hash": password_hash,
                "role_id": str(admin_role_id),
            },
        )
    else:
        print("Skipping admin user (SEED_ADMIN_EMAIL / SEED_ADMIN_PASSWORD not set)")

    await session.commit()
    print("Seed complete.")


async def main() -> None:
    engine = create_async_engine(DATABASE_URL, poolclass=NullPool, echo=False)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        await seed(session)
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())

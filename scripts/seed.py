# ABOUTME: Idempotent database seeder — roles, equipment categories, app config, and admin user.
# ABOUTME: Run via `make seed`. Safe to run multiple times; uses INSERT ... ON CONFLICT DO NOTHING.
from __future__ import annotations

import asyncio
import os
import sys
import uuid
from datetime import date as _date

# Allow running from repo root (local dev) or from inside the api container
# where scripts/ is mounted at /app/scripts/ and /app/ is the api root.
_here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_here, "..", "api"))  # local dev: repo/api/
sys.path.insert(0, os.path.join(_here, ".."))          # container: /app/ (= api root)
sys.path.insert(0, _here)                              # sibling scripts

import bcrypt
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    raise SystemExit(
        "DATABASE_URL is required. Export it or run via `make seed`, which sources .env."
    )

_BCRYPT_ROUNDS = 12


def _hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt(rounds=_BCRYPT_ROUNDS)).decode()

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

# Category catalog. The three bundle-seeded categories (dozers, backhoe-loaders,
# articulated-dump-trucks) are owned by scripts/import_category_bundle.py —
# that importer writes the full components/prompts/photo_slots/red_flag_rules
# graph. The remaining 12 entries here are name-only placeholders for Phase 4
# Admin Panel (ADR-002) to fill out via bulk import.
EQUIPMENT_CATEGORIES = [
    {"name": "Excavators",            "slug": "excavators",            "display_order": 1},
    {"name": "Wheel Loaders",         "slug": "wheel-loaders",         "display_order": 3},
    {"name": "Motor Graders",         "slug": "motor-graders",         "display_order": 4},
    {"name": "Scrapers",              "slug": "scrapers",              "display_order": 5},
    {"name": "Rigid Frame Trucks",    "slug": "rigid-frame-trucks",    "display_order": 7},
    {"name": "Compactors",            "slug": "compactors",            "display_order": 8},
    {"name": "Cranes",                "slug": "cranes",                "display_order": 9},
    {"name": "Forklifts",             "slug": "forklifts",             "display_order": 10},
    {"name": "Telescopic Handlers",   "slug": "telescopic-handlers",   "display_order": 11},
    {"name": "Skid Steers",           "slug": "skid-steers",           "display_order": 12},
    {"name": "Track Loaders",         "slug": "track-loaders",         "display_order": 13},
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

    print("Seeding equipment categories (placeholders)...")
    # Migration 019 replaced UNIQUE(slug) with a partial unique index
    # scoped to current, non-deleted versions. ON CONFLICT must reference
    # the same index predicate so Postgres infers the right index.
    for cat in EQUIPMENT_CATEGORIES:
        await session.execute(
            text(
                "INSERT INTO equipment_categories (id, name, slug, status, display_order) "
                "VALUES (:id, :name, :slug, 'active', :display_order) "
                "ON CONFLICT (slug) WHERE replaced_at IS NULL AND deleted_at IS NULL "
                "DO NOTHING"
            ),
            {"id": str(uuid.uuid4()), **cat},
        )

    print("Seeding starter category bundle (Dozers, Backhoe Loaders, ADT)...")
    # Imported locally so the top of seed.py stays import-cheap.
    from import_category_bundle import import_bundle

    inserted = await import_bundle(session)
    if inserted:
        print(f"  inserted: {', '.join(inserted)}")
    else:
        print("  (already present — no-op)")

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

    print("Seeding comparable_sales baseline rows...")
    await _seed_comparable_sales(session)

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

        password_hash = _hash_password(admin_password)
        admin_user_id = str(uuid.uuid4())
        await session.execute(
            text(
                "INSERT INTO users "
                "(id, email, password_hash, first_name, last_name, role_id, status) "
                "VALUES (:id, :email, :password_hash, 'Admin', 'User', :role_id, 'active') "
                "ON CONFLICT (email) DO NOTHING"
            ),
            {
                "id": admin_user_id,
                "email": admin_email,
                "password_hash": password_hash,
                "role_id": str(admin_role_id),
            },
        )
        # Mirror the primary role into the user_roles join table. Required
        # since Phase 4 pre-work moved RBAC checks onto the join table;
        # raw SQL inserts bypass the SQLAlchemy event listener that
        # handles this for ORM writes.
        await session.execute(
            text(
                "INSERT INTO user_roles (user_id, role_id) "
                "SELECT id, role_id FROM users WHERE email = :email "
                "ON CONFLICT (user_id, role_id) DO NOTHING"
            ),
            {"email": admin_email},
        )
    else:
        print("Skipping admin user (SEED_ADMIN_EMAIL / SEED_ADMIN_PASSWORD not set)")

    await session.commit()
    print("Seed complete.")


# ---------------------------------------------------------------------------
# Comparable sales seed data — ~50 internal rows for the valuation lookup.
# Mix of CAT, Komatsu, John Deere, Volvo, Hitachi across the categories
# seeded above (excavators, wheel-loaders, dozers, backhoe-loaders, etc.).
# ---------------------------------------------------------------------------

_COMPARABLE_SALES = [
    # Excavators
    {"make": "Caterpillar", "model": "320", "year": 2019, "hours": 4200, "sale_price": "185000.00", "sale_date": "2024-09-15", "slug": "excavators"},
    {"make": "Caterpillar", "model": "320", "year": 2020, "hours": 3100, "sale_price": "215000.00", "sale_date": "2024-11-02", "slug": "excavators"},
    {"make": "Caterpillar", "model": "336", "year": 2018, "hours": 6800, "sale_price": "245000.00", "sale_date": "2024-07-18", "slug": "excavators"},
    {"make": "Caterpillar", "model": "336", "year": 2021, "hours": 2400, "sale_price": "340000.00", "sale_date": "2025-01-10", "slug": "excavators"},
    {"make": "Komatsu", "model": "PC360LC-11", "year": 2019, "hours": 5100, "sale_price": "228000.00", "sale_date": "2024-08-22", "slug": "excavators"},
    {"make": "Komatsu", "model": "PC210LC-11", "year": 2020, "hours": 3800, "sale_price": "197000.00", "sale_date": "2024-10-05", "slug": "excavators"},
    {"make": "Komatsu", "model": "PC360LC-11", "year": 2017, "hours": 8900, "sale_price": "162000.00", "sale_date": "2024-06-14", "slug": "excavators"},
    {"make": "Hitachi", "model": "ZX350LC-6", "year": 2018, "hours": 6200, "sale_price": "218000.00", "sale_date": "2024-09-30", "slug": "excavators"},
    {"make": "Hitachi", "model": "ZX210LC-6", "year": 2020, "hours": 2900, "sale_price": "195000.00", "sale_date": "2025-02-08", "slug": "excavators"},
    {"make": "John Deere", "model": "350G LC", "year": 2019, "hours": 4700, "sale_price": "231000.00", "sale_date": "2024-12-01", "slug": "excavators"},
    # Dozers (Crawler Dozers)
    {"make": "Caterpillar", "model": "D6T", "year": 2019, "hours": 3900, "sale_price": "278000.00", "sale_date": "2024-10-20", "slug": "crawler-dozers"},
    {"make": "Caterpillar", "model": "D6T", "year": 2021, "hours": 1800, "sale_price": "345000.00", "sale_date": "2025-01-25", "slug": "crawler-dozers"},
    {"make": "Caterpillar", "model": "D8T", "year": 2018, "hours": 7200, "sale_price": "312000.00", "sale_date": "2024-07-09", "slug": "crawler-dozers"},
    {"make": "Komatsu", "model": "D61PX-24", "year": 2020, "hours": 2700, "sale_price": "265000.00", "sale_date": "2024-11-14", "slug": "crawler-dozers"},
    {"make": "Komatsu", "model": "D85EX-18", "year": 2019, "hours": 5400, "sale_price": "287000.00", "sale_date": "2024-08-05", "slug": "crawler-dozers"},
    {"make": "John Deere", "model": "1050K", "year": 2018, "hours": 6100, "sale_price": "295000.00", "sale_date": "2024-09-03", "slug": "crawler-dozers"},
    {"make": "Liebherr", "model": "PR 736", "year": 2020, "hours": 3200, "sale_price": "310000.00", "sale_date": "2024-12-19", "slug": "crawler-dozers"},
    # Backhoe Loaders
    {"make": "Caterpillar", "model": "420F2", "year": 2019, "hours": 3400, "sale_price": "68000.00", "sale_date": "2024-10-08", "slug": "backhoe-loaders"},
    {"make": "Caterpillar", "model": "420F2", "year": 2021, "hours": 1600, "sale_price": "88000.00", "sale_date": "2025-01-17", "slug": "backhoe-loaders"},
    {"make": "John Deere", "model": "310SL", "year": 2020, "hours": 2800, "sale_price": "74000.00", "sale_date": "2024-11-22", "slug": "backhoe-loaders"},
    {"make": "John Deere", "model": "310SL", "year": 2018, "hours": 5200, "sale_price": "52000.00", "sale_date": "2024-06-28", "slug": "backhoe-loaders"},
    {"make": "Komatsu", "model": "WB146-6", "year": 2019, "hours": 4100, "sale_price": "61000.00", "sale_date": "2024-09-11", "slug": "backhoe-loaders"},
    {"make": "Volvo", "model": "BL71B", "year": 2020, "hours": 2100, "sale_price": "72000.00", "sale_date": "2025-02-04", "slug": "backhoe-loaders"},
    # Wheel Loaders
    {"make": "Caterpillar", "model": "950M", "year": 2019, "hours": 4600, "sale_price": "198000.00", "sale_date": "2024-10-15", "slug": "wheel-loaders"},
    {"make": "Caterpillar", "model": "950M", "year": 2021, "hours": 2200, "sale_price": "248000.00", "sale_date": "2025-01-08", "slug": "wheel-loaders"},
    {"make": "Caterpillar", "model": "972M XE", "year": 2020, "hours": 3300, "sale_price": "315000.00", "sale_date": "2024-11-30", "slug": "wheel-loaders"},
    {"make": "Komatsu", "model": "WA380-8", "year": 2019, "hours": 5000, "sale_price": "188000.00", "sale_date": "2024-08-16", "slug": "wheel-loaders"},
    {"make": "Komatsu", "model": "WA470-8", "year": 2018, "hours": 7100, "sale_price": "172000.00", "sale_date": "2024-07-24", "slug": "wheel-loaders"},
    {"make": "Volvo", "model": "L110H", "year": 2020, "hours": 2900, "sale_price": "205000.00", "sale_date": "2024-12-10", "slug": "wheel-loaders"},
    {"make": "Liebherr", "model": "L 546", "year": 2019, "hours": 4400, "sale_price": "212000.00", "sale_date": "2024-09-25", "slug": "wheel-loaders"},
    # Motor Graders
    {"make": "Caterpillar", "model": "140M3", "year": 2019, "hours": 4800, "sale_price": "262000.00", "sale_date": "2024-10-29", "slug": "motor-graders"},
    {"make": "Caterpillar", "model": "140M3", "year": 2021, "hours": 2100, "sale_price": "318000.00", "sale_date": "2025-01-21", "slug": "motor-graders"},
    {"make": "John Deere", "model": "872GP", "year": 2020, "hours": 3600, "sale_price": "278000.00", "sale_date": "2024-11-07", "slug": "motor-graders"},
    {"make": "Komatsu", "model": "GD655-5", "year": 2018, "hours": 6500, "sale_price": "225000.00", "sale_date": "2024-07-31", "slug": "motor-graders"},
    # Articulated Dump Trucks
    {"make": "Caterpillar", "model": "740 GC", "year": 2019, "hours": 5300, "sale_price": "385000.00", "sale_date": "2024-10-03", "slug": "articulated-dump-trucks"},
    {"make": "Caterpillar", "model": "745", "year": 2020, "hours": 3700, "sale_price": "445000.00", "sale_date": "2024-12-05", "slug": "articulated-dump-trucks"},
    {"make": "Volvo", "model": "A40G", "year": 2019, "hours": 6100, "sale_price": "368000.00", "sale_date": "2024-09-08", "slug": "articulated-dump-trucks"},
    {"make": "Komatsu", "model": "HM400-5", "year": 2018, "hours": 7800, "sale_price": "312000.00", "sale_date": "2024-06-19", "slug": "articulated-dump-trucks"},
    {"make": "Bell", "model": "B40E", "year": 2020, "hours": 4200, "sale_price": "392000.00", "sale_date": "2025-01-14", "slug": "articulated-dump-trucks"},
    # Compactors
    {"make": "Caterpillar", "model": "CS11 GC", "year": 2020, "hours": 1800, "sale_price": "92000.00", "sale_date": "2024-11-18", "slug": "compactors"},
    {"make": "Caterpillar", "model": "CS11 GC", "year": 2018, "hours": 4400, "sale_price": "68000.00", "sale_date": "2024-08-12", "slug": "compactors"},
    {"make": "Bomag", "model": "BW 213 D-5", "year": 2019, "hours": 3100, "sale_price": "79000.00", "sale_date": "2024-10-24", "slug": "compactors"},
    # Skid Steers
    {"make": "Caterpillar", "model": "272D2", "year": 2020, "hours": 1400, "sale_price": "62000.00", "sale_date": "2024-12-03", "slug": "skid-steers"},
    {"make": "Caterpillar", "model": "272D2", "year": 2018, "hours": 3800, "sale_price": "44000.00", "sale_date": "2024-09-18", "slug": "skid-steers"},
    {"make": "Bobcat", "model": "S770", "year": 2020, "hours": 1700, "sale_price": "57000.00", "sale_date": "2024-11-26", "slug": "skid-steers"},
    # Cranes
    {"make": "Manitowoc", "model": "MLC100", "year": 2018, "hours": 5200, "sale_price": "780000.00", "sale_date": "2024-08-27", "slug": "cranes"},
    {"make": "Liebherr", "model": "LTM 1070-4.2", "year": 2019, "hours": 4100, "sale_price": "890000.00", "sale_date": "2024-10-11", "slug": "cranes"},
    # Forklifts
    {"make": "Toyota", "model": "8FGU25", "year": 2020, "hours": 2200, "sale_price": "24000.00", "sale_date": "2024-11-05", "slug": "forklifts"},
    {"make": "Caterpillar", "model": "GP25N", "year": 2019, "hours": 3600, "sale_price": "19000.00", "sale_date": "2024-09-22", "slug": "forklifts"},
]


async def _seed_comparable_sales(session: AsyncSession) -> None:
    existing = (await session.execute(text("SELECT COUNT(*) FROM comparable_sales"))).scalar()
    if existing:
        print(f"  skipping — {existing} rows already present.")
        return

    # Fetch all seeded category slugs at once.
    slug_rows = await session.execute(
        text(
            "SELECT slug, id FROM equipment_categories "
            "WHERE replaced_at IS NULL AND deleted_at IS NULL"
        )
    )
    slug_to_id = {row.slug: row.id for row in slug_rows}

    inserted = 0
    for sale in _COMPARABLE_SALES:
        cat_id = slug_to_id.get(sale["slug"])
        if cat_id is None:
            continue  # category not yet seeded — skip gracefully
        await session.execute(
            text(
                "INSERT INTO comparable_sales "
                "(id, make, model, year, hours, sale_price, sale_date, source, category_id) "
                "VALUES (:id, :make, :model, :year, :hours, "
                "        CAST(:sale_price AS NUMERIC(12,2)), "
                "        :sale_date, 'internal', :category_id)"
            ),
            {
                "id": str(uuid.uuid4()),
                "make": sale["make"],
                "model": sale["model"],
                "year": sale["year"],
                "hours": sale["hours"],
                "sale_price": sale["sale_price"],
                "sale_date": _date.fromisoformat(sale["sale_date"]),
                "category_id": str(cat_id),
            },
        )
        inserted += 1
    print(f"  {inserted} rows inserted.")


async def main() -> None:
    engine = create_async_engine(DATABASE_URL, poolclass=NullPool, echo=False)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        await seed(session)
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())

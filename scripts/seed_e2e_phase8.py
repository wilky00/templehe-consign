# ABOUTME: Phase 8 E2E fixtures — public listing catalog acceptance scenarios.
# ABOUTME: Seeds a published listing so the browser tests can hit /listings without auth.
from __future__ import annotations

import asyncio
import json
import os
import sys
import uuid
from datetime import UTC, datetime
from decimal import Decimal

import bcrypt
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    raise SystemExit("DATABASE_URL is required.")

PASSWORD = "TestPassword1!"

SALES_EMAIL = "e2e-phase8-sales@example.com"


def _hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt(rounds=12)).decode()


async def _role_id(session: AsyncSession, slug: str) -> str:
    row = await session.execute(text("SELECT id FROM roles WHERE slug = :s"), {"s": slug})
    found = row.scalar_one_or_none()
    if found is None:
        raise SystemExit(f"role '{slug}' missing — run `make seed` first")
    return str(found)


async def _upsert_user(
    session: AsyncSession,
    *,
    email: str,
    role_slug: str,
    first: str,
    last: str,
) -> str:
    row = await session.execute(text("SELECT id FROM users WHERE email = :e"), {"e": email})
    existing = row.scalar_one_or_none()
    role_id = await _role_id(session, role_slug)
    if existing is not None:
        user_id = str(existing)
        await session.execute(
            text(
                """
                UPDATE users
                SET role_id = :role, status = 'active',
                    failed_login_count = 0, locked_until = NULL
                WHERE id = :id
                """
            ),
            {"id": user_id, "role": role_id},
        )
    else:
        user_id = str(uuid.uuid4())
        await session.execute(
            text(
                """
                INSERT INTO users (
                    id, email, password_hash, first_name, last_name,
                    role_id, status,
                    tos_accepted_at, tos_version,
                    privacy_accepted_at, privacy_version
                ) VALUES (
                    :id, :email, :pw, :first, :last,
                    :role, 'active',
                    NOW(), '1', NOW(), '1'
                )
                """
            ),
            {
                "id": user_id,
                "email": email,
                "pw": _hash_password(PASSWORD),
                "first": first,
                "last": last,
                "role": role_id,
            },
        )
    return user_id


async def _reset_rate_limits(session: AsyncSession) -> None:
    await session.execute(text("DELETE FROM rate_limit_counters"))


async def _seed_listing(session: AsyncSession) -> dict:
    sales_id = await _upsert_user(
        session,
        email=SALES_EMAIL,
        role_slug="sales",
        first="E2E8",
        last="Sales",
    )

    # Customer with invite_email (satisfies ck_customers_user_or_invite)
    customer_id = str(uuid.uuid4())
    invite_email = f"e2e8-owner-{uuid.uuid4().hex[:8]}@example.com"
    await session.execute(
        text(
            """
            INSERT INTO customers (id, submitter_name, invite_email, address_state, created_at, updated_at)
            VALUES (:id, 'E2E8 Owner', :invite_email, 'TX', NOW(), NOW())
            ON CONFLICT DO NOTHING
            """
        ),
        {"id": customer_id, "invite_email": invite_email},
    )

    # EquipmentRecord
    record_id = str(uuid.uuid4())
    ref_num = f"THE-P8L{uuid.uuid4().hex[:5].upper()}"
    await session.execute(
        text(
            """
            INSERT INTO equipment_records (
                id, customer_id, reference_number, status,
                customer_make, customer_model, customer_year,
                assigned_sales_rep_id, created_at, updated_at
            ) VALUES (
                :id, :cust, :ref, 'listed',
                'Komatsu', 'PC360', 2020,
                :rep, NOW(), NOW()
            )
            """
        ),
        {
            "id": record_id,
            "cust": customer_id,
            "ref": ref_num,
            "rep": sales_id,
        },
    )

    # PublicListing
    listing_id = str(uuid.uuid4())
    await session.execute(
        text(
            """
            INSERT INTO public_listings (
                id, equipment_record_id, listing_title,
                asking_price, status, published_at
            ) VALUES (
                :id, :record_id, '2020 Komatsu PC360',
                95000.00, 'active', NOW()
            )
            """
        ),
        {"id": listing_id, "record_id": record_id},
    )

    await _reset_rate_limits(session)

    return {
        "sales_email": SALES_EMAIL,
        "sales_id": sales_id,
        "password": PASSWORD,
        "record_id": record_id,
        "listing_id": listing_id,
        "listing_title": "2020 Komatsu PC360",
        "asking_price": "95000.00",
    }


async def main() -> None:
    engine = create_async_engine(DATABASE_URL, poolclass=NullPool, echo=False)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with factory() as session:
            payload = await _seed_listing(session)
            await session.commit()
            sys.stdout.write(json.dumps(payload) + "\n")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())

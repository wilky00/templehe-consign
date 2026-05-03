# ABOUTME: Phase 7 E2E fixtures — PDF report download UI scenarios.
# ABOUTME: Seeds customer + sales_rep + records in report-eligible and non-eligible statuses.
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import uuid

import bcrypt
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    raise SystemExit("DATABASE_URL is required.")

PASSWORD = "TestPassword1!"

CUSTOMER_EMAIL = "e2e-phase7-customer@example.com"
SALES_EMAIL = "e2e-phase7-sales@example.com"


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
    await session.execute(
        text(
            "INSERT INTO user_roles (user_id, role_id) VALUES (:uid, :rid) "
            "ON CONFLICT (user_id, role_id) DO NOTHING"
        ),
        {"uid": user_id, "rid": role_id},
    )
    return user_id


async def _upsert_customer_profile(session: AsyncSession, *, user_id: str) -> str:
    row = await session.execute(text("SELECT id FROM customers WHERE user_id = :u"), {"u": user_id})
    existing = row.scalar_one_or_none()
    if existing is not None:
        return str(existing)
    customer_id = str(uuid.uuid4())
    await session.execute(
        text(
            """
            INSERT INTO customers (
                id, user_id, submitter_name, business_name
            ) VALUES (
                :id, :uid, 'E2E Phase7 Customer', 'Phase 7 E2E Co'
            )
            """
        ),
        {"id": customer_id, "uid": user_id},
    )
    return customer_id


async def _first_category_id(session: AsyncSession) -> str | None:
    row = await session.execute(
        text("SELECT id FROM equipment_categories WHERE deleted_at IS NULL LIMIT 1")
    )
    found = row.scalar_one_or_none()
    return str(found) if found else None


async def _reset_rate_limits(session: AsyncSession) -> None:
    await session.execute(text("TRUNCATE rate_limit_counters"))
    await session.execute(
        text(
            """
            UPDATE users SET failed_login_count = 0, locked_until = NULL
            WHERE email IN (:c, :s)
            """
        ),
        {"c": CUSTOMER_EMAIL, "s": SALES_EMAIL},
    )


async def _create_record(
    session: AsyncSession,
    *,
    customer_id: str,
    sales_rep_id: str,
    status: str,
    category_id: str | None,
) -> tuple[str, str]:
    record_id = str(uuid.uuid4())
    ref = f"THE-P7E{uuid.uuid4().hex[:5].upper()}"
    await session.execute(
        text(
            """
            INSERT INTO equipment_records (
                id, customer_id, category_id, status, reference_number,
                assigned_sales_rep_id,
                customer_make, customer_model, customer_year
            ) VALUES (
                :id, :cid, :cat, :status, :ref,
                :rep,
                'Komatsu', 'PC210', 2020
            )
            """
        ),
        {
            "id": record_id,
            "cid": customer_id,
            "cat": category_id,
            "status": status,
            "ref": ref,
            "rep": sales_rep_id,
        },
    )
    return record_id, ref


async def _create_approved_submission(
    session: AsyncSession,
    *,
    record_id: str,
    appraiser_id: str,
    category_id: str | None,
) -> str:
    sub_id = str(uuid.uuid4())
    await session.execute(
        text(
            """
            INSERT INTO appraisal_submissions (
                id, equipment_record_id, appraiser_id, category_id, status,
                make, model, year, overall_score, score_band, marketability_rating,
                management_review_required, hold_for_title_review,
                approved_purchase_offer, suggested_consignment_price,
                submitted_at, created_at, updated_at
            ) VALUES (
                :id, :rec, :app, :cat, 'approved',
                'Komatsu', 'PC210', 2020, 4.1, 'Strong resale candidate', 'Fast Sell',
                FALSE, FALSE,
                55000.00, 65000.00,
                NOW(), NOW(), NOW()
            )
            """
        ),
        {
            "id": sub_id,
            "rec": record_id,
            "app": appraiser_id,
            "cat": category_id,
        },
    )
    return sub_id


async def _seed_base_users(session: AsyncSession) -> dict:
    customer_user_id = await _upsert_user(
        session, email=CUSTOMER_EMAIL, role_slug="customer", first="E2E7", last="Customer"
    )
    customer_id = await _upsert_customer_profile(session, user_id=customer_user_id)
    sales_id = await _upsert_user(
        session, email=SALES_EMAIL, role_slug="sales", first="E2E7", last="Sales"
    )
    await _reset_rate_limits(session)
    return {
        "customer_email": CUSTOMER_EMAIL,
        "customer_id": customer_id,
        "customer_user_id": customer_user_id,
        "sales_email": SALES_EMAIL,
        "sales_id": sales_id,
        "password": PASSWORD,
    }


async def _seed_approved(session: AsyncSession) -> dict:
    """Record in approved_pending_esign — report not yet generated (202 state)."""
    base = await _seed_base_users(session)
    category_id = await _first_category_id(session)

    record_id, ref = await _create_record(
        session,
        customer_id=base["customer_id"],
        sales_rep_id=base["sales_id"],
        status="approved_pending_esign",
        category_id=category_id,
    )
    await _create_approved_submission(
        session,
        record_id=record_id,
        appraiser_id=base["sales_id"],
        category_id=category_id,
    )
    return {
        **base,
        "record_id": record_id,
        "reference_number": ref,
    }


async def _seed_new_request(session: AsyncSession) -> dict:
    """Record in new_request — report section should not appear."""
    base = await _seed_base_users(session)
    category_id = await _first_category_id(session)

    record_id, ref = await _create_record(
        session,
        customer_id=base["customer_id"],
        sales_rep_id=base["sales_id"],
        status="new_request",
        category_id=category_id,
    )
    return {
        **base,
        "record_id": record_id,
        "reference_number": ref,
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Phase 7 E2E fixture seeder")
    parser.add_argument(
        "--mode",
        choices=("approved", "new_request"),
        default="approved",
    )
    return parser.parse_args()


async def main() -> None:
    args = _parse_args()
    engine = create_async_engine(DATABASE_URL, poolclass=NullPool, echo=False)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    _SEEDERS = {
        "approved": _seed_approved,
        "new_request": _seed_new_request,
    }
    try:
        async with factory() as session:
            payload = await _SEEDERS[args.mode](session)
            await session.commit()
            sys.stdout.write(json.dumps(payload) + "\n")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())

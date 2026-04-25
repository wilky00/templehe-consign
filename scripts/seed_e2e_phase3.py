# ABOUTME: Phase 3 calendar E2E fixture — sales/appraiser/customer users + a fresh new_request record.
# ABOUTME: Idempotent on users; always creates a new equipment record so each spec run starts clean.
from __future__ import annotations

import asyncio
import json
import os
import secrets
import sys
import uuid

import bcrypt
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    raise SystemExit(
        "DATABASE_URL is required. Export it or run via `make seed-e2e-phase3`."
    )

PASSWORD = "TestPassword1!"
SALES_EMAIL = "e2e-phase3-sales@example.com"
APPRAISER_EMAIL = "e2e-phase3-appraiser@example.com"
CUSTOMER_EMAIL = "e2e-phase3-customer@example.com"

# Crockford-32 minus I/L/O/U — same alphabet equipment_service uses.
_REF_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def _hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt(rounds=12)).decode()


def _reference_number() -> str:
    suffix = "".join(secrets.choice(_REF_ALPHABET) for _ in range(8))
    return f"THE-{suffix}"


async def _role_id(session: AsyncSession, slug: str) -> uuid.UUID:
    row = await session.execute(text("SELECT id FROM roles WHERE slug = :s"), {"s": slug})
    found = row.scalar_one_or_none()
    if found is None:
        raise SystemExit(f"role '{slug}' missing — run `make seed` first")
    return found


async def _upsert_user(
    session: AsyncSession,
    *,
    email: str,
    role_slug: str,
    first: str,
    last: str,
) -> str:
    row = await session.execute(
        text("SELECT id FROM users WHERE email = :e"), {"e": email}
    )
    existing = row.scalar_one_or_none()
    if existing is not None:
        return str(existing)
    role_id = await _role_id(session, role_slug)
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
                NOW(), '1',
                NOW(), '1'
            )
            """
        ),
        {
            "id": user_id,
            "email": email,
            "pw": _hash_password(PASSWORD),
            "first": first,
            "last": last,
            "role": str(role_id),
        },
    )
    return user_id


async def _upsert_customer_profile(session: AsyncSession, *, user_id: str) -> str:
    row = await session.execute(
        text("SELECT id FROM customers WHERE user_id = :u"), {"u": user_id}
    )
    existing = row.scalar_one_or_none()
    if existing is not None:
        return str(existing)
    customer_id = str(uuid.uuid4())
    await session.execute(
        text(
            """
            INSERT INTO customers (
                id, user_id, submitter_name,
                address_street, address_city, address_state, address_zip
            ) VALUES (
                :id, :uid, 'E2E Phase3 Customer',
                '101 Yard Rd', 'Houston', 'TX', '77001'
            )
            """
        ),
        {"id": customer_id, "uid": user_id},
    )
    return customer_id


async def _create_new_request_record(session: AsyncSession, *, customer_id: str) -> dict:
    record_id = str(uuid.uuid4())
    reference = _reference_number()
    await session.execute(
        text(
            """
            INSERT INTO equipment_records (
                id, customer_id, status, reference_number,
                customer_make, customer_model, customer_year,
                customer_running_status, customer_ownership_type,
                customer_location_text, customer_submitted_at
            ) VALUES (
                :id, :cid, 'new_request', :ref,
                'Caterpillar', 'D6T', 2018,
                'running', 'owned',
                '101 Yard Rd, Houston TX 77001', NOW()
            )
            """
        ),
        {"id": record_id, "cid": customer_id, "ref": reference},
    )
    return {"equipment_record_id": record_id, "reference_number": reference}


async def _purge_future_calendar_events(session: AsyncSession, *, appraiser_id: str) -> None:
    """Drop any unfinished events for the test appraiser so spec re-runs
    don't 409 on stale 10:00-tomorrow slots."""
    await session.execute(
        text(
            "DELETE FROM calendar_events "
            "WHERE appraiser_id = :aid AND scheduled_at >= NOW()"
        ),
        {"aid": appraiser_id},
    )


async def main() -> None:
    engine = create_async_engine(DATABASE_URL, poolclass=NullPool, echo=False)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with factory() as session:
            sales_id = await _upsert_user(
                session,
                email=SALES_EMAIL,
                role_slug="sales",
                first="E2E",
                last="Sales",
            )
            appraiser_id = await _upsert_user(
                session,
                email=APPRAISER_EMAIL,
                role_slug="appraiser",
                first="E2E",
                last="Appraiser",
            )
            customer_user_id = await _upsert_user(
                session,
                email=CUSTOMER_EMAIL,
                role_slug="customer",
                first="E2E",
                last="Customer",
            )
            customer_id = await _upsert_customer_profile(
                session, user_id=customer_user_id
            )
            await _purge_future_calendar_events(session, appraiser_id=appraiser_id)
            record = await _create_new_request_record(session, customer_id=customer_id)
            await session.commit()
            payload = {
                "password": PASSWORD,
                "sales_user_id": sales_id,
                "sales_email": SALES_EMAIL,
                "appraiser_user_id": appraiser_id,
                "appraiser_email": APPRAISER_EMAIL,
                "customer_user_id": customer_user_id,
                "customer_email": CUSTOMER_EMAIL,
                "customer_id": customer_id,
                **record,
            }
            sys.stdout.write(json.dumps(payload) + "\n")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())

# ABOUTME: Phase 8 Sprint 4 E2E fixtures — admin reporting acceptance scenarios.
# ABOUTME: Seeds an admin user, approved equipment records, and analytics events for report data.
from __future__ import annotations

import asyncio
import json
import os
import uuid
from decimal import Decimal

import bcrypt
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    raise SystemExit("DATABASE_URL is required.")

PASSWORD = "TestPassword1!"
ADMIN_EMAIL = "e2e-phase8-reports-admin@example.com"
FAKE_IP = "192.0.2.88"


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


async def _seed_approved_record(
    session: AsyncSession,
    *,
    state: str,
    category_id: str,
    offer: Decimal,
) -> None:
    invite_email = f"e2e8-report-owner-{uuid.uuid4().hex[:8]}@example.com"
    customer_id = str(uuid.uuid4())
    await session.execute(
        text(
            """
            INSERT INTO customers (id, submitter_name, invite_email, address_state, created_at, updated_at)
            VALUES (:id, 'E2E Report Owner', :email, :state, NOW(), NOW())
            """
        ),
        {"id": customer_id, "email": invite_email, "state": state},
    )

    record_id = str(uuid.uuid4())
    ref_num = f"THE-P8R{uuid.uuid4().hex[:5].upper()}"
    await session.execute(
        text(
            """
            INSERT INTO equipment_records (
                id, customer_id, reference_number, status,
                category_id, customer_make, customer_model, customer_year,
                created_at, updated_at
            ) VALUES (
                :id, :cust, :ref, 'listed',
                :cat, 'Komatsu', 'PC360', 2020,
                NOW(), NOW()
            )
            """
        ),
        {"id": record_id, "cust": customer_id, "ref": ref_num, "cat": category_id},
    )

    sub_id = str(uuid.uuid4())
    await session.execute(
        text(
            """
            INSERT INTO appraisal_submissions (
                id, equipment_record_id, status,
                category_id, make, model, year,
                overall_score, approved_purchase_offer,
                approved_at, submitted_at, created_at, updated_at
            ) VALUES (
                :id, :record, 'approved',
                :cat, 'Komatsu', 'PC360', 2020,
                3.75, :offer,
                NOW(), NOW(), NOW(), NOW()
            )
            """
        ),
        {"id": sub_id, "record": record_id, "cat": category_id, "offer": str(offer)},
    )


async def _seed_analytics(session: AsyncSession) -> None:
    for i, (session_id, event_type, page) in enumerate(
        [
            ("e2e-sess-r1", "page_view", "/listings"),
            ("e2e-sess-r1", "page_view", "/portal/submit"),
            ("e2e-sess-r2", "page_view", "/listings"),
            ("e2e-sess-r2", "form_step_start", "/portal/submit"),
            ("e2e-sess-r2", "form_abandon", "/portal/submit"),
            ("e2e-sess-r3", "pdf_download_click", "/portal/report"),
        ]
    ):
        event_id = str(uuid.uuid4())
        # Guard against duplicate session/type/page combos on re-runs
        exists = await session.execute(
            text(
                "SELECT 1 FROM analytics_events WHERE id = :id"
            ),
            {"id": event_id},
        )
        if not exists.scalar_one_or_none():
            await session.execute(
                text(
                    """
                    INSERT INTO analytics_events (id, session_id, event_type, page, created_at)
                    VALUES (:id, :sess, :etype, :page, NOW())
                    """
                ),
                {
                    "id": event_id,
                    "sess": session_id,
                    "etype": event_type,
                    "page": page,
                },
            )


async def _reset_rate_limits(session: AsyncSession) -> None:
    await session.execute(text("DELETE FROM rate_limit_counters"))


async def main() -> None:
    engine = create_async_engine(DATABASE_URL, poolclass=NullPool)
    Session = async_sessionmaker(engine, expire_on_commit=False)

    async with Session() as session:
        async with session.begin():
            await _reset_rate_limits(session)
            await _upsert_user(
                session,
                email=ADMIN_EMAIL,
                role_slug="admin",
                first="E2E8",
                last="Admin",
            )

            # Get or create the Dozers category
            cat_row = await session.execute(
                text("SELECT id FROM equipment_categories WHERE name = 'Dozers' LIMIT 1")
            )
            cat_id = str(cat_row.scalar_one())

            await _seed_approved_record(session, state="TX", category_id=cat_id, offer=Decimal("75000.00"))
            await _seed_approved_record(session, state="CA", category_id=cat_id, offer=Decimal("55000.00"))
            await _seed_analytics(session)

    await engine.dispose()

    print(
        json.dumps(
            {
                "admin_email": ADMIN_EMAIL,
                "password": PASSWORD,
                "fake_ip": FAKE_IP,
            }
        )
    )


asyncio.run(main())

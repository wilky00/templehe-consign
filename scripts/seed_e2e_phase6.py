# ABOUTME: Phase 6 E2E fixtures — manager + sales_rep + appraiser + customer + records.
# ABOUTME: Multi-mode seeder; each mode returns JSON credentials + IDs for the spec's fixtures.
from __future__ import annotations

import argparse
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

MANAGER_EMAIL = "e2e-phase6-manager@example.com"
SALES_EMAIL = "e2e-phase6-sales@example.com"
APPRAISER_EMAIL = "e2e-phase6-appraiser@example.com"
CUSTOMER_EMAIL = "e2e-phase6-customer@example.com"


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
                id, user_id, submitter_name, business_name, cell_phone,
                address_street, address_city, address_state, address_zip
            ) VALUES (
                :id, :uid, 'E2E Phase6 Customer',
                'Phase 6 E2E Heavy Equipment Co', '+15555550600',
                '600 Approval Ave', 'Dallas', 'TX', '75201'
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
            WHERE email IN (:m, :s, :a, :c)
            """
        ),
        {"m": MANAGER_EMAIL, "s": SALES_EMAIL, "a": APPRAISER_EMAIL, "c": CUSTOMER_EMAIL},
    )


async def _create_equipment_record(
    session: AsyncSession,
    *,
    customer_id: str,
    sales_rep_id: str,
    status: str,
    category_id: str | None,
) -> tuple[str, str]:
    """Returns (record_id, reference_number)."""
    record_id = str(uuid.uuid4())
    ref = f"THE-E2E{uuid.uuid4().hex[:5].upper()}"
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
                'Caterpillar', '320', 2019
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


async def _create_submission(
    session: AsyncSession,
    *,
    record_id: str,
    appraiser_id: str,
    category_id: str | None,
    status: str = "submitted",
    management_review_required: bool = False,
    hold_for_title_review: bool = False,
    marketability_rating: str = "Fast Sell",
    overall_score: float = 3.75,
    score_band: str = "Strong resale candidate",
    approved_purchase_offer: float | None = None,
    suggested_consignment_price: float | None = None,
) -> str:
    sub_id = str(uuid.uuid4())
    now = datetime.now(UTC).isoformat()
    await session.execute(
        text(
            """
            INSERT INTO appraisal_submissions (
                id, equipment_record_id, appraiser_id, category_id, status,
                make, model, year,
                overall_score, score_band, marketability_rating,
                management_review_required, hold_for_title_review,
                submitted_at, created_at, updated_at
                {offer_col}
                {price_col}
            ) VALUES (
                :id, :rec, :app, :cat, :status,
                'Caterpillar', '320', 2019,
                :score, :band, :market,
                :mgmt_req, :title_hold,
                NOW(), NOW(), NOW()
                {offer_val}
                {price_val}
            )
            """
            .replace(
                "{offer_col}",
                ", approved_purchase_offer" if approved_purchase_offer is not None else "",
            )
            .replace(
                "{offer_val}",
                ", :offer" if approved_purchase_offer is not None else "",
            )
            .replace(
                "{price_col}",
                ", suggested_consignment_price" if suggested_consignment_price is not None else "",
            )
            .replace(
                "{price_val}",
                ", :price" if suggested_consignment_price is not None else "",
            )
        ),
        {
            "id": sub_id,
            "rec": record_id,
            "app": appraiser_id,
            "cat": category_id,
            "status": status,
            "score": overall_score,
            "band": score_band,
            "market": marketability_rating,
            "mgmt_req": management_review_required,
            "title_hold": hold_for_title_review,
            **({"offer": approved_purchase_offer} if approved_purchase_offer is not None else {}),
            **({"price": suggested_consignment_price} if suggested_consignment_price is not None else {}),
        },
    )
    return sub_id


async def _create_contract(
    session: AsyncSession,
    *,
    record_id: str,
    envelope_id: str,
    status: str = "sent",
    signed: bool = False,
) -> str:
    contract_id = str(uuid.uuid4())
    signed_at = datetime.now(UTC).isoformat() if signed else None
    await session.execute(
        text(
            """
            INSERT INTO consignment_contracts (
                id, equipment_record_id, envelope_id, status, signed_at, created_at
            ) VALUES (
                :id, :rec, :env, :status, :signed_at, NOW()
            )
            """
        ),
        {
            "id": contract_id,
            "rec": record_id,
            "env": envelope_id,
            "status": status,
            "signed_at": signed_at,
        },
    )
    return contract_id


async def _create_report(session: AsyncSession, *, record_id: str) -> str:
    report_id = str(uuid.uuid4())
    await session.execute(
        text(
            """
            INSERT INTO appraisal_reports (
                id, equipment_record_id, gcs_path, created_at
            ) VALUES (
                :id, :rec, 'reports/e2e/placeholder.pdf', NOW()
            )
            """
        ),
        {"id": report_id, "rec": record_id},
    )
    return report_id


async def _seed_base_users(session: AsyncSession) -> dict:
    manager_id = await _upsert_user(
        session, email=MANAGER_EMAIL, role_slug="sales_manager", first="E2E", last="Manager"
    )
    sales_id = await _upsert_user(
        session, email=SALES_EMAIL, role_slug="sales", first="E2E", last="Sales"
    )
    appraiser_id = await _upsert_user(
        session, email=APPRAISER_EMAIL, role_slug="appraiser", first="E2E", last="Appraiser"
    )
    customer_user_id = await _upsert_user(
        session, email=CUSTOMER_EMAIL, role_slug="customer", first="E2E", last="Customer"
    )
    customer_id = await _upsert_customer_profile(session, user_id=customer_user_id)
    await _reset_rate_limits(session)
    return {
        "manager_id": manager_id,
        "manager_email": MANAGER_EMAIL,
        "sales_id": sales_id,
        "sales_email": SALES_EMAIL,
        "appraiser_id": appraiser_id,
        "customer_id": customer_id,
        "customer_email": CUSTOMER_EMAIL,
        "password": PASSWORD,
    }


async def _seed_default(session: AsyncSession) -> dict:
    """Standard fixture: submitted appraisal ready for manager review."""
    base = await _seed_base_users(session)
    category_id = await _first_category_id(session)

    record_id, ref = await _create_equipment_record(
        session,
        customer_id=base["customer_id"],
        sales_rep_id=base["sales_id"],
        status="appraisal_complete",
        category_id=category_id,
    )
    sub_id = await _create_submission(
        session,
        record_id=record_id,
        appraiser_id=base["appraiser_id"],
        category_id=category_id,
    )
    return {
        **base,
        "record_id": record_id,
        "reference_number": ref,
        "submission_id": sub_id,
    }


async def _seed_red_flags(session: AsyncSession) -> dict:
    """Fixture with management_review_required=True and downgraded marketability."""
    base = await _seed_base_users(session)
    category_id = await _first_category_id(session)

    record_id, ref = await _create_equipment_record(
        session,
        customer_id=base["customer_id"],
        sales_rep_id=base["sales_id"],
        status="appraisal_complete",
        category_id=category_id,
    )
    sub_id = await _create_submission(
        session,
        record_id=record_id,
        appraiser_id=base["appraiser_id"],
        category_id=category_id,
        management_review_required=True,
        marketability_rating="Salvage Risk",
    )
    return {
        **base,
        "record_id": record_id,
        "reference_number": ref,
        "submission_id": sub_id,
    }


async def _seed_title_hold(session: AsyncSession) -> dict:
    """Fixture with hold_for_title_review=True."""
    base = await _seed_base_users(session)
    category_id = await _first_category_id(session)

    record_id, ref = await _create_equipment_record(
        session,
        customer_id=base["customer_id"],
        sales_rep_id=base["sales_id"],
        status="appraisal_complete",
        category_id=category_id,
    )
    sub_id = await _create_submission(
        session,
        record_id=record_id,
        appraiser_id=base["appraiser_id"],
        category_id=category_id,
        hold_for_title_review=True,
    )
    return {
        **base,
        "record_id": record_id,
        "reference_number": ref,
        "submission_id": sub_id,
    }


async def _seed_esign(session: AsyncSession) -> dict:
    """Fixture post-approval: record in approved_pending_esign with a ConsignmentContract."""
    base = await _seed_base_users(session)
    category_id = await _first_category_id(session)

    record_id, ref = await _create_equipment_record(
        session,
        customer_id=base["customer_id"],
        sales_rep_id=base["sales_id"],
        status="approved_pending_esign",
        category_id=category_id,
    )
    await _create_submission(
        session,
        record_id=record_id,
        appraiser_id=base["appraiser_id"],
        category_id=category_id,
        status="approved",
        approved_purchase_offer=50000.0,
        suggested_consignment_price=65000.0,
    )
    envelope_id = f"stub-{uuid.uuid4().hex}"
    await _create_contract(session, record_id=record_id, envelope_id=envelope_id, status="sent")

    return {
        **base,
        "record_id": record_id,
        "reference_number": ref,
        "envelope_id": envelope_id,
    }


async def _seed_price_change(session: AsyncSession) -> dict:
    """Fixture: approved record with a pending price change requiring manager re-approval."""
    base = await _seed_base_users(session)
    category_id = await _first_category_id(session)

    record_id, ref = await _create_equipment_record(
        session,
        customer_id=base["customer_id"],
        sales_rep_id=base["sales_id"],
        status="approved_pending_esign",
        category_id=category_id,
    )
    await _create_submission(
        session,
        record_id=record_id,
        appraiser_id=base["appraiser_id"],
        category_id=category_id,
        status="approved",
        suggested_consignment_price=60000.0,
    )

    change_id = str(uuid.uuid4())
    await session.execute(
        text(
            """
            INSERT INTO change_requests (
                id, equipment_record_id, request_type, status,
                proposed_consignment_price, requires_manager_reapproval,
                submitted_at
            ) VALUES (
                :id, :rec, 'update_consignment_price', 'pending',
                :proposed, TRUE,
                NOW()
            )
            """
        ),
        {"id": change_id, "rec": record_id, "proposed": Decimal("45000.00")},
    )

    return {
        **base,
        "record_id": record_id,
        "reference_number": ref,
        "change_request_id": change_id,
    }


async def _seed_publish_ready(session: AsyncSession) -> dict:
    """Fixture: record in esigned_pending_publish with signed contract + appraisal report."""
    base = await _seed_base_users(session)
    category_id = await _first_category_id(session)

    record_id, ref = await _create_equipment_record(
        session,
        customer_id=base["customer_id"],
        sales_rep_id=base["sales_id"],
        status="esigned_pending_publish",
        category_id=category_id,
    )
    await _create_submission(
        session,
        record_id=record_id,
        appraiser_id=base["appraiser_id"],
        category_id=category_id,
        status="approved",
        suggested_consignment_price=65000.0,
    )
    envelope_id = f"stub-{uuid.uuid4().hex}"
    await _create_contract(
        session, record_id=record_id, envelope_id=envelope_id, status="completed", signed=True
    )
    await _create_report(session, record_id=record_id)

    return {
        **base,
        "record_id": record_id,
        "reference_number": ref,
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Phase 6 E2E fixture seeder")
    parser.add_argument(
        "--mode",
        choices=("default", "red_flags", "title_hold", "esign", "price_change", "publish_ready"),
        default="default",
    )
    return parser.parse_args()


async def main() -> None:
    args = _parse_args()
    engine = create_async_engine(DATABASE_URL, poolclass=NullPool, echo=False)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    _SEEDERS = {
        "default": _seed_default,
        "red_flags": _seed_red_flags,
        "title_hold": _seed_title_hold,
        "esign": _seed_esign,
        "price_change": _seed_price_change,
        "publish_ready": _seed_publish_ready,
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

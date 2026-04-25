# ABOUTME: Phase 3 E2E fixtures — sales/manager/appraiser/customer users + per-spec records.
# ABOUTME: Idempotent on users; always creates fresh equipment_records so spec re-runs start clean.
from __future__ import annotations

import argparse
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
    raise SystemExit("DATABASE_URL is required. Export it or run via `make seed-e2e-phase3`.")

PASSWORD = "TestPassword1!"
SALES_EMAIL = "e2e-phase3-sales@example.com"
MANAGER_EMAIL = "e2e-phase3-manager@example.com"
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
    row = await session.execute(text("SELECT id FROM users WHERE email = :e"), {"e": email})
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
    # Mirror primary role into the user_roles join table — Phase 4 pre-
    # work moved RBAC onto the join table; raw SQL inserts bypass the
    # ORM event listener that handles this for managed writes.
    await session.execute(
        text(
            "INSERT INTO user_roles (user_id, role_id) VALUES (:uid, :rid) "
            "ON CONFLICT (user_id, role_id) DO NOTHING"
        ),
        {"uid": user_id, "rid": str(role_id)},
    )
    return user_id


async def _upsert_customer_profile(session: AsyncSession, *, user_id: str) -> str:
    row = await session.execute(text("SELECT id FROM customers WHERE user_id = :u"), {"u": user_id})
    existing = row.scalar_one_or_none()
    if existing is not None:
        # Converge to the seeded fields on every run — pre-existing rows from
        # before business_name/cell_phone were added would otherwise show
        # stale data on the dashboard.
        await session.execute(
            text(
                """
                UPDATE customers
                SET submitter_name = 'E2E Phase3 Customer',
                    business_name = 'Phase 3 E2E Co',
                    cell_phone = '+15555550100',
                    address_street = '101 Yard Rd',
                    address_city = 'Houston',
                    address_state = 'TX',
                    address_zip = '77001'
                WHERE id = :id
                """
            ),
            {"id": str(existing)},
        )
        return str(existing)
    customer_id = str(uuid.uuid4())
    await session.execute(
        text(
            """
            INSERT INTO customers (
                id, user_id, submitter_name,
                business_name, cell_phone,
                address_street, address_city, address_state, address_zip
            ) VALUES (
                :id, :uid, 'E2E Phase3 Customer',
                'Phase 3 E2E Co', '+15555550100',
                '101 Yard Rd', 'Houston', 'TX', '77001'
            )
            """
        ),
        {"id": customer_id, "uid": user_id},
    )
    return customer_id


async def _create_new_request_record(
    session: AsyncSession,
    *,
    customer_id: str,
    sales_rep_id: str | None = None,
) -> dict:
    record_id = str(uuid.uuid4())
    reference = _reference_number()
    await session.execute(
        text(
            """
            INSERT INTO equipment_records (
                id, customer_id, status, reference_number,
                customer_make, customer_model, customer_year,
                customer_running_status, customer_ownership_type,
                customer_location_text, customer_submitted_at,
                assigned_sales_rep_id
            ) VALUES (
                :id, :cid, 'new_request', :ref,
                'Caterpillar', 'D6T', 2018,
                'running', 'owned',
                '101 Yard Rd, Houston TX 77001', NOW(),
                :rep
            )
            """
        ),
        {
            "id": record_id,
            "cid": customer_id,
            "ref": reference,
            "rep": sales_rep_id,
        },
    )
    return {"equipment_record_id": record_id, "reference_number": reference}


async def _create_publish_ready_record(
    session: AsyncSession,
    *,
    customer_id: str,
    sales_rep_id: str,
    appraiser_id: str,
) -> dict:
    """Spec Feature 3.1.4 — record at esigned_pending_publish with the prereqs.

    Publish endpoint validates: status, signed contract, appraisal report.
    Seeds all three so the spec can exercise the happy path end-to-end.
    """
    record_id = str(uuid.uuid4())
    reference = _reference_number()
    await session.execute(
        text(
            """
            INSERT INTO equipment_records (
                id, customer_id, status, reference_number,
                customer_make, customer_model, customer_year,
                customer_running_status, customer_ownership_type,
                customer_location_text, customer_submitted_at,
                assigned_sales_rep_id, assigned_appraiser_id
            ) VALUES (
                :id, :cid, 'esigned_pending_publish', :ref,
                'Komatsu', 'PC360LC', 2020,
                'running', 'owned',
                '202 Quarry Way, Houston TX 77002', NOW(),
                :rep, :appr
            )
            """
        ),
        {
            "id": record_id,
            "cid": customer_id,
            "ref": reference,
            "rep": sales_rep_id,
            "appr": appraiser_id,
        },
    )
    # Signed consignment contract — publish gate #1.
    await session.execute(
        text(
            """
            INSERT INTO consignment_contracts (
                id, equipment_record_id, envelope_id, status, signed_at
            ) VALUES (
                :id, :rid, 'e2e-phase3-envelope', 'signed', NOW()
            )
            """
        ),
        {"id": str(uuid.uuid4()), "rid": record_id},
    )
    # Appraisal report — publish gate #2. gcs_path is just a stub.
    await session.execute(
        text(
            """
            INSERT INTO appraisal_reports (
                id, equipment_record_id, gcs_path
            ) VALUES (
                :id, :rid, 'e2e-phase3/appraisal.pdf'
            )
            """
        ),
        {"id": str(uuid.uuid4()), "rid": record_id},
    )
    return {"equipment_record_id": record_id, "reference_number": reference}


async def _purge_customer_records(session: AsyncSession, *, customer_id: str) -> None:
    """Wipe everything tied to a customer's equipment records so each test
    re-run starts from a known-empty slate. Deletes child rows that the
    schema doesn't cascade (calendar_events, change_requests, contracts,
    reports, listings, locks) before deleting the parent equipment_records.
    """
    rows = await session.execute(
        text("SELECT id FROM equipment_records WHERE customer_id = :cid"),
        {"cid": customer_id},
    )
    record_ids = [str(r[0]) for r in rows]
    if not record_ids:
        return
    for table in (
        "calendar_events",
        "change_requests",
        "consignment_contracts",
        "appraisal_reports",
        "public_listings",
    ):
        await session.execute(
            text(f"DELETE FROM {table} WHERE equipment_record_id = ANY(:ids)"),
            {"ids": record_ids},
        )
    await session.execute(
        text("DELETE FROM record_locks WHERE record_id = ANY(:ids)"),
        {"ids": record_ids},
    )
    await session.execute(
        text("DELETE FROM equipment_records WHERE id = ANY(:ids)"),
        {"ids": record_ids},
    )


async def _purge_future_calendar_events(session: AsyncSession) -> None:
    """Wipe every future calendar event regardless of appraiser. The Phase 3
    calendar spec asserts an empty board between scheduling steps and other
    test runs may have left orphaned events for unrelated appraisers."""
    await session.execute(
        text("DELETE FROM calendar_events WHERE scheduled_at >= NOW() AND cancelled_at IS NULL"),
    )


async def _reset_notification_prefs(session: AsyncSession, *, user_ids: list[str]) -> None:
    """Drop saved notification preferences so specs land back at the default
    'email' channel. The notifications spec switches to SMS mid-run and
    leaks state across runs without this."""
    if not user_ids:
        return
    await session.execute(
        text("DELETE FROM notification_preferences WHERE user_id = ANY(:ids)"),
        {"ids": user_ids},
    )


async def _reset_rate_limits(session: AsyncSession) -> None:
    """Clear every rate_limit_counters row + reset failed_login state on
    the deterministic test users. The Phase 3 e2e suite logs the same
    staff users in many times across specs and the per-email login
    limiter (10/15 min) trips fast. Test-only — production never calls
    this."""
    await session.execute(text("TRUNCATE rate_limit_counters"))
    await session.execute(
        text(
            """
            UPDATE users
            SET failed_login_count = 0, locked_until = NULL
            WHERE email IN (:s, :m, :a, :c)
            """
        ),
        {"s": SALES_EMAIL, "m": MANAGER_EMAIL, "a": APPRAISER_EMAIL, "c": CUSTOMER_EMAIL},
    )


async def _seed_default(session: AsyncSession, *, records: int = 1) -> dict:
    """Default fixture — sales/appraiser/customer + N new_request records.

    Wipes all of the test customer's prior records + all future calendar
    events so each invocation starts from a clean slate. ``records`` lets
    the calendar spec request the two records it needs in a single call
    (avoiding the previous pattern of two seed calls racing each other's
    cleanup).
    """
    sales_id = await _upsert_user(
        session, email=SALES_EMAIL, role_slug="sales", first="E2E", last="Sales"
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
    customer_id = await _upsert_customer_profile(session, user_id=customer_user_id)
    await _purge_customer_records(session, customer_id=customer_id)
    await _purge_future_calendar_events(session)
    await _reset_rate_limits(session)
    await _reset_notification_prefs(session, user_ids=[sales_id, appraiser_id, customer_user_id])
    created = []
    for _ in range(records):
        rec = await _create_new_request_record(
            session, customer_id=customer_id, sales_rep_id=sales_id
        )
        created.append(rec)
    payload: dict = {
        "password": PASSWORD,
        "sales_user_id": sales_id,
        "sales_email": SALES_EMAIL,
        "appraiser_user_id": appraiser_id,
        "appraiser_email": APPRAISER_EMAIL,
        "customer_user_id": customer_user_id,
        "customer_email": CUSTOMER_EMAIL,
        "customer_id": customer_id,
    }
    if records == 1:
        # Single-record callers (most specs) get the flat shape they expect.
        payload.update(created[0])
    else:
        payload["records"] = created
    return payload


async def _seed_publish(session: AsyncSession) -> dict:
    """Manual-publish fixture — a record at esigned_pending_publish + prereqs."""
    sales_id = await _upsert_user(
        session, email=SALES_EMAIL, role_slug="sales", first="E2E", last="Sales"
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
    customer_id = await _upsert_customer_profile(session, user_id=customer_user_id)
    await _purge_customer_records(session, customer_id=customer_id)
    await _purge_future_calendar_events(session)
    await _reset_rate_limits(session)
    record = await _create_publish_ready_record(
        session,
        customer_id=customer_id,
        sales_rep_id=sales_id,
        appraiser_id=appraiser_id,
    )
    return {
        "password": PASSWORD,
        "sales_user_id": sales_id,
        "sales_email": SALES_EMAIL,
        "customer_id": customer_id,
        **record,
    }


async def _seed_cascade(session: AsyncSession) -> dict:
    """Cascade-assignment fixture — one customer with three new_request rows.

    Records are pre-assigned to the test sales rep so the dashboard's
    "mine" scope renders the customer group. Cascade then exercises the
    appraiser path; the spec asserts an exact "Updated 3 / skipped 0".
    """
    sales_id = await _upsert_user(
        session, email=SALES_EMAIL, role_slug="sales", first="E2E", last="Sales"
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
    customer_id = await _upsert_customer_profile(session, user_id=customer_user_id)
    await _purge_customer_records(session, customer_id=customer_id)
    await _purge_future_calendar_events(session)
    await _reset_rate_limits(session)
    records = []
    for _ in range(3):
        rec = await _create_new_request_record(
            session, customer_id=customer_id, sales_rep_id=sales_id
        )
        records.append(rec)
    return {
        "password": PASSWORD,
        "sales_user_id": sales_id,
        "sales_email": SALES_EMAIL,
        "appraiser_user_id": appraiser_id,
        "customer_id": customer_id,
        "records": records,
    }


async def _seed_locking(session: AsyncSession) -> dict:
    """Record-locking fixture — sales rep + manager + a fresh record.

    Manager triggers the override; the rep gets the broken-lock notification.
    Manager email must be deliverable (Mailpit) so the spec can read it.
    """
    sales_id = await _upsert_user(
        session, email=SALES_EMAIL, role_slug="sales", first="E2E", last="Sales"
    )
    manager_id = await _upsert_user(
        session,
        email=MANAGER_EMAIL,
        role_slug="sales_manager",
        first="E2E",
        last="Manager",
    )
    customer_user_id = await _upsert_user(
        session,
        email=CUSTOMER_EMAIL,
        role_slug="customer",
        first="E2E",
        last="Customer",
    )
    customer_id = await _upsert_customer_profile(session, user_id=customer_user_id)
    await _purge_customer_records(session, customer_id=customer_id)
    await _purge_future_calendar_events(session)
    await _reset_rate_limits(session)
    # Locking spec asserts the override notification reaches Mailpit. If a
    # prior spec left the sales rep on SMS, dispatch skips ("not configured")
    # and the email never arrives. Reset to default before each run.
    await _reset_notification_prefs(session, user_ids=[sales_id, manager_id, customer_user_id])
    record = await _create_new_request_record(
        session, customer_id=customer_id, sales_rep_id=sales_id
    )
    return {
        "password": PASSWORD,
        "sales_user_id": sales_id,
        "sales_email": SALES_EMAIL,
        "manager_user_id": manager_id,
        "manager_email": MANAGER_EMAIL,
        "customer_id": customer_id,
        **record,
    }


async def _set_hidden_roles(session: AsyncSession, *, roles: list[str]) -> dict:
    """Toggle the AppConfig key that hides the notifications page per role.

    Lets the notifications spec exercise the "hidden" placeholder branch
    without touching code. Idempotent on re-runs.
    """
    payload = json.dumps({"roles": roles})
    await session.execute(
        text(
            """
            INSERT INTO app_config (key, value, category, field_type)
            VALUES (
                'notification_preferences_hidden_roles',
                CAST(:val AS jsonb),
                'notifications',
                'json'
            )
            ON CONFLICT (key) DO UPDATE SET value = CAST(:val AS jsonb)
            """
        ),
        {"val": payload},
    )
    return {"hidden_roles": roles}


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Phase 3 E2E fixture seeder")
    parser.add_argument(
        "--mode",
        choices=("default", "publish", "cascade", "locking", "hide-roles"),
        default="default",
        help="Which fixture to seed.",
    )
    parser.add_argument(
        "--records",
        type=int,
        default=1,
        help="How many new_request records to create (default mode only).",
    )
    parser.add_argument(
        "--roles",
        default="",
        help="Comma-separated role slugs (used with --mode hide-roles)",
    )
    return parser.parse_args()


async def main() -> None:
    args = _parse_args()
    engine = create_async_engine(DATABASE_URL, poolclass=NullPool, echo=False)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with factory() as session:
            if args.mode == "publish":
                payload = await _seed_publish(session)
            elif args.mode == "cascade":
                payload = await _seed_cascade(session)
            elif args.mode == "locking":
                payload = await _seed_locking(session)
            elif args.mode == "hide-roles":
                roles = [r.strip() for r in args.roles.split(",") if r.strip()]
                payload = await _set_hidden_roles(session, roles=roles)
            else:
                payload = await _seed_default(session, records=args.records)
            await session.commit()
            sys.stdout.write(json.dumps(payload) + "\n")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())

# ABOUTME: Phase 4 E2E fixtures — admin + reporting users + per-mode admin-side state.
# ABOUTME: Idempotent on users; resets rate limits + clears AppConfig overrides each run.
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
    raise SystemExit("DATABASE_URL is required. Export it or run via `make seed-e2e-phase4`.")

PASSWORD = "TestPassword1!"
ADMIN_EMAIL = "e2e-phase4-admin@example.com"
REPORTING_EMAIL = "e2e-phase4-reporting@example.com"
SALES_EMAIL = "e2e-phase4-sales@example.com"
CUSTOMER_EMAIL = "e2e-phase4-customer@example.com"

# AppConfig keys the spec touches; cleared on every default seed so the
# intake-visibility scenario starts from a known "all canonical fields"
# state regardless of what a prior run left behind.
_RESET_CONFIG_KEYS = ("intake_fields_visible", "intake_fields_order")


def _hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt(rounds=12)).decode()


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
    """Create-or-fetch the test user. Mirrors the role into user_roles —
    raw SQL inserts bypass the ORM event listener that handles this for
    managed writes. Re-runs converge to the same state."""
    row = await session.execute(text("SELECT id FROM users WHERE email = :e"), {"e": email})
    existing = row.scalar_one_or_none()
    role_id = await _role_id(session, role_slug)
    if existing is not None:
        user_id = str(existing)
        # Re-converge the primary role + status in case a prior phase
        # mutated them (e.g. deactivation tests).
        await session.execute(
            text(
                """
                UPDATE users
                SET role_id = :role, status = 'active',
                    failed_login_count = 0, locked_until = NULL
                WHERE id = :id
                """
            ),
            {"id": user_id, "role": str(role_id)},
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
    # Mirror primary role into user_roles — Phase 4 pre-work moved RBAC
    # onto the join table; raw SQL inserts bypass the ORM listener.
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
                :id, :uid, 'E2E Phase4 Customer',
                'Phase 4 E2E Co', '+15555550400',
                '404 Admin Way', 'Austin', 'TX', '73301'
            )
            """
        ),
        {"id": customer_id, "uid": user_id},
    )
    return customer_id


async def _reset_rate_limits(session: AsyncSession) -> None:
    """Clear every rate_limit_counters row + reset failed_login state on
    the deterministic test users. Phase 4 specs log the same admin user
    across many flows; without this the per-email login limiter trips
    fast. Test-only — production never calls this."""
    await session.execute(text("TRUNCATE rate_limit_counters"))
    await session.execute(
        text(
            """
            UPDATE users
            SET failed_login_count = 0, locked_until = NULL
            WHERE email IN (:a, :r, :s, :c)
            """
        ),
        {
            "a": ADMIN_EMAIL,
            "r": REPORTING_EMAIL,
            "s": SALES_EMAIL,
            "c": CUSTOMER_EMAIL,
        },
    )


async def _reset_app_config(session: AsyncSession) -> None:
    """Drop the AppConfig overrides Phase 4 specs flip. Defaults rehydrate
    via the registry's KeySpec.default, so deletion = "no override"."""
    for key in _RESET_CONFIG_KEYS:
        await session.execute(text("DELETE FROM app_config WHERE key = :k"), {"k": key})


async def _reset_integration_credentials(session: AsyncSession) -> None:
    """Wipe stored integration credentials so the integrations spec
    starts with the "not set" badge. Other phases never touched this
    table, so a TRUNCATE is safe; cascading FKs from health_state are
    by service_name not credential id, so unaffected."""
    await session.execute(text("TRUNCATE integration_credentials"))
    # Health state references service_name (PK) — flush so an old red
    # status from a prior run doesn't bleed into the next run's
    # rendering. Probes re-populate on next snapshot read.
    await session.execute(text("TRUNCATE service_health_state"))


async def _purge_seeded_routing_rules(session: AsyncSession) -> None:
    """Hard-delete routing rules created by the spec helper; keeps re-runs
    from accumulating duplicate-priority orphans. Real prod rules are
    untouched — the spec marker is a JSONB key (`phase4_e2e_marker`).
    Spec-created rules from the UI flow are tagged via a separate name
    marker on metro_area.name; the LIKE handles both shapes."""
    await session.execute(
        text(
            """
            DELETE FROM lead_routing_rules
            WHERE (conditions ? 'phase4_e2e_marker')
               OR conditions::text LIKE '%phase4-e2e%'
            """
        ),
    )


async def _seed_geographic_rules(session: AsyncSession, *, sales_rep_id: str) -> list[dict]:
    """Pre-seed two geographic rules at priorities 10 and 20 so the spec
    can exercise reorder + per-rule test endpoints without first having
    to drive the create form."""
    rules: list[dict] = []
    for priority, state in ((10, "TX"), (20, "CA")):
        rule_id = str(uuid.uuid4())
        conditions = {
            # Marker so _purge_seeded_routing_rules can clean us up.
            "state_list": [state],
            "phase4_e2e_marker": True,
        }
        await session.execute(
            text(
                """
                INSERT INTO lead_routing_rules (
                    id, rule_type, priority, conditions,
                    assigned_user_id, round_robin_index, is_active,
                    created_at
                ) VALUES (
                    :id, 'geographic', :pri, CAST(:cond AS jsonb),
                    :rep, 0, TRUE,
                    NOW()
                )
                """
            ),
            {
                "id": rule_id,
                "pri": priority,
                "cond": json.dumps(conditions),
                "rep": sales_rep_id,
            },
        )
        rules.append({"rule_id": rule_id, "state": state, "priority": priority})
    return rules


async def _seed_default(session: AsyncSession) -> dict:
    """Default fixture — admin + reporting + sales + customer users.

    Resets rate limits + AppConfig overrides every run so each spec
    starts from a known clean slate. Returns IDs the spec needs for
    routing/integration/role assertions."""
    admin_id = await _upsert_user(
        session, email=ADMIN_EMAIL, role_slug="admin", first="E2E", last="Admin"
    )
    reporting_id = await _upsert_user(
        session,
        email=REPORTING_EMAIL,
        role_slug="reporting",
        first="E2E",
        last="Reporting",
    )
    sales_id = await _upsert_user(
        session, email=SALES_EMAIL, role_slug="sales", first="E2E", last="Sales"
    )
    customer_user_id = await _upsert_user(
        session,
        email=CUSTOMER_EMAIL,
        role_slug="customer",
        first="E2E",
        last="Customer",
    )
    customer_id = await _upsert_customer_profile(session, user_id=customer_user_id)
    await _purge_seeded_routing_rules(session)
    await _reset_rate_limits(session)
    await _reset_app_config(session)
    await _reset_integration_credentials(session)
    return {
        "password": PASSWORD,
        "admin_user_id": admin_id,
        "admin_email": ADMIN_EMAIL,
        "reporting_user_id": reporting_id,
        "reporting_email": REPORTING_EMAIL,
        "sales_user_id": sales_id,
        "sales_email": SALES_EMAIL,
        "customer_user_id": customer_user_id,
        "customer_email": CUSTOMER_EMAIL,
        "customer_id": customer_id,
    }


async def _seed_routing(session: AsyncSession) -> dict:
    """Default fixture + two seeded geographic rules at priorities 10/20."""
    base = await _seed_default(session)
    rules = await _seed_geographic_rules(session, sales_rep_id=base["sales_user_id"])
    base["seeded_geographic_rules"] = rules
    return base


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Phase 4 E2E fixture seeder")
    parser.add_argument(
        "--mode",
        choices=("default", "routing"),
        default="default",
        help="Which fixture to seed.",
    )
    return parser.parse_args()


async def main() -> None:
    args = _parse_args()
    engine = create_async_engine(DATABASE_URL, poolclass=NullPool, echo=False)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with factory() as session:
            if args.mode == "routing":
                payload = await _seed_routing(session)
            else:
                payload = await _seed_default(session)
            await session.commit()
            sys.stdout.write(json.dumps(payload) + "\n")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())

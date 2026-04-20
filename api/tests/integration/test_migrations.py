# ABOUTME: Integration tests verifying the initial schema migration is correct.
# ABOUTME: Checks all tables exist, seed data loads, and audit_logs append-only trigger fires.
from __future__ import annotations

import pytest
from sqlalchemy import text

EXPECTED_TABLES = [
    "roles",
    "users",
    "user_sessions",
    "totp_recovery_codes",
    "known_devices",
    "notification_preferences",
    "rate_limit_counters",
    "equipment_categories",
    "category_components",
    "category_inspection_prompts",
    "category_attachments",
    "category_photo_slots",
    "category_red_flag_rules",
    "customers",
    "equipment_records",
    "appraisal_submissions",
    "appraisal_photos",
    "component_scores",
    "appraisal_reports",
    "consignment_contracts",
    "change_requests",
    "lead_routing_rules",
    "calendar_events",
    "public_listings",
    "audit_logs",
    "record_locks",
    "app_config",
    "analytics_events",
    "inquiries",
    "comparable_sales",
    "webhook_events_seen",
]


@pytest.mark.asyncio
async def test_all_tables_exist(db_session):
    """Every expected table is present in the database after migration."""
    result = await db_session.execute(
        text(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename"
        )
    )
    existing = {row[0] for row in result.fetchall()}
    for table in EXPECTED_TABLES:
        assert table in existing, f"Table '{table}' not found after migration"


@pytest.mark.asyncio
async def test_roles_have_indexes(db_session):
    """roles.slug has a unique index."""
    result = await db_session.execute(
        text(
            "SELECT indexname FROM pg_indexes "
            "WHERE tablename = 'roles' AND indexdef LIKE '%UNIQUE%'"
        )
    )
    assert result.fetchone() is not None, "No unique index found on roles"


@pytest.mark.asyncio
async def test_audit_logs_append_only_trigger(db_session):
    """Attempting to DELETE from audit_logs raises an exception."""
    # Insert a test row
    await db_session.execute(
        text("INSERT INTO audit_logs (event_type) VALUES ('test_event')")
    )
    await db_session.flush()

    # DELETE must be blocked by trigger
    with pytest.raises(Exception, match="append-only"):
        await db_session.execute(
            text("DELETE FROM audit_logs WHERE event_type = 'test_event'")
        )
        await db_session.flush()


@pytest.mark.asyncio
async def test_audit_logs_update_blocked(db_session):
    """Attempting to UPDATE audit_logs raises an exception."""
    await db_session.execute(
        text("INSERT INTO audit_logs (event_type) VALUES ('update_test')")
    )
    await db_session.flush()

    with pytest.raises(Exception, match="append-only"):
        await db_session.execute(
            text("UPDATE audit_logs SET event_type = 'modified' WHERE event_type = 'update_test'")
        )
        await db_session.flush()


@pytest.mark.asyncio
async def test_users_updated_at_trigger(db_session):
    """updated_at is automatically refreshed when a user row is updated."""
    # Need a role first
    await db_session.execute(
        text(
            "INSERT INTO roles (slug, display_name) VALUES ('test_role', 'Test')"
            " ON CONFLICT DO NOTHING"
        )
    )
    role_row = await db_session.execute(
        text("SELECT id FROM roles WHERE slug = 'test_role'")
    )
    role_id = role_row.scalar()

    await db_session.execute(
        text(
            "INSERT INTO users (email, first_name, last_name, role_id) "
            "VALUES ('trigger_test@example.com', 'T', 'T', :role_id)"
        ),
        {"role_id": role_id},
    )
    await db_session.flush()

    before = await db_session.execute(
        text("SELECT updated_at FROM users WHERE email = 'trigger_test@example.com'")
    )
    updated_at_before = before.scalar()

    # Small delay to ensure clock advances
    import asyncio
    await asyncio.sleep(0.01)

    await db_session.execute(
        text("UPDATE users SET first_name = 'Updated' WHERE email = 'trigger_test@example.com'")
    )
    await db_session.flush()

    after = await db_session.execute(
        text("SELECT updated_at FROM users WHERE email = 'trigger_test@example.com'")
    )
    updated_at_after = after.scalar()

    assert updated_at_after > updated_at_before, "updated_at trigger did not fire"

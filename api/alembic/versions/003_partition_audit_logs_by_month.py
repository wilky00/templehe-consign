"""partition audit_logs by month on created_at

Revision ID: 003
Revises: 002
Create Date: 2026-04-21 13:00:00.000000

Rewrites audit_logs as a monthly-range-partitioned table on created_at.
Preserves the append-only trigger, indexes, and FK to users(id). Data
from the legacy flat table is copied into the partitioned one and the
legacy table dropped.

Staging must run this before prod so the rewrite is observed end-to-end
on non-critical data first.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa

from alembic import op

revision: str = "003"
down_revision: str | None = "002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _month_bounds(year: int, month: int) -> tuple[str, str]:
    """Return ISO-formatted [start, next_month_start) for a given year/month."""
    start = datetime(year, month, 1, tzinfo=UTC).strftime("%Y-%m-%d")
    if month == 12:
        nxt = datetime(year + 1, 1, 1, tzinfo=UTC)
    else:
        nxt = datetime(year, month + 1, 1, tzinfo=UTC)
    return start, nxt.strftime("%Y-%m-%d")


def _iter_months(start_year: int, start_month: int, count: int):
    """Yield (year, month) tuples for ``count`` consecutive months starting at (y, m)."""
    y, m = start_year, start_month
    for _ in range(count):
        yield y, m
        m += 1
        if m > 12:
            m = 1
            y += 1


def _partition_name(year: int, month: int) -> str:
    return f"audit_logs_{year:04d}_{month:02d}"


def upgrade() -> None:
    # 1. Drop the append-only trigger and indexes on the legacy flat table so
    #    the rename + data copy isn't blocked.
    op.execute(sa.text("DROP TRIGGER IF EXISTS trg_audit_logs_readonly ON audit_logs"))
    op.execute(sa.text("DROP INDEX IF EXISTS ix_audit_logs_actor"))
    op.execute(sa.text("DROP INDEX IF EXISTS ix_audit_logs_target"))
    op.execute(sa.text("DROP INDEX IF EXISTS ix_audit_logs_event_type"))

    # 2. Rename the existing flat table out of the way.
    op.execute(sa.text("ALTER TABLE audit_logs RENAME TO audit_logs_legacy"))

    # 3. Create the new partitioned parent. PRIMARY KEY must include the
    #    partition key for Postgres range partitioning.
    op.execute(
        sa.text(
            """
            CREATE TABLE audit_logs (
                id           UUID NOT NULL DEFAULT gen_random_uuid(),
                event_type   VARCHAR(100) NOT NULL,
                actor_id     UUID REFERENCES users(id),
                actor_role   VARCHAR(50),
                target_type  VARCHAR(50),
                target_id    UUID,
                before_state JSONB,
                after_state  JSONB,
                ip_address   VARCHAR(45),
                user_agent   VARCHAR(512),
                created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                PRIMARY KEY (id, created_at)
            ) PARTITION BY RANGE (created_at)
            """
        )
    )

    # 4. Seed partitions for the previous 3 months, the current month, and the
    #    next 6 months. Ongoing month rollovers are handled by
    #    fn_ensure_audit_partitions in migration 004.
    now = datetime.now(UTC)
    start_m = now.month - 3
    start_y = now.year
    while start_m <= 0:
        start_m += 12
        start_y -= 1

    for y, m in _iter_months(start_y, start_m, 10):
        start, end = _month_bounds(y, m)
        op.execute(
            sa.text(
                f"""
                CREATE TABLE {_partition_name(y, m)}
                PARTITION OF audit_logs
                FOR VALUES FROM ('{start}') TO ('{end}')
                """
            )
        )

    # 5. A default partition catches any row with created_at outside the
    #    preallocated range, so inserts never fail even if the sweeper hasn't
    #    run. fn_ensure_audit_partitions will migrate rows out of it.
    op.execute(sa.text("CREATE TABLE audit_logs_default PARTITION OF audit_logs DEFAULT"))

    # 6. Indexes applied on the parent propagate to every partition.
    op.execute(sa.text("CREATE INDEX ix_audit_logs_actor ON audit_logs (actor_id, created_at)"))
    op.execute(
        sa.text(
            "CREATE INDEX ix_audit_logs_target ON audit_logs (target_id, target_type, created_at)"
        )
    )
    op.execute(
        sa.text("CREATE INDEX ix_audit_logs_event_type ON audit_logs (event_type, created_at)")
    )

    # 7. Copy historical data. PG routes each row into its monthly partition
    #    (or audit_logs_default if somehow outside the seeded range).
    op.execute(
        sa.text(
            """
            INSERT INTO audit_logs
                (id, event_type, actor_id, actor_role, target_type, target_id,
                 before_state, after_state, ip_address, user_agent, created_at)
            SELECT id, event_type, actor_id, actor_role, target_type, target_id,
                   before_state, after_state, ip_address, user_agent, created_at
            FROM audit_logs_legacy
            """
        )
    )

    # 8. Drop legacy table now that data is migrated.
    op.execute(sa.text("DROP TABLE audit_logs_legacy"))

    # 9. Re-apply append-only enforcement. In PG 16, triggers on the parent
    #    apply to every partition — no per-partition trigger needed.
    op.execute(
        sa.text(
            """
            CREATE TRIGGER trg_audit_logs_readonly
                BEFORE UPDATE OR DELETE ON audit_logs
                FOR EACH ROW EXECUTE FUNCTION prevent_audit_log_modification()
            """
        )
    )


def downgrade() -> None:
    # Reverse: collapse the partitioned table back into a single flat table.
    op.execute(sa.text("DROP TRIGGER IF EXISTS trg_audit_logs_readonly ON audit_logs"))
    op.execute(sa.text("DROP INDEX IF EXISTS ix_audit_logs_actor"))
    op.execute(sa.text("DROP INDEX IF EXISTS ix_audit_logs_target"))
    op.execute(sa.text("DROP INDEX IF EXISTS ix_audit_logs_event_type"))
    op.execute(sa.text("ALTER TABLE audit_logs RENAME TO audit_logs_partitioned"))

    op.execute(
        sa.text(
            """
            CREATE TABLE audit_logs (
                id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                event_type   VARCHAR(100) NOT NULL,
                actor_id     UUID REFERENCES users(id),
                actor_role   VARCHAR(50),
                target_type  VARCHAR(50),
                target_id    UUID,
                before_state JSONB,
                after_state  JSONB,
                ip_address   VARCHAR(45),
                user_agent   VARCHAR(512),
                created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
    )
    op.execute(
        sa.text(
            """
            INSERT INTO audit_logs
                (id, event_type, actor_id, actor_role, target_type, target_id,
                 before_state, after_state, ip_address, user_agent, created_at)
            SELECT id, event_type, actor_id, actor_role, target_type, target_id,
                   before_state, after_state, ip_address, user_agent, created_at
            FROM audit_logs_partitioned
            """
        )
    )
    op.execute(sa.text("DROP TABLE audit_logs_partitioned CASCADE"))

    op.execute(sa.text("CREATE INDEX ix_audit_logs_actor ON audit_logs (actor_id, created_at)"))
    op.execute(
        sa.text(
            "CREATE INDEX ix_audit_logs_target ON audit_logs (target_id, target_type, created_at)"
        )
    )
    op.execute(
        sa.text("CREATE INDEX ix_audit_logs_event_type ON audit_logs (event_type, created_at)")
    )
    op.execute(
        sa.text(
            """
            CREATE TRIGGER trg_audit_logs_readonly
                BEFORE UPDATE OR DELETE ON audit_logs
                FOR EACH ROW EXECUTE FUNCTION prevent_audit_log_modification()
            """
        )
    )

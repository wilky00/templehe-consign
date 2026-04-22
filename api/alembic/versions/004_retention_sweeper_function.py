"""retention sweeper + audit partition bootstrap functions

Revision ID: 004
Revises: 003
Create Date: 2026-04-21 13:30:00.000000

Adds two PL/pgSQL functions called hourly by the temple-sweeper Fly Machine
(see infra/fly/temple-sweeper.toml):

- fn_sweep_retention() — deletes stale rate_limit_counters (> 2h old),
  expired webhook_events_seen, and long-revoked user_sessions (> 7 days
  past expiry or revocation). Keeps those tables from growing without
  bound.

- fn_ensure_audit_partitions() — creates monthly partitions of
  audit_logs for the current and next two months if they don't exist.
  Idempotent; safe to call repeatedly. Uses advisory lock to avoid
  concurrent partition-creation races.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "004"
down_revision: str | None = "003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            CREATE OR REPLACE FUNCTION fn_sweep_retention()
            RETURNS TABLE (swept_table TEXT, rows_deleted BIGINT) AS $$
            DECLARE
                deleted_counters BIGINT;
                deleted_webhooks BIGINT;
                deleted_sessions BIGINT;
            BEGIN
                -- rate_limit_counters: fixed-window buckets older than 2 hours
                -- are never read again (longest window is 1h login-email).
                DELETE FROM rate_limit_counters
                WHERE window_start < now() - INTERVAL '2 hours';
                GET DIAGNOSTICS deleted_counters = ROW_COUNT;

                -- webhook_events_seen: expires_at is authoritative.
                DELETE FROM webhook_events_seen
                WHERE expires_at < now();
                GET DIAGNOSTICS deleted_webhooks = ROW_COUNT;

                -- user_sessions: expired or long-revoked. Keep revoked rows
                -- for 7 days so audit reports can still correlate to them.
                DELETE FROM user_sessions
                WHERE expires_at < now()
                   OR (revoked_at IS NOT NULL
                       AND revoked_at < now() - INTERVAL '7 days');
                GET DIAGNOSTICS deleted_sessions = ROW_COUNT;

                RETURN QUERY VALUES
                    ('rate_limit_counters'::TEXT, deleted_counters),
                    ('webhook_events_seen'::TEXT, deleted_webhooks),
                    ('user_sessions'::TEXT, deleted_sessions);
            END;
            $$ LANGUAGE plpgsql;
            """
        )
    )

    op.execute(
        sa.text(
            """
            CREATE OR REPLACE FUNCTION fn_ensure_audit_partitions()
            RETURNS INTEGER AS $$
            DECLARE
                target_month DATE;
                next_month   DATE;
                partition_name TEXT;
                created_count INTEGER := 0;
            BEGIN
                -- Advisory lock prevents two sweepers from racing to create
                -- the same partition. Arbitrary key; release at function end.
                PERFORM pg_advisory_xact_lock(829146);

                FOR i IN 0..2 LOOP
                    target_month := date_trunc('month', now()) + (i * INTERVAL '1 month');
                    next_month   := target_month + INTERVAL '1 month';
                    partition_name := 'audit_logs_' || to_char(target_month, 'YYYY_MM');

                    IF NOT EXISTS (
                        SELECT 1 FROM pg_class WHERE relname = partition_name
                    ) THEN
                        EXECUTE format(
                            'CREATE TABLE %I PARTITION OF audit_logs '
                            'FOR VALUES FROM (%L) TO (%L)',
                            partition_name, target_month, next_month
                        );
                        created_count := created_count + 1;
                    END IF;
                END LOOP;

                RETURN created_count;
            END;
            $$ LANGUAGE plpgsql;
            """
        )
    )


def downgrade() -> None:
    op.execute(sa.text("DROP FUNCTION IF EXISTS fn_sweep_retention()"))
    op.execute(sa.text("DROP FUNCTION IF EXISTS fn_ensure_audit_partitions()"))

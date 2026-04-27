# ABOUTME: Phase 4 Sprint 7 — integration_credentials vault + service_health_state.
# ABOUTME: Both new; no existing data to backfill. Reversible.
"""phase 4 sprint 7 — integration credentials + health state

Revision ID: 020
Revises: 019
Create Date: 2026-04-27 18:45:00.000000

Sprint 7 introduces two cross-cutting tables:

``integration_credentials`` — admin-managed credentials for Slack,
Twilio, SendGrid, Google Maps (and whatever Phase 5+ plugs in next).
Plaintext is never stored; the ``encrypted_value`` column carries a
Fernet-encrypted blob, keyed off ``settings.credentials_encryption_key``.
Test-button results live alongside (last_tested_at, last_test_status,
last_test_detail) so the admin UI can render "✓ tested 2 min ago"
without round-tripping the integration.

``service_health_state`` — one row per monitored service (db, r2,
slack, twilio, sendgrid, google_maps). The health poller and the
admin GET /admin/health endpoint both read+write here; the rate-limit
window for "service flipped red" notifications uses ``last_alerted_at``
to gate at 1 alert per service per 15 minutes.

The column-shape on ``service_health_state`` keeps the table tiny on
purpose — history goes to ``audit_logs`` (event_type=service_health_*),
not to a per-tick row in this table. Sprint 7 admin UI's "history
sparkline" reads ``audit_logs``.

Both tables are net-new; downgrade is a clean drop.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "020"
down_revision: str | None = "019"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    # Widen the notification_jobs channel CHECK to admit 'slack'. Phase 3
    # left the dispatch path as a no-op; Sprint 7 wires it through the
    # same queue + retry loop the email + SMS channels use.
    op.execute(sa.text("ALTER TABLE notification_jobs DROP CONSTRAINT chk_notification_channel"))
    op.execute(
        sa.text(
            "ALTER TABLE notification_jobs ADD CONSTRAINT chk_notification_channel "
            "CHECK (channel IN ('email', 'sms', 'slack'))"
        )
    )

    op.create_table(
        "integration_credentials",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("integration_name", sa.String(64), nullable=False, unique=True),
        sa.Column("encrypted_value", sa.LargeBinary(), nullable=False),
        sa.Column(
            "set_by",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "set_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("last_tested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_test_status", sa.String(32), nullable=True),
        sa.Column("last_test_detail", sa.Text(), nullable=True),
        sa.Column("last_test_latency_ms", sa.Integer(), nullable=True),
        sa.CheckConstraint(
            "last_test_status IS NULL OR last_test_status IN ('success','failure','stubbed')",
            name="ck_integration_credentials_test_status",
        ),
    )

    op.create_table(
        "service_health_state",
        sa.Column("service_name", sa.String(64), primary_key=True),
        sa.Column(
            "status",
            sa.String(16),
            nullable=False,
            server_default="unknown",
        ),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_alerted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_detail", sa.dialects.postgresql.JSONB(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "status IN ('green','yellow','red','unknown','stubbed')",
            name="ck_service_health_state_status",
        ),
    )


def downgrade() -> None:
    op.drop_table("service_health_state")
    op.drop_table("integration_credentials")
    op.execute(sa.text("ALTER TABLE notification_jobs DROP CONSTRAINT chk_notification_channel"))
    op.execute(
        sa.text(
            "ALTER TABLE notification_jobs ADD CONSTRAINT chk_notification_channel "
            "CHECK (channel IN ('email', 'sms'))"
        )
    )

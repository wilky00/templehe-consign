# ABOUTME: Phase 3 Sprint 3 — adds audit columns + soft-delete to lead_routing_rules.
# ABOUTME: Spec line 120 lists created_by, created_at; soft-delete uses deleted_at to preserve historical rules.
"""phase 3 lead routing audit columns

Revision ID: 010
Revises: 009
Create Date: 2026-04-24 18:00:00.000000

Adds:
- lead_routing_rules.created_by — FK to users, nullable. Captures the admin who
  authored the rule. Nullable to permit seeded/system rules.
- lead_routing_rules.created_at — server_default now(); audit baseline.
- lead_routing_rules.deleted_at — nullable; non-null marks the rule as soft-deleted.
  The waterfall ignores deleted_at IS NOT NULL rows, but the row stays for audit.
- Partial index ux_lead_routing_rules_active on (priority) WHERE deleted_at IS NULL
  AND is_active = true to keep the waterfall query lean as the rule set grows.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "010"
down_revision: str | None = "009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "lead_routing_rules",
        sa.Column(
            "created_by",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=True,
        ),
    )
    op.add_column(
        "lead_routing_rules",
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.add_column(
        "lead_routing_rules",
        sa.Column(
            "deleted_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )

    op.execute(
        """
        CREATE INDEX ix_lead_routing_rules_active
        ON lead_routing_rules (priority)
        WHERE deleted_at IS NULL AND is_active = true
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_lead_routing_rules_active")
    op.drop_column("lead_routing_rules", "deleted_at")
    op.drop_column("lead_routing_rules", "created_at")
    op.drop_column("lead_routing_rules", "created_by")

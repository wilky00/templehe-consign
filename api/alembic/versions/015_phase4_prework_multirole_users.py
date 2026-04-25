# ABOUTME: Phase 4 pre-work — user_roles join table; users.role_id stays as the "primary" role for back-compat.
# ABOUTME: Backfills existing users into the join table so the runtime can switch to intersection-based RBAC immediately.
"""phase 4 prework — user_roles join table

Revision ID: 015
Revises: 014
Create Date: 2026-04-25 22:00:00.000000

Phase 1's ``users.role_id`` FK enforced one role per user. Phase 4
admin will surface user management; the moment a sales rep also covers
appraiser shifts (or a manager also has reporting access), one-role-
per-user breaks down. Migrating the data after Phase 4 admin ships
means rebuilding the admin UI in flight.

Schema:

- ``user_roles`` — join table with ``(user_id, role_id, granted_at,
  granted_by)``. ``UNIQUE(user_id, role_id)`` so the same role can't
  be granted twice to the same user. ``granted_by`` is nullable for
  the initial backfill (admin who granted the role isn't known
  retroactively).

- ``users.role_id`` — RETAINED. Still NOT NULL. Now interpreted as the
  user's "primary" role: the one that drives default landing-page
  routing in the SPA (``Layout.tsx``'s sales-vs-customer split) and
  the single-string snapshot in ``audit_logs.actor_role``. Multi-role
  users have multiple ``user_roles`` rows AND a primary ``role_id``;
  RBAC checks (``require_roles``) hit the join table; landing-page
  routing hits the primary.

Backfill: every existing user gets one ``user_roles`` row matching
their current ``role_id``. Idempotent — only inserts rows that don't
already exist (handles re-runs).

Reversible: downgrade drops the table; ``users.role_id`` is
unaffected so the old runtime keeps working.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "015"
down_revision: str | None = "014"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "user_roles",
        sa.Column("user_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "granted_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("granted_by", sa.dialects.postgresql.UUID(as_uuid=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["role_id"], ["roles.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["granted_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("user_id", "role_id"),
    )
    op.create_index("ix_user_roles_user_id", "user_roles", ["user_id"])
    op.create_index("ix_user_roles_role_id", "user_roles", ["role_id"])

    # Backfill: every existing user has their primary role mirrored into
    # the join table. ON CONFLICT keeps the migration idempotent if
    # someone re-runs it (alembic's stamp-and-replay flow).
    op.execute(
        sa.text(
            """
            INSERT INTO user_roles (user_id, role_id, granted_at, granted_by)
            SELECT id, role_id, NOW(), NULL FROM users
            ON CONFLICT (user_id, role_id) DO NOTHING
            """
        )
    )


def downgrade() -> None:
    op.drop_index("ix_user_roles_role_id", table_name="user_roles")
    op.drop_index("ix_user_roles_user_id", table_name="user_roles")
    op.drop_table("user_roles")

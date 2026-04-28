# ABOUTME: Phase 5 Sprint 1 — device_tokens table for APNs (and future FCM) push targets.
# ABOUTME: Net-new table; downgrade is a clean drop.
"""phase 5 sprint 1 — device tokens

Revision ID: 022
Revises: 021
Create Date: 2026-04-28 21:30:00.000000

Sprint 1 lands the ``device_tokens`` table so the iOS app can register
its APNs token after a successful login. Sprint 2 layers APNs dispatch
on top of this — the dispatcher reads ``tokens_for_user(user, 'ios')``
and fans out one push per active token.

Schema notes:

- ``token`` is the raw APNs token (hex-encoded; 64+ chars). Stored
  plaintext because (a) it's not a credential — it identifies a device,
  not a person — and (b) APNs requires us to send it back verbatim on
  every dispatch.
- ``platform`` CHECKs ('ios','android') today; an Android client (Phase
  6+) would slot in without a schema change. The CHECK is enforced at
  the DB level so a service-layer bug can't write a third value.
- ``environment`` distinguishes APNs sandbox ('development', tied to
  Xcode debug builds) from production ('production', App Store / TestFlight
  builds). The dispatcher routes to the correct apple endpoint based on
  this column.
- ``UNIQUE (user_id, token)`` — re-registering the same token for the
  same user is an upsert (touch ``last_seen_at``, clear ``deleted_at``).
  If the same token reaches a different user (rare; happens on
  reinstall + login-as-someone-else), both rows coexist; the earlier
  one is reaped by APNs's permanent-failure response in Sprint 2.
- Soft-delete via ``deleted_at`` so the dispatcher and audit log can
  reason about "this token was once registered" history. Hard-delete
  fired by Sprint 2's permanent-failure path drops the row outright.

Reversible — downgrade drops the table.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "022"
down_revision: str | None = "021"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "device_tokens",
        sa.Column(
            "id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "user_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("platform", sa.String(16), nullable=False),
        sa.Column("token", sa.Text(), nullable=False),
        sa.Column("environment", sa.String(16), nullable=False),
        sa.Column(
            "registered_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "platform IN ('ios','android')",
            name="chk_device_token_platform",
        ),
        sa.CheckConstraint(
            "environment IN ('development','production')",
            name="chk_device_token_environment",
        ),
        sa.UniqueConstraint("user_id", "token", name="uq_device_tokens_user_token"),
    )

    # Active-tokens-per-user is the hot read path (Sprint 2 dispatch
    # fans out per user). Index on (user_id) where deleted_at IS NULL
    # so the planner can skip soft-deleted rows without a table scan.
    op.create_index(
        "ix_device_tokens_user_active",
        "device_tokens",
        ["user_id"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_device_tokens_user_active", table_name="device_tokens")
    op.drop_table("device_tokens")

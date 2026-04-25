# ABOUTME: Phase 3 Sprint 5 — UNIQUE(user_id) on notification_preferences + visibility flag.
# ABOUTME: One row per user (single preferred channel) and seeds notification_preferences_hidden_roles = [].
"""phase 3 notification preferences unique + visibility flag

Revision ID: 012
Revises: 011
Create Date: 2026-04-25 18:00:00.000000

The Phase 1 schema allowed multiple ``notification_preferences`` rows per
user (one per channel) but no caller ever wrote that way. Sprint 5 reads
the row as the user's *single preferred channel*, so a UNIQUE(user_id)
constraint matches actual usage and keeps the upsert path simple.

Also seeds the ``notification_preferences_hidden_roles`` AppConfig key
(default ``[]``) so an admin can hide the preferences page from a role
slug entirely without a code change. The customer role gets a read-only
view by default; flipping that flag hides the page outright.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "012"
down_revision: str | None = "011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Collapse any stray duplicate rows (defensive — none exist in known
    # environments since nothing wrote to the table, but the constraint
    # would fail on duplicates if they did).
    op.execute(
        sa.text(
            """
            DELETE FROM notification_preferences a USING notification_preferences b
            WHERE a.id < b.id AND a.user_id = b.user_id
            """
        )
    )
    op.create_unique_constraint(
        "uq_notification_preferences_user_id",
        "notification_preferences",
        ["user_id"],
    )

    op.execute(
        sa.text(
            """
            INSERT INTO app_config (key, value, category, field_type)
            VALUES (
                'notification_preferences_hidden_roles',
                '{"roles": []}'::jsonb,
                'notifications',
                'json'
            )
            ON CONFLICT (key) DO NOTHING
            """
        )
    )


def downgrade() -> None:
    op.execute(
        "DELETE FROM app_config WHERE key = 'notification_preferences_hidden_roles'"
    )
    op.drop_constraint(
        "uq_notification_preferences_user_id",
        "notification_preferences",
        type_="unique",
    )

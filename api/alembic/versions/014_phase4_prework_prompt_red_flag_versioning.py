# ABOUTME: Phase 4 pre-work — versioning columns on category_inspection_prompts + category_red_flag_rules.
# ABOUTME: Edits become insert-new + replaced_at on old; in-flight appraisals stay anchored to the version they were authored against.
"""phase 4 prework — prompt + red-flag rule versioning

Revision ID: 014
Revises: 013
Create Date: 2026-04-25 21:30:00.000000

Phase 4 admin will ship a CRUD UI for ``category_inspection_prompts``
and ``category_red_flag_rules``. Today both tables UPDATE in place,
which would silently rewrite every historical answer's prompt
definition. ``component_scores`` already snapshots ``weight_at_time_of_scoring``
(see models.py); this migration brings the prompt + red-flag tables to
the same standard.

Schema:

- ``version`` (int, default 1, NOT NULL) — sequential within a
  ``(category_id, semantic-id)`` group. Phase 4 admin's "edit" inserts
  a new row with ``version = max + 1`` and sets ``replaced_at`` on the
  old row.
- ``replaced_at`` (timestamptz, nullable) — when this version was
  superseded. ``replaced_at IS NULL`` = current. Indexed (partial) so
  the "fetch current prompts for category X" query stays a single seek.

Backfill: every existing row defaults to version=1, replaced_at=NULL.
Production has zero edits to date so this is a true no-op.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "014"
down_revision: str | None = "013"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    # category_inspection_prompts
    op.add_column(
        "category_inspection_prompts",
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column(
        "category_inspection_prompts",
        sa.Column("replaced_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_category_inspection_prompts_current",
        "category_inspection_prompts",
        ["category_id"],
        postgresql_where=sa.text("replaced_at IS NULL"),
    )

    # category_red_flag_rules
    op.add_column(
        "category_red_flag_rules",
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column(
        "category_red_flag_rules",
        sa.Column("replaced_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_category_red_flag_rules_current",
        "category_red_flag_rules",
        ["category_id"],
        postgresql_where=sa.text("replaced_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_category_red_flag_rules_current", table_name="category_red_flag_rules")
    op.drop_column("category_red_flag_rules", "replaced_at")
    op.drop_column("category_red_flag_rules", "version")

    op.drop_index(
        "ix_category_inspection_prompts_current",
        table_name="category_inspection_prompts",
    )
    op.drop_column("category_inspection_prompts", "replaced_at")
    op.drop_column("category_inspection_prompts", "version")

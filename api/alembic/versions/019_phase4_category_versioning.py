# ABOUTME: Phase 4 Sprint 6 — versioning columns on equipment_categories.
# ABOUTME: Edits become insert-new + replaced_at on old; mirrors migration 014 prompt + red-flag pattern.
"""phase 4 sprint 6 — equipment_categories versioning

Revision ID: 019
Revises: 018
Create Date: 2026-04-27 18:30:00.000000

Sprint 6 admin ships rename + structural-edit on ``equipment_categories``.
Today the table UPDATEs in place; that would silently mutate the
category every historical appraisal was authored against. Migration 014
brought ``category_inspection_prompts`` + ``category_red_flag_rules``
to a versioned model — this migration extends the same shape to the
parent ``equipment_categories`` table.

Schema:

- ``version`` (int, default 1, NOT NULL) — sequential within a slug.
  Admin's "rename" or other identity-affecting edit inserts a new row
  with ``version = max + 1`` and sets ``replaced_at`` on the old row.
- ``replaced_at`` (timestamptz, nullable) — when this version was
  superseded. ``replaced_at IS NULL`` = current.

Slug uniqueness:

- The column-level ``UNIQUE`` constraint on ``slug`` (set in migration 001)
  is replaced with a partial unique index that scopes uniqueness to
  current, non-deleted versions: ``WHERE replaced_at IS NULL AND
  deleted_at IS NULL``. This lets superseded rows share a slug with
  their successor while still preventing two live categories from
  colliding.

Backfill: every existing row defaults to version=1, replaced_at=NULL.
Production has no edits to date so this is a true no-op.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "019"
down_revision: str | None = "018"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "equipment_categories",
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column(
        "equipment_categories",
        sa.Column("replaced_at", sa.DateTime(timezone=True), nullable=True),
    )

    # Drop the column-level UNIQUE on slug (auto-named by Postgres as
    # ``equipment_categories_slug_key``) and replace with a partial
    # unique index scoped to the current, non-deleted version.
    op.execute(
        sa.text("ALTER TABLE equipment_categories DROP CONSTRAINT equipment_categories_slug_key")
    )
    op.create_index(
        "uq_equipment_categories_slug_current",
        "equipment_categories",
        ["slug"],
        unique=True,
        postgresql_where=sa.text("replaced_at IS NULL AND deleted_at IS NULL"),
    )

    # Single-seek "fetch current categories" matches the prompt + rule pattern.
    op.create_index(
        "ix_equipment_categories_current",
        "equipment_categories",
        ["display_order", "id"],
        postgresql_where=sa.text("replaced_at IS NULL AND deleted_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "ix_equipment_categories_current",
        table_name="equipment_categories",
    )
    op.drop_index(
        "uq_equipment_categories_slug_current",
        table_name="equipment_categories",
    )
    op.execute(
        sa.text(
            "ALTER TABLE equipment_categories ADD CONSTRAINT equipment_categories_slug_key "
            "UNIQUE (slug)"
        )
    )
    op.drop_column("equipment_categories", "replaced_at")
    op.drop_column("equipment_categories", "version")

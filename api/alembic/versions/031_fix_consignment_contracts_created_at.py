# ABOUTME: Fix migration — adds missing created_at column to consignment_contracts.
# ABOUTME: The original 001 migration omitted this column; seed scripts assumed it existed.
"""Fix — add created_at to consignment_contracts

Revision ID: 031
Revises: 030
Create Date: 2026-05-03 00:00:00.000000

The consignment_contracts table was created in migration 001 without a
created_at column. All other tables have this column and the Phase 6
seed script already references it. This migration adds the column with
a default of NOW() so existing rows are backfilled.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "031"
down_revision: str | None = "030"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "consignment_contracts",
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )


def downgrade() -> None:
    op.drop_column("consignment_contracts", "created_at")

"""phase5: extend comparable_sales with source_url, notes, created_by, deleted_at + indexes

Revision ID: 024
Revises: 023
Create Date: 2026-05-02
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "024"
down_revision: str = "023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The table was created in 001_init_schema with a minimal column set.
    # Sprint 3 adds the columns needed by valuation_service.search():
    # source_url, notes, created_by (FK → users), deleted_at.
    op.execute(sa.text("ALTER TABLE comparable_sales ADD COLUMN source_url TEXT"))
    op.execute(sa.text("ALTER TABLE comparable_sales ADD COLUMN notes TEXT"))
    op.execute(
        sa.text("ALTER TABLE comparable_sales ADD COLUMN created_by UUID REFERENCES users(id)")
    )
    op.execute(sa.text("ALTER TABLE comparable_sales ADD COLUMN deleted_at TIMESTAMPTZ"))

    # Restrict source to the three known provenance values.
    op.execute(
        sa.text(
            "ALTER TABLE comparable_sales ADD CONSTRAINT chk_comparable_sale_source "
            "CHECK (source IN ('internal', 'external', 'scraped'))"
        )
    )

    # Composite index for the primary search query (category + year + hours range filter).
    op.execute(
        sa.text(
            "CREATE INDEX ix_comparable_sales_category_year_hours "
            "ON comparable_sales (category_id, year, hours)"
        )
    )
    # Partial index for soft-delete — keeps all active-row scans fast.
    op.execute(
        sa.text(
            "CREATE INDEX ix_comparable_sales_active "
            "ON comparable_sales (category_id) WHERE deleted_at IS NULL"
        )
    )


def downgrade() -> None:
    op.execute(sa.text("DROP INDEX IF EXISTS ix_comparable_sales_active"))
    op.execute(sa.text("DROP INDEX IF EXISTS ix_comparable_sales_category_year_hours"))
    op.execute(
        sa.text(
            "ALTER TABLE comparable_sales DROP CONSTRAINT IF EXISTS chk_comparable_sale_source"
        )
    )
    op.execute(sa.text("ALTER TABLE comparable_sales DROP COLUMN IF EXISTS deleted_at"))
    op.execute(sa.text("ALTER TABLE comparable_sales DROP COLUMN IF EXISTS created_by"))
    op.execute(sa.text("ALTER TABLE comparable_sales DROP COLUMN IF EXISTS notes"))
    op.execute(sa.text("ALTER TABLE comparable_sales DROP COLUMN IF EXISTS source_url"))

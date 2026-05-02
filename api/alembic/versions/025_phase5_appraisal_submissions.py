# ABOUTME: Phase 5 Sprint 4 — extends appraisal_submissions with draft/submit lifecycle columns.
# ABOUTME: ALTER TABLE (table exists from migration 001); adds status, appraiser, version snapshot fields.
"""Phase 5 Sprint 4 — appraisal_submissions draft/submit extensions

Revision ID: 025
Revises: 024
Create Date: 2026-05-02 00:00:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "025"
down_revision: str | None = "024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Lifecycle + ownership columns
    op.execute(
        sa.text("""
        ALTER TABLE appraisal_submissions
            ADD COLUMN appraiser_id UUID REFERENCES users(id),
            ADD COLUMN status VARCHAR(20) NOT NULL DEFAULT 'draft',
            ADD COLUMN category_version INTEGER,
            ADD COLUMN prompt_version_set JSONB,
            ADD COLUMN rule_version_set JSONB,
            ADD COLUMN transport_notes TEXT,
            ADD COLUMN listing_notes TEXT,
            ADD COLUMN deleted_at TIMESTAMPTZ,
            ADD COLUMN created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            ADD COLUMN updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    """)
    )

    op.execute(
        sa.text("""
        ALTER TABLE appraisal_submissions
            ADD CONSTRAINT chk_appraisal_submission_status
            CHECK (status IN ('draft', 'submitted', 'under_review', 'approved', 'rejected'))
    """)
    )

    # Only one draft per equipment record at a time
    op.execute(
        sa.text("""
        CREATE UNIQUE INDEX uq_appraisal_submissions_one_draft
            ON appraisal_submissions(equipment_record_id)
            WHERE status = 'draft'
    """)
    )

    op.execute(
        sa.text("""
        CREATE INDEX ix_appraisal_submissions_appraiser_status
            ON appraisal_submissions(appraiser_id, status)
            WHERE deleted_at IS NULL
    """)
    )

    # set_updated_at() function was created in migration 002
    op.execute(
        sa.text("""
        CREATE TRIGGER set_appraisal_submissions_updated_at
            BEFORE UPDATE ON appraisal_submissions
            FOR EACH ROW EXECUTE FUNCTION set_updated_at()
    """)
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "DROP TRIGGER IF EXISTS set_appraisal_submissions_updated_at ON appraisal_submissions"
        )
    )
    op.execute(sa.text("DROP INDEX IF EXISTS ix_appraisal_submissions_appraiser_status"))
    op.execute(sa.text("DROP INDEX IF EXISTS uq_appraisal_submissions_one_draft"))
    op.execute(
        sa.text(
            "ALTER TABLE appraisal_submissions "
            "DROP CONSTRAINT IF EXISTS chk_appraisal_submission_status"
        )
    )
    op.execute(
        sa.text("""
        ALTER TABLE appraisal_submissions
            DROP COLUMN IF EXISTS appraiser_id,
            DROP COLUMN IF EXISTS status,
            DROP COLUMN IF EXISTS category_version,
            DROP COLUMN IF EXISTS prompt_version_set,
            DROP COLUMN IF EXISTS rule_version_set,
            DROP COLUMN IF EXISTS transport_notes,
            DROP COLUMN IF EXISTS listing_notes,
            DROP COLUMN IF EXISTS deleted_at,
            DROP COLUMN IF EXISTS created_at,
            DROP COLUMN IF EXISTS updated_at
    """)
    )

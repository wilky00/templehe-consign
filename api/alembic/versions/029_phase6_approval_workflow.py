# ABOUTME: Phase 6 Sprint 2 — adds rejection_notes, approved_by_id, and approved_at to appraisal_submissions.
# ABOUTME: No new tables; all columns are additions to the existing appraisal_submissions table.
"""Phase 6 Sprint 2 — manager approval workflow columns

Revision ID: 029
Revises: 028
Create Date: 2026-05-02 00:00:00.000000

Adds three nullable columns to appraisal_submissions that the manager
approval workflow writes:
  - rejection_notes TEXT: manager-written reason for rejection
  - approved_by_id UUID → users: who approved (NULL until approved)
  - approved_at TIMESTAMPTZ: when approved (NULL until approved)
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "029"
down_revision: str | None = "028"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        sa.text("""
        ALTER TABLE appraisal_submissions
            ADD COLUMN rejection_notes TEXT,
            ADD COLUMN approved_by_id UUID REFERENCES users(id),
            ADD COLUMN approved_at TIMESTAMPTZ
    """)
    )


def downgrade() -> None:
    op.execute(
        sa.text("""
        ALTER TABLE appraisal_submissions
            DROP COLUMN IF EXISTS approved_at,
            DROP COLUMN IF EXISTS approved_by_id,
            DROP COLUMN IF EXISTS rejection_notes
    """)
    )

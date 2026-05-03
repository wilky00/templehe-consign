# ABOUTME: Phase 6 Sprint 1 — widens score_band column and adds review_notes to appraisal_submissions.
# ABOUTME: No new tables; all Phase 6 approval columns were pre-created in migration 001.
"""Phase 6 Sprint 1 — appraisal_submissions scoring + review_notes columns

Revision ID: 028
Revises: 027
Create Date: 2026-05-02 00:00:00.000000

score_band was VARCHAR(20) in migration 001. Phase 6 label strings reach
33 characters ("Project, salvage, or parts-biased") — widen to VARCHAR(100).

review_notes is a server-written TEXT field appended to by RedFlagService
when the "hours_verified = false" condition fires; also used for any other
server-side advisory the approval workflow attaches.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "028"
down_revision: str | None = "027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        sa.text("""
        ALTER TABLE appraisal_submissions
            ALTER COLUMN score_band TYPE VARCHAR(100),
            ADD COLUMN review_notes TEXT
    """)
    )


def downgrade() -> None:
    op.execute(
        sa.text("""
        ALTER TABLE appraisal_submissions
            DROP COLUMN IF EXISTS review_notes,
            ALTER COLUMN score_band TYPE VARCHAR(20)
    """)
    )

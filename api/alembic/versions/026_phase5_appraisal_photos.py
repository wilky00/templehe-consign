# ABOUTME: Phase 5 Sprint 5 — adds sha256, content_type, gps_timestamp, created_at, deleted_at
# ABOUTME: to the existing appraisal_photos table; adds partial + unique indexes for retake logic.
"""Phase 5 Sprint 5 — extend appraisal_photos with EXIF + lifecycle columns

Revision ID: 026
Revises: 025
Create Date: 2026-05-02 00:00:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "026"
down_revision: str | None = "025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        sa.text("""
        ALTER TABLE appraisal_photos
            ADD COLUMN sha256 VARCHAR(64),
            ADD COLUMN content_type VARCHAR(100),
            ADD COLUMN gps_timestamp TIMESTAMPTZ,
            ADD COLUMN created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            ADD COLUMN deleted_at TIMESTAMPTZ
    """)
    )

    # Partial index for active-slot lookups (retake queries skip deleted rows)
    op.execute(
        sa.text("""
        CREATE INDEX ix_appraisal_photos_submission_slot
            ON appraisal_photos(appraisal_submission_id, slot_label)
            WHERE deleted_at IS NULL
    """)
    )

    # Prevent the same R2/GCS key from being finalized twice
    op.execute(
        sa.text("""
        CREATE UNIQUE INDEX uq_appraisal_photos_gcs_path
            ON appraisal_photos(gcs_path)
    """)
    )


def downgrade() -> None:
    op.execute(sa.text("DROP INDEX IF EXISTS uq_appraisal_photos_gcs_path"))
    op.execute(sa.text("DROP INDEX IF EXISTS ix_appraisal_photos_submission_slot"))
    op.execute(
        sa.text("""
        ALTER TABLE appraisal_photos
            DROP COLUMN IF EXISTS sha256,
            DROP COLUMN IF EXISTS content_type,
            DROP COLUMN IF EXISTS gps_timestamp,
            DROP COLUMN IF EXISTS created_at,
            DROP COLUMN IF EXISTS deleted_at
    """)
    )

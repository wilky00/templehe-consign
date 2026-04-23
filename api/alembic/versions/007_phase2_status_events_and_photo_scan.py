# ABOUTME: Phase 2 Sprint 3 — status_events audit trail + photo scan metadata.
# ABOUTME: Adds status_events (append-only) and scan_status/content_type/checksum on customer_intake_photos.
"""phase 2 status events and photo scan metadata

Revision ID: 007
Revises: 006
Create Date: 2026-04-23 10:00:00.000000

Adds:
- status_events — append-only audit log of every equipment_records.status
  transition. Drives the customer-facing status timeline on
  /me/equipment/{id}. Append-only at the DB layer via trigger, same
  pattern as audit_logs and user_consent_versions.
- customer_intake_photos gains scan_status, content_type, and sha256.
  scan_status scaffold-only this sprint (API writes 'pending' on
  finalize and never flips); real ClamAV integration is deferred.
  content_type + sha256 are captured on finalize so the appraiser UI
  can show MIME + a tamper-evident hash.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "007"
down_revision: str | None = "006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ------------------------------------------------------------------ #
    # status_events — append-only timeline of record status transitions
    # ------------------------------------------------------------------ #
    op.execute(
        sa.text("""
        CREATE TABLE status_events (
            id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            equipment_record_id UUID NOT NULL
              REFERENCES equipment_records(id) ON DELETE CASCADE,
            from_status         VARCHAR(40),
            to_status           VARCHAR(40) NOT NULL,
            changed_by          UUID REFERENCES users(id) ON DELETE SET NULL,
            note                TEXT,
            created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    )
    op.execute(
        sa.text(
            "CREATE INDEX ix_status_events_record_created "
            "ON status_events(equipment_record_id, created_at)"
        )
    )
    # Append-only at the DB layer. Tests & scripts that need to wipe rows
    # must drop the table or use ON DELETE CASCADE via the parent record.
    op.execute(
        sa.text("""
        CREATE OR REPLACE FUNCTION fn_status_events_append_only()
        RETURNS TRIGGER AS $$
        BEGIN
            RAISE EXCEPTION 'status_events is append-only';
        END;
        $$ LANGUAGE plpgsql
    """)
    )
    op.execute(
        sa.text("""
        CREATE TRIGGER trg_status_events_no_update
          BEFORE UPDATE ON status_events
          FOR EACH ROW EXECUTE FUNCTION fn_status_events_append_only()
    """)
    )

    # ------------------------------------------------------------------ #
    # customer_intake_photos — scan scaffold + MIME + checksum
    # ------------------------------------------------------------------ #
    op.execute(
        sa.text("""
        ALTER TABLE customer_intake_photos
          ADD COLUMN scan_status  VARCHAR(20) NOT NULL DEFAULT 'pending',
          ADD COLUMN content_type VARCHAR(100),
          ADD COLUMN sha256       VARCHAR(64)
    """)
    )
    op.execute(
        sa.text("""
        ALTER TABLE customer_intake_photos
          ADD CONSTRAINT chk_photo_scan_status CHECK (
            scan_status IN ('pending', 'clean', 'infected', 'failed')
          )
    """)
    )
    op.execute(
        sa.text(
            "CREATE INDEX ix_customer_intake_photos_scan_pending "
            "ON customer_intake_photos(uploaded_at) "
            "WHERE scan_status = 'pending'"
        )
    )


def downgrade() -> None:
    op.execute(sa.text("DROP INDEX IF EXISTS ix_customer_intake_photos_scan_pending"))
    op.execute(
        sa.text("""
        ALTER TABLE customer_intake_photos
          DROP CONSTRAINT IF EXISTS chk_photo_scan_status,
          DROP COLUMN IF EXISTS scan_status,
          DROP COLUMN IF EXISTS content_type,
          DROP COLUMN IF EXISTS sha256
    """)
    )
    op.execute(sa.text("DROP TRIGGER IF EXISTS trg_status_events_no_update ON status_events"))
    op.execute(sa.text("DROP FUNCTION IF EXISTS fn_status_events_append_only()"))
    op.execute(sa.text("DROP TABLE IF EXISTS status_events"))

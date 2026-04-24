# ABOUTME: Phase 2 Sprint 2 — customer intake fields + durable notification queue.
# ABOUTME: Adds equipment_records intake columns, customer_intake_photos child, notification_jobs.
"""phase 2 intake fields and notification queue

Revision ID: 006
Revises: 005
Create Date: 2026-04-23 00:00:00.000000

Adds:
- equipment_records gains customer-side intake columns: reference_number
  (public THE-XXXXXXXX), category_id FK, customer_make/model/year/serial/
  hours/running_status/ownership_type/location_text/description, and
  customer_submitted_at timestamp. AppraisalSubmission retains its
  appraiser-authored versions of the same fields — these are the
  customer's initial claims, the appraisal submission is the verified
  record.
- customer_intake_photos — child table holding R2 storage keys + captions
  for customer-uploaded intake photos. Sprint 2 persists metadata only;
  the actual signed-URL upload flow lands in Sprint 3.
- notification_jobs — Postgres-backed durable queue per ADR-001/012.
  temple-notifications Fly Machine drains it; retries with exponential
  backoff; idempotency_key guarantees one delivery per (user, event).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "006"
down_revision: str | None = "005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ------------------------------------------------------------------ #
    # equipment_records — customer intake columns
    # ------------------------------------------------------------------ #
    op.execute(
        sa.text("""
        ALTER TABLE equipment_records
          ADD COLUMN reference_number         VARCHAR(20) UNIQUE,
          ADD COLUMN category_id              UUID REFERENCES equipment_categories(id),
          ADD COLUMN customer_make            VARCHAR(100),
          ADD COLUMN customer_model           VARCHAR(100),
          ADD COLUMN customer_year            INTEGER,
          ADD COLUMN customer_serial_number   VARCHAR(100),
          ADD COLUMN customer_hours           INTEGER,
          ADD COLUMN customer_running_status  VARCHAR(20),
          ADD COLUMN customer_ownership_type  VARCHAR(20),
          ADD COLUMN customer_location_text   VARCHAR(255),
          ADD COLUMN customer_description     TEXT,
          ADD COLUMN customer_submitted_at    TIMESTAMPTZ
    """)
    )
    op.execute(
        sa.text(
            "CREATE INDEX ix_equipment_records_reference_number "
            "ON equipment_records(reference_number)"
        )
    )
    op.execute(
        sa.text("CREATE INDEX ix_equipment_records_category_id ON equipment_records(category_id)")
    )
    # CHECK constraints so service-layer validation is backed up at the DB.
    op.execute(
        sa.text("""
        ALTER TABLE equipment_records
          ADD CONSTRAINT chk_equipment_running_status CHECK (
            customer_running_status IS NULL OR customer_running_status IN
              ('running', 'partially_running', 'not_running')
          ),
          ADD CONSTRAINT chk_equipment_ownership_type CHECK (
            customer_ownership_type IS NULL OR customer_ownership_type IN
              ('owned', 'financed', 'leased', 'unknown')
          )
    """)
    )

    # ------------------------------------------------------------------ #
    # customer_intake_photos
    # ------------------------------------------------------------------ #
    op.execute(
        sa.text("""
        CREATE TABLE customer_intake_photos (
            id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            equipment_record_id UUID NOT NULL
              REFERENCES equipment_records(id) ON DELETE CASCADE,
            storage_key         VARCHAR(255) NOT NULL,
            caption             TEXT,
            display_order       INTEGER NOT NULL DEFAULT 0,
            uploaded_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    )
    op.execute(
        sa.text(
            "CREATE INDEX ix_customer_intake_photos_record "
            "ON customer_intake_photos(equipment_record_id, display_order)"
        )
    )

    # ------------------------------------------------------------------ #
    # notification_jobs — durable Postgres-backed queue
    # ------------------------------------------------------------------ #
    op.execute(
        sa.text("""
        CREATE TABLE notification_jobs (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            idempotency_key VARCHAR(120) NOT NULL UNIQUE,
            user_id         UUID REFERENCES users(id) ON DELETE SET NULL,
            channel         VARCHAR(20) NOT NULL,
            template        VARCHAR(100) NOT NULL,
            payload         JSONB NOT NULL DEFAULT '{}'::jsonb,
            status          VARCHAR(20) NOT NULL DEFAULT 'pending',
            attempts        INTEGER NOT NULL DEFAULT 0,
            max_attempts    INTEGER NOT NULL DEFAULT 5,
            scheduled_for   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            processed_at    TIMESTAMPTZ,
            last_error      TEXT,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    )
    op.execute(
        sa.text("""
        ALTER TABLE notification_jobs
          ADD CONSTRAINT chk_notification_channel CHECK (
            channel IN ('email', 'sms')
          ),
          ADD CONSTRAINT chk_notification_status CHECK (
            status IN ('pending', 'processing', 'delivered', 'failed', 'skipped')
          )
    """)
    )
    op.execute(
        sa.text(
            "CREATE INDEX ix_notification_jobs_ready "
            "ON notification_jobs(scheduled_for) "
            "WHERE status = 'pending'"
        )
    )
    op.execute(sa.text("CREATE INDEX ix_notification_jobs_user ON notification_jobs(user_id)"))
    # Keep updated_at honest — reuse the generic trigger from migration 001/002.
    op.execute(
        sa.text("""
        CREATE TRIGGER trg_notification_jobs_updated_at
          BEFORE UPDATE ON notification_jobs
          FOR EACH ROW EXECUTE FUNCTION set_updated_at()
    """)
    )


def downgrade() -> None:
    op.execute(
        sa.text("DROP TRIGGER IF EXISTS trg_notification_jobs_updated_at ON notification_jobs")
    )
    op.execute(sa.text("DROP TABLE IF EXISTS notification_jobs"))
    op.execute(sa.text("DROP TABLE IF EXISTS customer_intake_photos"))
    op.execute(
        sa.text("""
        ALTER TABLE equipment_records
          DROP CONSTRAINT IF EXISTS chk_equipment_running_status,
          DROP CONSTRAINT IF EXISTS chk_equipment_ownership_type
    """)
    )
    op.execute(
        sa.text("""
        ALTER TABLE equipment_records
          DROP COLUMN IF EXISTS reference_number,
          DROP COLUMN IF EXISTS category_id,
          DROP COLUMN IF EXISTS customer_make,
          DROP COLUMN IF EXISTS customer_model,
          DROP COLUMN IF EXISTS customer_year,
          DROP COLUMN IF EXISTS customer_serial_number,
          DROP COLUMN IF EXISTS customer_hours,
          DROP COLUMN IF EXISTS customer_running_status,
          DROP COLUMN IF EXISTS customer_ownership_type,
          DROP COLUMN IF EXISTS customer_location_text,
          DROP COLUMN IF EXISTS customer_description,
          DROP COLUMN IF EXISTS customer_submitted_at
    """)
    )

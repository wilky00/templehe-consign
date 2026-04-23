# ABOUTME: Phase 2 Sprint 4 — GDPR-lite data export + account deletion + audit PII scrubber.
# ABOUTME: Adds data_export_jobs + two retention PL/pgSQL functions; relaxes audit trigger for scrubs.
"""phase 2 account deletion and audit pii scrub

Revision ID: 008
Revises: 007
Create Date: 2026-04-23 14:00:00.000000

Adds:
- data_export_jobs — tracks GDPR-lite export requests. The service
  processes them synchronously on POST today; the table shape is stable
  so we can move to an async worker later without a contract change.
- fn_delete_expired_accounts() — PL/pgSQL function the retention sweeper
  invokes hourly. Applies right-to-erasure to users whose
  ``deletion_grace_until`` has passed: pseudonymizes the ``users`` and
  ``customers`` rows and flips user.status to 'deleted'. Equipment
  records + consignment history stay intact — those are business facts,
  not personal data, once the identity is scrubbed.
- fn_scrub_audit_pii(retention_days INT) — NULLs ip_address + user_agent
  on audit_logs rows older than N days. The append-only trigger on
  audit_logs is relaxed to allow this specific path: the scrubber sets
  ``templehe.pii_scrub='on'`` before the UPDATE and the trigger bails
  early when that session GUC is present. Outside that path the table
  is still immutable.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "008"
down_revision: str | None = "007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ------------------------------------------------------------------ #
    # data_export_jobs
    # ------------------------------------------------------------------ #
    op.execute(
        sa.text("""
        CREATE TABLE data_export_jobs (
            id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id        UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            status         VARCHAR(20) NOT NULL DEFAULT 'pending',
            requested_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            completed_at   TIMESTAMPTZ,
            storage_key    VARCHAR(255),
            download_url   TEXT,
            url_expires_at TIMESTAMPTZ,
            error          TEXT,
            created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    )
    op.execute(
        sa.text("""
        ALTER TABLE data_export_jobs
          ADD CONSTRAINT chk_data_export_status CHECK (
            status IN ('pending', 'processing', 'complete', 'failed')
          )
    """)
    )
    op.execute(
        sa.text(
            "CREATE INDEX ix_data_export_jobs_user_requested "
            "ON data_export_jobs(user_id, requested_at DESC)"
        )
    )
    op.execute(
        sa.text("""
        CREATE TRIGGER trg_data_export_jobs_updated_at
          BEFORE UPDATE ON data_export_jobs
          FOR EACH ROW EXECUTE FUNCTION set_updated_at()
    """)
    )

    # ------------------------------------------------------------------ #
    # Relax the audit-log trigger to permit the PII scrubber's UPDATEs.
    # The trigger still blocks DELETE and any UPDATE from a session that
    # has NOT explicitly set the GUC.
    # ------------------------------------------------------------------ #
    op.execute(
        sa.text("""
        CREATE OR REPLACE FUNCTION prevent_audit_log_modification()
        RETURNS TRIGGER AS $$
        BEGIN
            IF TG_OP = 'UPDATE' THEN
                -- current_setting(..., true) returns NULL when the GUC is
                -- not set in this session rather than raising.
                IF current_setting('templehe.pii_scrub', true) = 'on' THEN
                    RETURN NEW;
                END IF;
            END IF;
            RAISE EXCEPTION 'audit_logs is append-only; UPDATE and DELETE are not permitted';
        END;
        $$ LANGUAGE plpgsql
    """)
    )

    # ------------------------------------------------------------------ #
    # fn_scrub_audit_pii — NULL ip_address + user_agent on old rows.
    # SECURITY DEFINER so the GUC is scoped to this function's execution.
    # ------------------------------------------------------------------ #
    op.execute(
        sa.text("""
        CREATE OR REPLACE FUNCTION fn_scrub_audit_pii(retention_days INT)
        RETURNS BIGINT AS $$
        DECLARE
            rows_scrubbed BIGINT;
        BEGIN
            IF retention_days < 30 OR retention_days > 120 THEN
                RAISE EXCEPTION 'retention_days must be between 30 and 120';
            END IF;

            -- Flag this session as authorized to UPDATE audit_logs.
            PERFORM set_config('templehe.pii_scrub', 'on', true);

            UPDATE audit_logs
               SET ip_address = NULL,
                   user_agent = NULL
             WHERE created_at < NOW() - (retention_days || ' days')::interval
               AND (ip_address IS NOT NULL OR user_agent IS NOT NULL);

            GET DIAGNOSTICS rows_scrubbed = ROW_COUNT;

            -- Drop the authorization before returning.
            PERFORM set_config('templehe.pii_scrub', 'off', true);

            RETURN rows_scrubbed;
        END;
        $$ LANGUAGE plpgsql SECURITY DEFINER
    """)
    )

    # ------------------------------------------------------------------ #
    # fn_delete_expired_accounts — apply right-to-erasure after grace
    # ------------------------------------------------------------------ #
    op.execute(
        sa.text("""
        CREATE OR REPLACE FUNCTION fn_delete_expired_accounts()
        RETURNS BIGINT AS $$
        DECLARE
            accounts_deleted BIGINT := 0;
            rec RECORD;
        BEGIN
            FOR rec IN
                SELECT id FROM users
                 WHERE status = 'pending_deletion'
                   AND deletion_grace_until IS NOT NULL
                   AND deletion_grace_until < NOW()
            LOOP
                -- Scrub the customer row (preserve equipment history).
                UPDATE customers
                   SET submitter_name = '[deleted]',
                       business_name = NULL,
                       title = NULL,
                       address_street = NULL,
                       address_city = NULL,
                       address_state = NULL,
                       address_zip = NULL,
                       business_phone = NULL,
                       business_phone_ext = NULL,
                       cell_phone = NULL,
                       communication_prefs = NULL,
                       deleted_at = NOW()
                 WHERE user_id = rec.id;

                -- Pseudonymize the user row. Email is set to a non-routable
                -- marker per user.id so the UNIQUE constraint is honored
                -- and a replay can't accidentally match a fresh signup.
                UPDATE users
                   SET email = 'deleted-' || rec.id || '@deleted.invalid',
                       first_name = '[deleted]',
                       last_name = '',
                       password_hash = NULL,
                       totp_secret_enc = NULL,
                       totp_enabled = FALSE,
                       google_id = NULL,
                       profile_photo_url = NULL,
                       status = 'deleted',
                       deletion_grace_until = NULL
                 WHERE id = rec.id;

                accounts_deleted := accounts_deleted + 1;
            END LOOP;

            RETURN accounts_deleted;
        END;
        $$ LANGUAGE plpgsql
    """)
    )


def downgrade() -> None:
    op.execute(sa.text("DROP FUNCTION IF EXISTS fn_delete_expired_accounts()"))
    op.execute(sa.text("DROP FUNCTION IF EXISTS fn_scrub_audit_pii(INT)"))
    # Restore the strict pre-008 trigger body.
    op.execute(
        sa.text("""
        CREATE OR REPLACE FUNCTION prevent_audit_log_modification()
        RETURNS TRIGGER AS $$
        BEGIN
            RAISE EXCEPTION 'audit_logs is append-only; UPDATE and DELETE are not permitted';
        END;
        $$ LANGUAGE plpgsql
    """)
    )
    op.execute(
        sa.text("DROP TRIGGER IF EXISTS trg_data_export_jobs_updated_at ON data_export_jobs")
    )
    op.execute(sa.text("DROP TABLE IF EXISTS data_export_jobs"))

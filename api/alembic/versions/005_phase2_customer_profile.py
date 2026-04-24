# ABOUTME: Phase 2 Sprint 1 — customer profile & legal consent tracking.
# ABOUTME: Adds user_consent_versions archive, deletion grace, and app_config defaults.
"""phase 2 customer profile & consent archive

Revision ID: 005
Revises: 004
Create Date: 2026-04-22 00:00:00.000000

Adds:
- users.deletion_grace_until — 30-day soft-delete window (Epic 2.6).
- user_consent_versions — immutable archive of every ToS/Privacy acceptance
  so a version bump re-accept leaves an audit trail. users.tos_version /
  privacy_version continue to hold the *current* accepted version for fast
  lookup; the archive lets us prove when, from what IP, under what version.
- app_config defaults: tos_current_version, privacy_current_version,
  audit_pii_retention_days, audit_row_retention_months.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "005"
down_revision: str | None = "004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(sa.text("ALTER TABLE users ADD COLUMN deletion_grace_until TIMESTAMPTZ"))

    op.execute(
        sa.text("""
        CREATE TABLE user_consent_versions (
            id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id       UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            consent_type  VARCHAR(20) NOT NULL CHECK (consent_type IN ('tos', 'privacy')),
            version       VARCHAR(20) NOT NULL,
            accepted_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            ip_address    VARCHAR(45),
            user_agent    VARCHAR(512)
        )
    """)
    )
    op.execute(
        sa.text("CREATE INDEX ix_user_consent_versions_user_id ON user_consent_versions(user_id)")
    )
    op.execute(
        sa.text(
            "CREATE INDEX ix_user_consent_versions_lookup "
            "ON user_consent_versions(user_id, consent_type, version)"
        )
    )

    # Immutable archive — block UPDATE/DELETE at the DB layer.
    op.execute(
        sa.text("""
        CREATE OR REPLACE FUNCTION fn_consent_versions_append_only()
        RETURNS TRIGGER AS $$
        BEGIN
            RAISE EXCEPTION 'user_consent_versions is append-only';
        END;
        $$ LANGUAGE plpgsql
    """)
    )
    op.execute(
        sa.text("""
        CREATE TRIGGER trg_consent_versions_no_update
        BEFORE UPDATE OR DELETE ON user_consent_versions
        FOR EACH ROW EXECUTE FUNCTION fn_consent_versions_append_only()
    """)
    )

    # Seed app_config defaults. ON CONFLICT keeps re-runs idempotent if an
    # operator has already set a value out-of-band. jsonb_build_object avoids
    # SQLAlchemy's text-mode parser treating colons inside JSON literals as
    # bind parameters.
    op.execute(
        sa.text("""
        INSERT INTO app_config (key, value, category, field_type) VALUES
          (
            'tos_current_version',
            jsonb_build_object('version', '1'),
            'legal', 'json'
          ),
          (
            'privacy_current_version',
            jsonb_build_object('version', '1'),
            'legal', 'json'
          ),
          (
            'audit_pii_retention_days',
            jsonb_build_object('days', 30, 'min', 30, 'max', 120, 'step', 30),
            'retention', 'json'
          ),
          (
            'audit_row_retention_months',
            jsonb_build_object('months', 12),
            'retention', 'json'
          )
        ON CONFLICT (key) DO NOTHING
    """)
    )


def downgrade() -> None:
    op.execute(
        sa.text("""
        DELETE FROM app_config
        WHERE key IN (
            'tos_current_version',
            'privacy_current_version',
            'audit_pii_retention_days',
            'audit_row_retention_months'
        )
    """)
    )
    op.execute(
        sa.text("DROP TRIGGER IF EXISTS trg_consent_versions_no_update ON user_consent_versions")
    )
    op.execute(sa.text("DROP FUNCTION IF EXISTS fn_consent_versions_append_only()"))
    op.execute(sa.text("DROP TABLE IF EXISTS user_consent_versions"))
    op.execute(sa.text("ALTER TABLE users DROP COLUMN IF EXISTS deletion_grace_until"))

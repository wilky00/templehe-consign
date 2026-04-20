# ABOUTME: Initial schema migration creating all TempleHE platform tables.
# ABOUTME: Includes append-only trigger on audit_logs, updated_at triggers, and composite indexes.
"""Initial schema

Revision ID: 001
Revises:
Create Date: 2026-04-20 00:00:00.000000

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(sa.text("CREATE EXTENSION IF NOT EXISTS pgcrypto"))

    # ------------------------------------------------------------------ #
    # roles
    # ------------------------------------------------------------------ #
    op.execute(sa.text("""
        CREATE TABLE roles (
            id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            slug        VARCHAR(50)  NOT NULL UNIQUE,
            display_name VARCHAR(100) NOT NULL
        )
    """))

    # ------------------------------------------------------------------ #
    # users
    # ------------------------------------------------------------------ #
    op.execute(sa.text("""
        CREATE TABLE users (
            id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            email                 VARCHAR(255) NOT NULL UNIQUE,
            password_hash         VARCHAR(255),
            first_name            VARCHAR(100) NOT NULL,
            last_name             VARCHAR(100) NOT NULL,
            role_id               UUID NOT NULL REFERENCES roles(id),
            status                VARCHAR(30)  NOT NULL DEFAULT 'pending_verification',
            google_id             VARCHAR(255) UNIQUE,
            totp_secret_enc       TEXT,
            totp_enabled          BOOLEAN NOT NULL DEFAULT FALSE,
            profile_photo_url     VARCHAR(512),
            tos_accepted_at       TIMESTAMPTZ,
            tos_version           VARCHAR(20),
            privacy_accepted_at   TIMESTAMPTZ,
            privacy_version       VARCHAR(20),
            deletion_requested_at TIMESTAMPTZ,
            failed_login_count    INTEGER NOT NULL DEFAULT 0,
            locked_until          TIMESTAMPTZ,
            created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at            TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """))
    op.execute(sa.text("CREATE INDEX ix_users_email ON users(email)"))
    op.execute(sa.text("CREATE INDEX ix_users_role_id ON users(role_id)"))

    # ------------------------------------------------------------------ #
    # user_sessions  (opaque refresh tokens — replaces Redis in POC)
    # ------------------------------------------------------------------ #
    op.execute(sa.text("""
        CREATE TABLE user_sessions (
            id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id     UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            token_hash  VARCHAR(128) NOT NULL UNIQUE,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            expires_at  TIMESTAMPTZ NOT NULL,
            revoked_at  TIMESTAMPTZ,
            ip_address  VARCHAR(45),
            user_agent  VARCHAR(512)
        )
    """))
    op.execute(sa.text("CREATE INDEX ix_user_sessions_user_id ON user_sessions(user_id)"))
    op.execute(sa.text(
        "CREATE INDEX ix_user_sessions_expires ON user_sessions(expires_at)"
        " WHERE revoked_at IS NULL"
    ))

    # ------------------------------------------------------------------ #
    # totp_recovery_codes
    # ------------------------------------------------------------------ #
    op.execute(sa.text("""
        CREATE TABLE totp_recovery_codes (
            id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id   UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            code_hash VARCHAR(255) NOT NULL,
            used_at   TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """))
    op.execute(sa.text(
        "CREATE INDEX ix_totp_recovery_codes_user_id ON totp_recovery_codes(user_id)"
    ))

    # ------------------------------------------------------------------ #
    # known_devices
    # ------------------------------------------------------------------ #
    op.execute(sa.text("""
        CREATE TABLE known_devices (
            id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id            UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            device_fingerprint VARCHAR(128) NOT NULL,
            first_seen_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE(user_id, device_fingerprint)
        )
    """))

    # ------------------------------------------------------------------ #
    # notification_preferences
    # ------------------------------------------------------------------ #
    op.execute(sa.text("""
        CREATE TABLE notification_preferences (
            id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id      UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            channel      VARCHAR(20) NOT NULL,
            slack_user_id VARCHAR(100),
            phone_number VARCHAR(20)
        )
    """))
    op.execute(sa.text(
        "CREATE INDEX ix_notification_prefs_user_id ON notification_preferences(user_id)"
    ))

    # ------------------------------------------------------------------ #
    # rate_limit_counters  (replaces Redis in POC)
    # ------------------------------------------------------------------ #
    op.execute(sa.text("""
        CREATE TABLE rate_limit_counters (
            id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            key          VARCHAR(255) NOT NULL,
            window_start TIMESTAMPTZ  NOT NULL,
            count        INTEGER      NOT NULL DEFAULT 1,
            UNIQUE(key, window_start)
        )
    """))
    op.execute(sa.text(
        "CREATE INDEX ix_rate_limit_counters_key_window ON rate_limit_counters(key, window_start)"
    ))

    # ------------------------------------------------------------------ #
    # equipment_categories
    # ------------------------------------------------------------------ #
    op.execute(sa.text("""
        CREATE TABLE equipment_categories (
            id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            name          VARCHAR(100) NOT NULL,
            slug          VARCHAR(100) NOT NULL UNIQUE,
            status        VARCHAR(20)  NOT NULL DEFAULT 'active',
            display_order INTEGER      NOT NULL DEFAULT 0,
            created_by    UUID REFERENCES users(id),
            created_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            updated_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            deleted_at    TIMESTAMPTZ
        )
    """))
    op.execute(sa.text("CREATE INDEX ix_equipment_categories_slug ON equipment_categories(slug)"))
    op.execute(sa.text(
        "CREATE INDEX ix_equipment_categories_status ON equipment_categories(status)"
        " WHERE deleted_at IS NULL"
    ))

    # ------------------------------------------------------------------ #
    # category_components
    # ------------------------------------------------------------------ #
    op.execute(sa.text("""
        CREATE TABLE category_components (
            id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            category_id   UUID NOT NULL REFERENCES equipment_categories(id),
            name          VARCHAR(100) NOT NULL,
            weight_pct    NUMERIC(6,4) NOT NULL,
            display_order INTEGER NOT NULL DEFAULT 0,
            active        BOOLEAN NOT NULL DEFAULT TRUE
        )
    """))
    op.execute(sa.text(
        "CREATE INDEX ix_category_components_category_id ON category_components(category_id)"
    ))

    # ------------------------------------------------------------------ #
    # category_inspection_prompts
    # ------------------------------------------------------------------ #
    op.execute(sa.text("""
        CREATE TABLE category_inspection_prompts (
            id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            category_id   UUID NOT NULL REFERENCES equipment_categories(id),
            label         VARCHAR(255) NOT NULL,
            response_type VARCHAR(20)  NOT NULL,
            required      BOOLEAN NOT NULL DEFAULT TRUE,
            display_order INTEGER NOT NULL DEFAULT 0,
            active        BOOLEAN NOT NULL DEFAULT TRUE
        )
    """))
    op.execute(sa.text(
        "CREATE INDEX ix_category_inspection_prompts_cat"
        " ON category_inspection_prompts(category_id)"
    ))

    # ------------------------------------------------------------------ #
    # category_attachments
    # ------------------------------------------------------------------ #
    op.execute(sa.text("""
        CREATE TABLE category_attachments (
            id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            category_id   UUID NOT NULL REFERENCES equipment_categories(id),
            label         VARCHAR(255) NOT NULL,
            description   TEXT,
            display_order INTEGER NOT NULL DEFAULT 0,
            active        BOOLEAN NOT NULL DEFAULT TRUE
        )
    """))
    op.execute(sa.text(
        "CREATE INDEX ix_category_attachments_category_id ON category_attachments(category_id)"
    ))

    # ------------------------------------------------------------------ #
    # category_photo_slots
    # ------------------------------------------------------------------ #
    op.execute(sa.text("""
        CREATE TABLE category_photo_slots (
            id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            category_id   UUID NOT NULL REFERENCES equipment_categories(id),
            label         VARCHAR(255) NOT NULL,
            helper_text   TEXT,
            required      BOOLEAN NOT NULL DEFAULT TRUE,
            display_order INTEGER NOT NULL DEFAULT 0,
            active        BOOLEAN NOT NULL DEFAULT TRUE
        )
    """))
    op.execute(sa.text(
        "CREATE INDEX ix_category_photo_slots_category_id ON category_photo_slots(category_id)"
    ))

    # ------------------------------------------------------------------ #
    # category_red_flag_rules
    # ------------------------------------------------------------------ #
    op.execute(sa.text("""
        CREATE TABLE category_red_flag_rules (
            id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            category_id        UUID NOT NULL REFERENCES equipment_categories(id),
            condition_field    VARCHAR(100) NOT NULL,
            condition_operator VARCHAR(20)  NOT NULL,
            condition_value    VARCHAR(255),
            actions            JSONB NOT NULL DEFAULT '{}',
            label              VARCHAR(255) NOT NULL,
            active             BOOLEAN NOT NULL DEFAULT TRUE
        )
    """))
    op.execute(sa.text(
        "CREATE INDEX ix_category_red_flag_rules_cat ON category_red_flag_rules(category_id)"
    ))

    # ------------------------------------------------------------------ #
    # customers
    # ------------------------------------------------------------------ #
    op.execute(sa.text("""
        CREATE TABLE customers (
            id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id            UUID NOT NULL UNIQUE REFERENCES users(id),
            business_name      VARCHAR(200),
            submitter_name     VARCHAR(200) NOT NULL,
            title              VARCHAR(100),
            address_street     VARCHAR(255),
            address_city       VARCHAR(100),
            address_state      CHAR(2),
            address_zip        VARCHAR(10),
            business_phone     VARCHAR(20),
            business_phone_ext VARCHAR(10),
            cell_phone         VARCHAR(20),
            communication_prefs JSONB,
            created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            deleted_at         TIMESTAMPTZ
        )
    """))
    op.execute(sa.text("CREATE INDEX ix_customers_user_id ON customers(user_id)"))

    # ------------------------------------------------------------------ #
    # equipment_records
    # ------------------------------------------------------------------ #
    op.execute(sa.text("""
        CREATE TABLE equipment_records (
            id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            customer_id           UUID NOT NULL REFERENCES customers(id),
            status                VARCHAR(40) NOT NULL DEFAULT 'new_request',
            assigned_sales_rep_id UUID REFERENCES users(id),
            assigned_appraiser_id UUID REFERENCES users(id),
            created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            deleted_at            TIMESTAMPTZ
        )
    """))
    op.execute(sa.text(
        "CREATE INDEX ix_equipment_records_customer_status "
        "ON equipment_records(customer_id, status) WHERE deleted_at IS NULL"
    ))
    op.execute(sa.text(
        "CREATE INDEX ix_equipment_records_sales_rep "
        "ON equipment_records(assigned_sales_rep_id) WHERE deleted_at IS NULL"
    ))

    # ------------------------------------------------------------------ #
    # appraisal_submissions
    # ------------------------------------------------------------------ #
    op.execute(sa.text("""
        CREATE TABLE appraisal_submissions (
            id                          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            equipment_record_id         UUID NOT NULL REFERENCES equipment_records(id),
            category_id                 UUID REFERENCES equipment_categories(id),
            make                        VARCHAR(100),
            model                       VARCHAR(100),
            year                        INTEGER,
            hours_condition             VARCHAR(50),
            running_status              VARCHAR(50),
            serial_number               VARCHAR(100),
            title_status                VARCHAR(50),
            overall_score               NUMERIC(5,2),
            score_band                  VARCHAR(20),
            management_review_required  BOOLEAN NOT NULL DEFAULT FALSE,
            hold_for_title_review       BOOLEAN NOT NULL DEFAULT FALSE,
            marketability_rating        VARCHAR(20),
            approved_purchase_offer     NUMERIC(12,2),
            suggested_consignment_price NUMERIC(12,2),
            red_flags                   JSONB,
            comparable_sales_data       JSONB,
            field_values                JSONB,
            submitted_at                TIMESTAMPTZ
        )
    """))
    op.execute(sa.text(
        "CREATE INDEX ix_appraisal_submissions_record "
        "ON appraisal_submissions(equipment_record_id)"
    ))

    # ------------------------------------------------------------------ #
    # appraisal_photos
    # ------------------------------------------------------------------ #
    op.execute(sa.text("""
        CREATE TABLE appraisal_photos (
            id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            appraisal_submission_id UUID NOT NULL REFERENCES appraisal_submissions(id),
            slot_label            VARCHAR(255) NOT NULL,
            gcs_path              VARCHAR(512) NOT NULL,
            capture_timestamp     TIMESTAMPTZ,
            gps_latitude          NUMERIC(10,7),
            gps_longitude         NUMERIC(10,7),
            gps_missing           BOOLEAN NOT NULL DEFAULT FALSE,
            gps_out_of_range      BOOLEAN NOT NULL DEFAULT FALSE,
            file_size_bytes       INTEGER
        )
    """))
    op.execute(sa.text(
        "CREATE INDEX ix_appraisal_photos_submission "
        "ON appraisal_photos(appraisal_submission_id)"
    ))

    # ------------------------------------------------------------------ #
    # component_scores
    # ------------------------------------------------------------------ #
    op.execute(sa.text("""
        CREATE TABLE component_scores (
            id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            appraisal_submission_id UUID NOT NULL REFERENCES appraisal_submissions(id),
            category_component_id   UUID NOT NULL REFERENCES category_components(id),
            raw_score               NUMERIC(3,2) NOT NULL,
            weight_at_time_of_scoring NUMERIC(6,4) NOT NULL,
            notes                   TEXT
        )
    """))
    op.execute(sa.text(
        "CREATE INDEX ix_component_scores_submission ON component_scores(appraisal_submission_id)"
    ))

    # ------------------------------------------------------------------ #
    # appraisal_reports
    # ------------------------------------------------------------------ #
    op.execute(sa.text("""
        CREATE TABLE appraisal_reports (
            id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            equipment_record_id     UUID NOT NULL REFERENCES equipment_records(id),
            appraisal_submission_id UUID REFERENCES appraisal_submissions(id),
            gcs_path                VARCHAR(512) NOT NULL,
            generated_at            TIMESTAMPTZ  NOT NULL DEFAULT NOW()
        )
    """))

    # ------------------------------------------------------------------ #
    # consignment_contracts
    # ------------------------------------------------------------------ #
    op.execute(sa.text("""
        CREATE TABLE consignment_contracts (
            id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            equipment_record_id UUID NOT NULL UNIQUE REFERENCES equipment_records(id),
            envelope_id         VARCHAR(255),
            status              VARCHAR(20) NOT NULL DEFAULT 'sent',
            signed_at           TIMESTAMPTZ
        )
    """))

    # ------------------------------------------------------------------ #
    # change_requests
    # ------------------------------------------------------------------ #
    op.execute(sa.text("""
        CREATE TABLE change_requests (
            id                        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            equipment_record_id       UUID NOT NULL REFERENCES equipment_records(id),
            request_type              VARCHAR(30) NOT NULL,
            customer_notes            TEXT,
            status                    VARCHAR(20) NOT NULL DEFAULT 'pending',
            resolution_notes          TEXT,
            requires_manager_reapproval BOOLEAN NOT NULL DEFAULT FALSE,
            submitted_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            resolved_at               TIMESTAMPTZ
        )
    """))
    op.execute(sa.text(
        "CREATE INDEX ix_change_requests_record ON change_requests(equipment_record_id)"
    ))

    # ------------------------------------------------------------------ #
    # lead_routing_rules
    # ------------------------------------------------------------------ #
    op.execute(sa.text("""
        CREATE TABLE lead_routing_rules (
            id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            rule_type        VARCHAR(20) NOT NULL,
            priority         INTEGER     NOT NULL DEFAULT 0,
            conditions       JSONB,
            assigned_user_id UUID REFERENCES users(id),
            round_robin_index INTEGER NOT NULL DEFAULT 0,
            is_active        BOOLEAN NOT NULL DEFAULT TRUE
        )
    """))

    # ------------------------------------------------------------------ #
    # calendar_events
    # ------------------------------------------------------------------ #
    op.execute(sa.text("""
        CREATE TABLE calendar_events (
            id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            equipment_record_id     UUID NOT NULL REFERENCES equipment_records(id),
            appraiser_id            UUID NOT NULL REFERENCES users(id),
            scheduled_at            TIMESTAMPTZ NOT NULL,
            duration_minutes        INTEGER NOT NULL DEFAULT 60,
            site_address            TEXT,
            drive_time_buffer_minutes INTEGER NOT NULL DEFAULT 30,
            cancelled_at            TIMESTAMPTZ
        )
    """))
    op.execute(sa.text(
        "CREATE INDEX ix_calendar_events_appraiser_time "
        "ON calendar_events(appraiser_id, scheduled_at) WHERE cancelled_at IS NULL"
    ))

    # ------------------------------------------------------------------ #
    # public_listings
    # ------------------------------------------------------------------ #
    op.execute(sa.text("""
        CREATE TABLE public_listings (
            id                     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            equipment_record_id    UUID NOT NULL UNIQUE REFERENCES equipment_records(id),
            listing_title          VARCHAR(255) NOT NULL,
            asking_price           NUMERIC(12,2),
            primary_photo_gcs_path VARCHAR(512),
            status                 VARCHAR(20) NOT NULL DEFAULT 'active',
            published_at           TIMESTAMPTZ,
            sold_at                TIMESTAMPTZ
        )
    """))
    op.execute(sa.text(
        "CREATE INDEX ix_public_listings_status ON public_listings(status) WHERE status = 'active'"
    ))

    # ------------------------------------------------------------------ #
    # audit_logs  (append-only — trigger blocks UPDATE/DELETE)
    # ------------------------------------------------------------------ #
    op.execute(sa.text("""
        CREATE TABLE audit_logs (
            id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            event_type  VARCHAR(100) NOT NULL,
            actor_id    UUID REFERENCES users(id),
            actor_role  VARCHAR(50),
            target_type VARCHAR(50),
            target_id   UUID,
            before_state JSONB,
            after_state  JSONB,
            ip_address  VARCHAR(45),
            user_agent  VARCHAR(512),
            created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """))
    op.execute(sa.text(
        "CREATE INDEX ix_audit_logs_actor ON audit_logs(actor_id, created_at)"
    ))
    op.execute(sa.text(
        "CREATE INDEX ix_audit_logs_target ON audit_logs(target_id, target_type, created_at)"
    ))
    op.execute(sa.text(
        "CREATE INDEX ix_audit_logs_event_type ON audit_logs(event_type, created_at)"
    ))

    # ------------------------------------------------------------------ #
    # record_locks
    # ------------------------------------------------------------------ #
    op.execute(sa.text("""
        CREATE TABLE record_locks (
            id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            record_id     UUID NOT NULL,
            record_type   VARCHAR(50) NOT NULL,
            locked_by     UUID NOT NULL REFERENCES users(id),
            locked_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            expires_at    TIMESTAMPTZ NOT NULL,
            overridden_by UUID REFERENCES users(id),
            overridden_at TIMESTAMPTZ,
            UNIQUE(record_id, record_type)
        )
    """))
    op.execute(sa.text(
        "CREATE INDEX ix_record_locks_expires ON record_locks(expires_at)"
    ))

    # ------------------------------------------------------------------ #
    # app_config
    # ------------------------------------------------------------------ #
    op.execute(sa.text("""
        CREATE TABLE app_config (
            id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            key        VARCHAR(255) NOT NULL UNIQUE,
            value      JSONB NOT NULL,
            category   VARCHAR(100),
            field_type VARCHAR(50),
            updated_by UUID REFERENCES users(id),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """))

    # ------------------------------------------------------------------ #
    # analytics_events
    # ------------------------------------------------------------------ #
    op.execute(sa.text("""
        CREATE TABLE analytics_events (
            id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            session_id VARCHAR(100),
            user_id    UUID REFERENCES users(id),
            event_type VARCHAR(100) NOT NULL,
            page       VARCHAR(255),
            metadata   JSONB,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """))
    op.execute(sa.text(
        "CREATE INDEX ix_analytics_events_user ON analytics_events(user_id, created_at)"
    ))

    # ------------------------------------------------------------------ #
    # inquiries
    # ------------------------------------------------------------------ #
    op.execute(sa.text("""
        CREATE TABLE inquiries (
            id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            public_listing_id UUID NOT NULL REFERENCES public_listings(id),
            first_name        VARCHAR(100) NOT NULL,
            last_name         VARCHAR(100) NOT NULL,
            email             VARCHAR(255) NOT NULL,
            phone             VARCHAR(20),
            message           TEXT,
            created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """))

    # ------------------------------------------------------------------ #
    # comparable_sales
    # ------------------------------------------------------------------ #
    op.execute(sa.text("""
        CREATE TABLE comparable_sales (
            id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            make        VARCHAR(100),
            model       VARCHAR(100),
            year        INTEGER,
            hours       INTEGER,
            sale_price  NUMERIC(12,2),
            sale_date   TIMESTAMPTZ,
            source      VARCHAR(100),
            category_id UUID REFERENCES equipment_categories(id),
            created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """))

    # ------------------------------------------------------------------ #
    # webhook_events_seen
    # ------------------------------------------------------------------ #
    op.execute(sa.text("""
        CREATE TABLE webhook_events_seen (
            event_id    VARCHAR(255) PRIMARY KEY,
            received_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            expires_at  TIMESTAMPTZ NOT NULL
        )
    """))
    op.execute(sa.text(
        "CREATE INDEX ix_webhook_events_seen_expires ON webhook_events_seen(expires_at)"
    ))

    # ------------------------------------------------------------------ #
    # Trigger: set_updated_at — fires on UPDATE for tables with updated_at
    # ------------------------------------------------------------------ #
    op.execute(sa.text("""
        CREATE OR REPLACE FUNCTION set_updated_at()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.updated_at = NOW();
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
    """))

    for table in ("users", "customers", "equipment_records", "equipment_categories", "app_config"):
        op.execute(sa.text(f"""
            CREATE TRIGGER trg_set_updated_at_{table}
                BEFORE UPDATE ON {table}
                FOR EACH ROW EXECUTE FUNCTION set_updated_at()
        """))

    # ------------------------------------------------------------------ #
    # Trigger: audit_logs is append-only — block UPDATE and DELETE
    # ------------------------------------------------------------------ #
    op.execute(sa.text("""
        CREATE OR REPLACE FUNCTION prevent_audit_log_modification()
        RETURNS TRIGGER AS $$
        BEGIN
            RAISE EXCEPTION 'audit_logs is append-only; UPDATE and DELETE are not permitted';
        END;
        $$ LANGUAGE plpgsql
    """))
    op.execute(sa.text("""
        CREATE TRIGGER trg_audit_logs_readonly
            BEFORE UPDATE OR DELETE ON audit_logs
            FOR EACH ROW EXECUTE FUNCTION prevent_audit_log_modification()
    """))


def downgrade() -> None:
    # Drop triggers first
    op.execute(sa.text("DROP TRIGGER IF EXISTS trg_audit_logs_readonly ON audit_logs"))
    for table in ("users", "customers", "equipment_records", "equipment_categories", "app_config"):
        op.execute(sa.text(f"DROP TRIGGER IF EXISTS trg_set_updated_at_{table} ON {table}"))
    op.execute(sa.text("DROP FUNCTION IF EXISTS prevent_audit_log_modification"))
    op.execute(sa.text("DROP FUNCTION IF EXISTS set_updated_at"))

    # Drop tables in reverse FK dependency order
    tables = [
        "webhook_events_seen",
        "comparable_sales",
        "inquiries",
        "analytics_events",
        "app_config",
        "record_locks",
        "audit_logs",
        "public_listings",
        "calendar_events",
        "lead_routing_rules",
        "change_requests",
        "consignment_contracts",
        "appraisal_reports",
        "component_scores",
        "appraisal_photos",
        "appraisal_submissions",
        "equipment_records",
        "customers",
        "category_red_flag_rules",
        "category_photo_slots",
        "category_attachments",
        "category_inspection_prompts",
        "category_components",
        "equipment_categories",
        "rate_limit_counters",
        "notification_preferences",
        "known_devices",
        "totp_recovery_codes",
        "user_sessions",
        "users",
        "roles",
    ]
    for table in tables:
        op.execute(sa.text(f"DROP TABLE IF EXISTS {table}"))

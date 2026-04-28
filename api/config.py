# ABOUTME: Application settings loaded from environment variables via pydantic-settings.
# ABOUTME: All secrets come from the environment; no defaults for sensitive values.
from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Resolve .env relative to repo root regardless of invocation directory
_ENV_FILE = Path(__file__).parent.parent / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_ENV_FILE,
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Database
    database_url: str
    # Direct (non-pooler) URL for Alembic migrations — bypasses PgBouncer on Neon.
    # Falls back to database_url when not set (fine for local Docker dev).
    database_direct_url: str = ""
    test_database_url: str = ""

    # JWT
    jwt_secret_key: str
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 7

    # 2FA / TOTP
    # Single-key field (legacy / minimum-viable dev env). Phase 5 Sprint 0
    # added the rotation-friendly `totp_encryption_keys` below; when that
    # field is set it wins, and this single-key field is the fallback so
    # existing dev / test setups keep working without a re-key.
    totp_encryption_key: str
    # Phase 5 Sprint 0 — comma-separated list of Fernet keys for TOTP
    # secret storage. First key is the encrypt-primary; all keys are tried
    # on decrypt via `MultiFernet`. Mirrors the `credentials_encryption_key`
    # pattern from Phase 4 Sprint 7 so both stores rotate the same way.
    # When unset, falls back to `totp_encryption_key` (single-key path).
    totp_encryption_keys: str = ""

    # Phase 4 Sprint 7 — separate Fernet key for the integration credentials
    # vault. Kept distinct from totp_encryption_key so the two key materials
    # can rotate independently. Comma-separated list of keys is supported
    # via MultiFernet — first key is used for new writes, all keys are
    # tried on decrypt (rotation-friendly). Falls back to the TOTP key when
    # unset so dev / test environments don't need two secrets configured.
    credentials_encryption_key: str = ""

    # Email
    sendgrid_api_key: str = ""
    sendgrid_from_email: str = "noreply@saltrun.net"
    sendgrid_from_name: str = "Temple Heavy Equipment"
    # 127.0.0.1 not "localhost" — on macOS the resolver tries IPv6 ::1 first and
    # blocks ~35s before falling back to IPv4 when Mailpit only binds to 0.0.0.0.
    smtp_host: str = "127.0.0.1"
    smtp_port: int = 1025

    # SMS — A2P 10DLC dispatch goes through a Messaging Service SID; the
    # from-number is kept for dev/sandbox testing. If the Messaging Service
    # SID is empty, NotificationService skips SMS and emits sms_skipped_not_configured.
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_from_number: str = ""
    twilio_messaging_service_sid: str = ""

    # Sales ops — fallback recipient for change-request notifications when
    # no rep is assigned yet. Empty string means "drop the notification with
    # a log line" (acceptable for dev / tests).
    sales_ops_email: str = ""

    # Cloudflare R2
    r2_account_id: str = ""
    r2_access_key_id: str = ""
    r2_secret_access_key: str = ""
    r2_bucket_photos: str = "temple-he-photos"
    r2_bucket_reports: str = "temple-he-reports"
    r2_bucket_backups: str = "temple-he-backups"
    r2_public_url: str = ""

    # Observability
    sentry_dsn: str = ""
    # Optional: Sentry CSP report endpoint — appended to CSP header when set
    sentry_csp_report_uri: str = ""
    betterstack_source_token: str = ""
    # Git SHA injected at build time (e.g. FLY_IMAGE_REF or GIT_SHA env var)
    release: str = ""

    # Google OAuth (stub — not active in Phase 1)
    google_client_id: str = ""
    google_client_secret: str = ""
    google_workspace_domain: str = ""

    # Google Maps Platform — Distance Matrix + Geocoding for Phase 3 Sprint 4.
    # Optional; when unset (dev/test/staging without billing), the calendar
    # falls back to AppConfig key `drive_time_fallback_minutes` and metro-area
    # routing rules silently no-op.
    google_maps_api_key: str = ""

    # Phase 5 Sprint 0 — Slack staging-channel guard. When set AND
    # environment != "production", `slack_dispatch_service.send` overrides
    # the saved webhook's channel routing to this channel ID instead. Lets
    # staging exercise real dispatch without paging the production
    # `#alerts` channel by accident. Webhook URL still comes from the
    # credentials vault — only the `channel` field on the payload changes.
    slack_staging_channel_id: str = ""

    # Application
    environment: str = "development"
    cors_origins: str = "http://localhost:5173,http://localhost:3000"

    # Seed
    seed_admin_email: str = ""
    seed_admin_password: str = ""

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def use_smtp_local(self) -> bool:
        return self.environment == "development"


settings = Settings()

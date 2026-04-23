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
    totp_encryption_key: str  # Fernet key for encrypting TOTP secrets at rest

    # Email
    sendgrid_api_key: str = ""
    sendgrid_from_email: str = "noreply@saltrun.net"
    sendgrid_from_name: str = "Temple Heavy Equipment"
    smtp_host: str = "localhost"
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

# ABOUTME: Application settings loaded from environment variables via pydantic-settings.
# ABOUTME: All secrets come from the environment; no defaults for sensitive values.
from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # Database
    database_url: str
    test_database_url: str = ""

    # JWT
    jwt_secret_key: str
    jwt_refresh_secret: str
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 7

    # 2FA / TOTP
    totp_encryption_key: str  # Fernet key for encrypting TOTP secrets at rest

    # Email
    sendgrid_api_key: str = ""
    sendgrid_from_email: str = "noreply@templehe.com"
    sendgrid_from_name: str = "Temple Heavy Equipment"
    smtp_host: str = "localhost"
    smtp_port: int = 1025

    # SMS
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_from_number: str = ""

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
    betterstack_source_token: str = ""

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

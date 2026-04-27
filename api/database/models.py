# ABOUTME: All SQLAlchemy ORM models for the TempleHE platform (30+ tables).
# ABOUTME: UUID primary keys throughout; all timestamps are timezone-aware UTC.
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


# --------------------------------------------------------------------------- #
# Auth & Users
# --------------------------------------------------------------------------- #


class Role(Base):
    __tablename__ = "roles"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    slug: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)

    users: Mapped[list[User]] = relationship("User", back_populates="role")


class UserRole(Base):
    """Phase 4 pre-work — many-to-many between users and roles.

    Phase 1 enforced one role per user via ``users.role_id``. Phase 4
    needs multi-role grants (sales rep who also covers appraiser
    shifts; manager with reporting access). This table is the live
    source of truth for ``require_roles()`` checks; ``users.role_id``
    becomes the user's *primary* role — drives default landing-page
    routing in the SPA + the snapshot in ``audit_logs.actor_role`` —
    and is mirrored into this table by the seeders + admin grant path.
    """

    __tablename__ = "user_roles"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    role_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("roles.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    granted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    )
    granted_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    user: Mapped[User] = relationship("User", back_populates="role_grants", foreign_keys=[user_id])
    role: Mapped[Role] = relationship("Role")


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    # Nullable — Google SSO users have no password
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    last_name: Mapped[str] = mapped_column(String(100), nullable=False)
    role_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("roles.id"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="pending_verification")
    google_id: Mapped[str | None] = mapped_column(String(255), nullable=True, unique=True)
    # Fernet-encrypted TOTP secret
    totp_secret_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    totp_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    profile_photo_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    tos_accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    tos_version: Mapped[str | None] = mapped_column(String(20), nullable=True)
    privacy_accepted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    privacy_version: Mapped[str | None] = mapped_column(String(20), nullable=True)
    deletion_requested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    deletion_grace_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    failed_login_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    )

    # Primary role — drives default landing-page routing + the snapshot
    # in audit_logs.actor_role. Multi-role checks go through ``role_grants``
    # / ``roles`` (the join table). See migration 015 + ADR-019.
    role: Mapped[Role] = relationship("Role", back_populates="users")
    role_grants: Mapped[list[UserRole]] = relationship(
        "UserRole",
        back_populates="user",
        cascade="all, delete-orphan",
        foreign_keys="UserRole.user_id",
    )
    # All roles granted to this user, including the primary. RBAC
    # checks (``require_roles``) read this list. Use
    # ``services.user_roles_service`` to grant/revoke so the audit
    # trail + uniqueness constraints stay enforced in one place.
    roles: Mapped[list[Role]] = relationship(
        "Role",
        secondary="user_roles",
        primaryjoin="User.id == UserRole.user_id",
        secondaryjoin="Role.id == UserRole.role_id",
        viewonly=True,
    )
    sessions: Mapped[list[UserSession]] = relationship(
        "UserSession", back_populates="user", cascade="all, delete-orphan"
    )
    totp_recovery_codes: Mapped[list[TotpRecoveryCode]] = relationship(
        "TotpRecoveryCode", back_populates="user", cascade="all, delete-orphan"
    )
    notification_preference: Mapped[NotificationPreference | None] = relationship(
        "NotificationPreference",
        back_populates="user",
        cascade="all, delete-orphan",
        uselist=False,
    )
    customer_profile: Mapped[Customer | None] = relationship(
        "Customer", back_populates="user", uselist=False
    )
    known_devices: Mapped[list[KnownDevice]] = relationship(
        "KnownDevice", back_populates="user", cascade="all, delete-orphan"
    )
    consent_versions: Mapped[list[UserConsentVersion]] = relationship(
        "UserConsentVersion", back_populates="user", cascade="all, delete-orphan"
    )


class UserConsentVersion(Base):
    """Append-only archive of every ToS/Privacy acceptance event."""

    __tablename__ = "user_consent_versions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    consent_type: Mapped[str] = mapped_column(String(20), nullable=False)
    version: Mapped[str] = mapped_column(String(20), nullable=False)
    accepted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    )
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(512), nullable=True)

    user: Mapped[User] = relationship("User", back_populates="consent_versions")


class UserSession(Base):
    """Opaque refresh tokens stored server-side. Swaps to Redis on GCP migration."""

    __tablename__ = "user_sessions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    # SHA-256 hex of the opaque token; never store the raw token
    token_hash: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(512), nullable=True)

    user: Mapped[User] = relationship("User", back_populates="sessions")


class TotpRecoveryCode(Base):
    """Single-use 2FA recovery codes stored as bcrypt hashes."""

    __tablename__ = "totp_recovery_codes"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    code_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    )

    user: Mapped[User] = relationship("User", back_populates="totp_recovery_codes")


class KnownDevice(Base):
    """Device fingerprints for new-device login notifications."""

    __tablename__ = "known_devices"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    # SHA-256 of (user_agent + IP ASN)
    device_fingerprint: Mapped[str] = mapped_column(String(128), nullable=False)
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    )

    user: Mapped[User] = relationship("User", back_populates="known_devices")

    __table_args__ = (UniqueConstraint("user_id", "device_fingerprint"),)


class NotificationPreference(Base):
    __tablename__ = "notification_preferences"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    channel: Mapped[str] = mapped_column(String(20), nullable=False)  # email | sms | slack
    slack_user_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    phone_number: Mapped[str | None] = mapped_column(String(20), nullable=True)

    user: Mapped[User] = relationship("User", back_populates="notification_preference")

    __table_args__ = (UniqueConstraint("user_id"),)


class DataExportJob(Base):
    """GDPR-lite export request — one per ``POST /me/account/data-export``.

    Processed synchronously in Sprint 4 (service writes the row, runs
    the generator, and updates the same row before returning). The
    shape stays stable so a future async worker can drain ``pending``
    rows without changing the API contract.
    """

    __tablename__ = "data_export_jobs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    storage_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    download_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    url_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    )


class NotificationJob(Base):
    """Durable notification queue. The API enqueues; temple-notifications drains.

    Swaps to Pub/Sub at GCP migration time — the NotificationService interface
    is stable, only the queue backing moves.
    """

    __tablename__ = "notification_jobs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # Callers compute this (typically "{event}:{entity_id}") — UNIQUE on the
    # column ensures a retry submits exactly one row per logical event.
    idempotency_key: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    channel: Mapped[str] = mapped_column(String(20), nullable=False)  # email | sms
    template: Mapped[str] = mapped_column(String(100), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    scheduled_for: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    )
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    )


class RateLimitCounter(Base):
    """Per-key rate limit counters. Swaps to Redis on GCP migration."""

    __tablename__ = "rate_limit_counters"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # e.g. "login:user@example.com" or "login_ip:1.2.3.4"
    key: Mapped[str] = mapped_column(String(255), nullable=False)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    __table_args__ = (UniqueConstraint("key", "window_start"),)


# --------------------------------------------------------------------------- #
# Customers & Equipment
# --------------------------------------------------------------------------- #


class Customer(Base):
    __tablename__ = "customers"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # Phase 4 Sprint 2 (migration 016): user_id is now nullable so admin
    # can create walk-in customers (sales rep met the customer in
    # person; no portal account yet). The DB-level CHECK
    # ck_customers_user_or_invite guarantees at least one of (user_id,
    # invite_email) is set, and a partial unique index on user_id WHERE
    # NOT NULL preserves the one-customer-per-user invariant for
    # registered users.
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    invite_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    business_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    submitter_name: Mapped[str] = mapped_column(String(200), nullable=False)
    title: Mapped[str | None] = mapped_column(String(100), nullable=True)
    address_street: Mapped[str | None] = mapped_column(String(255), nullable=True)
    address_city: Mapped[str | None] = mapped_column(String(100), nullable=True)
    address_state: Mapped[str | None] = mapped_column(String(2), nullable=True)
    address_zip: Mapped[str | None] = mapped_column(String(10), nullable=True)
    business_phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    business_phone_ext: Mapped[str | None] = mapped_column(String(10), nullable=True)
    cell_phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    communication_prefs: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped[User | None] = relationship("User", back_populates="customer_profile")
    equipment_records: Mapped[list[EquipmentRecord]] = relationship(
        "EquipmentRecord", back_populates="customer"
    )


class EquipmentRecord(Base):
    __tablename__ = "equipment_records"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customers.id"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="new_request")
    # Public reference e.g. THE-9ZF3K4XA. Generated at intake time; cheap to
    # quote over phone/email. Never reuse; unique across the platform.
    reference_number: Mapped[str | None] = mapped_column(String(20), nullable=True, unique=True)
    category_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("equipment_categories.id"), nullable=True
    )
    # Customer-reported fields. These are the *initial claims*; the
    # AppraisalSubmission carries the appraiser's verified version.
    customer_make: Mapped[str | None] = mapped_column(String(100), nullable=True)
    customer_model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    customer_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    customer_serial_number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    customer_hours: Mapped[int | None] = mapped_column(Integer, nullable=True)
    customer_running_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    customer_ownership_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    customer_location_text: Mapped[str | None] = mapped_column(String(255), nullable=True)
    customer_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    customer_submitted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    assigned_sales_rep_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    assigned_appraiser_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    customer: Mapped[Customer] = relationship("Customer", back_populates="equipment_records")
    category: Mapped[EquipmentCategory | None] = relationship("EquipmentCategory")
    intake_photos: Mapped[list[CustomerIntakePhoto]] = relationship(
        "CustomerIntakePhoto", back_populates="equipment_record", cascade="all, delete-orphan"
    )
    status_events: Mapped[list[StatusEvent]] = relationship(
        "StatusEvent",
        back_populates="equipment_record",
        cascade="all, delete-orphan",
        order_by="StatusEvent.created_at",
    )
    appraisal_submissions: Mapped[list[AppraisalSubmission]] = relationship(
        "AppraisalSubmission", back_populates="equipment_record"
    )
    appraisal_reports: Mapped[list[AppraisalReport]] = relationship(
        "AppraisalReport", back_populates="equipment_record"
    )
    consignment_contract: Mapped[ConsignmentContract | None] = relationship(
        "ConsignmentContract", back_populates="equipment_record", uselist=False
    )
    change_requests: Mapped[list[ChangeRequest]] = relationship(
        "ChangeRequest", back_populates="equipment_record"
    )
    calendar_events: Mapped[list[CalendarEvent]] = relationship(
        "CalendarEvent", back_populates="equipment_record"
    )
    public_listing: Mapped[PublicListing | None] = relationship(
        "PublicListing", back_populates="equipment_record", uselist=False
    )


class CustomerIntakePhoto(Base):
    """R2 storage metadata for photos a customer uploaded with their intake.

    The actual blob lives in Cloudflare R2 under ``storage_key``. Sprint 3
    adds the signed-URL upload + finalize flow and a scan_status scaffold
    (pending/clean/infected/failed); real ClamAV wiring is deferred.
    """

    __tablename__ = "customer_intake_photos"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    equipment_record_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("equipment_records.id", ondelete="CASCADE"),
        nullable=False,
    )
    storage_key: Mapped[str] = mapped_column(String(255), nullable=False)
    caption: Mapped[str | None] = mapped_column(Text, nullable=True)
    display_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    )
    # pending | clean | infected | failed — scaffold this sprint; ClamAV deferred.
    scan_status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    content_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)

    equipment_record: Mapped[EquipmentRecord] = relationship(
        "EquipmentRecord", back_populates="intake_photos"
    )


class StatusEvent(Base):
    """Append-only timeline of equipment_records.status transitions.

    Drives the customer-facing status timeline on /me/equipment/{id}.
    Blocked from UPDATE at the DB layer; cascades away when the parent
    record is deleted.
    """

    __tablename__ = "status_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    equipment_record_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("equipment_records.id", ondelete="CASCADE"),
        nullable=False,
    )
    from_status: Mapped[str | None] = mapped_column(String(40), nullable=True)
    to_status: Mapped[str] = mapped_column(String(40), nullable=False)
    changed_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    )

    equipment_record: Mapped[EquipmentRecord] = relationship(
        "EquipmentRecord", back_populates="status_events"
    )


# --------------------------------------------------------------------------- #
# Equipment Categories (Dynamic)
# --------------------------------------------------------------------------- #


class EquipmentCategory(Base):
    __tablename__ = "equipment_categories"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    display_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    components: Mapped[list[CategoryComponent]] = relationship(
        "CategoryComponent", back_populates="category"
    )
    inspection_prompts: Mapped[list[CategoryInspectionPrompt]] = relationship(
        "CategoryInspectionPrompt", back_populates="category"
    )
    attachments: Mapped[list[CategoryAttachment]] = relationship(
        "CategoryAttachment", back_populates="category"
    )
    photo_slots: Mapped[list[CategoryPhotoSlot]] = relationship(
        "CategoryPhotoSlot", back_populates="category"
    )
    red_flag_rules: Mapped[list[CategoryRedFlagRule]] = relationship(
        "CategoryRedFlagRule", back_populates="category"
    )


class CategoryComponent(Base):
    __tablename__ = "category_components"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    category_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("equipment_categories.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    weight_pct: Mapped[Decimal] = mapped_column(Numeric(6, 4), nullable=False)
    display_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    category: Mapped[EquipmentCategory] = relationship(
        "EquipmentCategory", back_populates="components"
    )
    scores: Mapped[list[ComponentScore]] = relationship(
        "ComponentScore", back_populates="component"
    )


class CategoryInspectionPrompt(Base):
    __tablename__ = "category_inspection_prompts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    category_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("equipment_categories.id"), nullable=False
    )
    label: Mapped[str] = mapped_column(String(255), nullable=False)
    # yes_no_na | text | scale_1_5
    response_type: Mapped[str] = mapped_column(String(20), nullable=False)
    required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    display_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Phase 4 pre-work versioning. Edits insert a new row + set
    # ``replaced_at`` on the old one so historical appraisals stay
    # anchored to the prompt definition they were authored against.
    # ``replaced_at IS NULL`` = current version. See migration 014.
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    replaced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    category: Mapped[EquipmentCategory] = relationship(
        "EquipmentCategory", back_populates="inspection_prompts"
    )


class CategoryAttachment(Base):
    __tablename__ = "category_attachments"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    category_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("equipment_categories.id"), nullable=False
    )
    label: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    display_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    category: Mapped[EquipmentCategory] = relationship(
        "EquipmentCategory", back_populates="attachments"
    )


class CategoryPhotoSlot(Base):
    __tablename__ = "category_photo_slots"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    category_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("equipment_categories.id"), nullable=False
    )
    label: Mapped[str] = mapped_column(String(255), nullable=False)
    helper_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    display_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    category: Mapped[EquipmentCategory] = relationship(
        "EquipmentCategory", back_populates="photo_slots"
    )


class CategoryRedFlagRule(Base):
    __tablename__ = "category_red_flag_rules"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    category_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("equipment_categories.id"), nullable=False
    )
    condition_field: Mapped[str] = mapped_column(String(100), nullable=False)
    # equals | is_true | is_false
    condition_operator: Mapped[str] = mapped_column(String(20), nullable=False)
    condition_value: Mapped[str | None] = mapped_column(String(255), nullable=True)
    actions: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    label: Mapped[str] = mapped_column(String(255), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Phase 4 pre-work versioning — see CategoryInspectionPrompt for
    # the same shape + rationale.
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    replaced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    category: Mapped[EquipmentCategory] = relationship(
        "EquipmentCategory", back_populates="red_flag_rules"
    )


# --------------------------------------------------------------------------- #
# Appraisal
# --------------------------------------------------------------------------- #


class AppraisalSubmission(Base):
    __tablename__ = "appraisal_submissions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    equipment_record_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("equipment_records.id"), nullable=False
    )
    category_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("equipment_categories.id"), nullable=True
    )
    make: Mapped[str | None] = mapped_column(String(100), nullable=True)
    model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    hours_condition: Mapped[str | None] = mapped_column(String(50), nullable=True)
    running_status: Mapped[str | None] = mapped_column(String(50), nullable=True)
    serial_number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    title_status: Mapped[str | None] = mapped_column(String(50), nullable=True)
    overall_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    score_band: Mapped[str | None] = mapped_column(String(20), nullable=True)
    management_review_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    hold_for_title_review: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    marketability_rating: Mapped[str | None] = mapped_column(String(20), nullable=True)
    approved_purchase_offer: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    suggested_consignment_price: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 2), nullable=True
    )
    # Triggered red flags. Phase 5 iOS writers MUST embed the rule
    # version that fired so historical reports stay correct after Phase 4
    # admin edits the rule. Shape (versioned, post-migration 014):
    #     [{"rule_id": "<uuid>", "rule_version": 1, "triggered_at": "<iso>"}]
    red_flags: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    comparable_sales_data: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    # All inspection prompt responses. Phase 5 iOS writers MUST embed
    # the prompt version that was answered so historical reports survive
    # Phase 4 admin edits to the prompt set. Shape (versioned, post-
    # migration 014):
    #     [{"prompt_id": "<uuid>", "prompt_version": 1, "value": <typed>}]
    # Keyed-by-prompt-ID dict shape from the original Phase 1 schema is
    # accepted as legacy on read (no rows in production); writers should
    # use the new shape exclusively.
    field_values: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    equipment_record: Mapped[EquipmentRecord] = relationship(
        "EquipmentRecord", back_populates="appraisal_submissions"
    )
    photos: Mapped[list[AppraisalPhoto]] = relationship(
        "AppraisalPhoto", back_populates="submission"
    )
    component_scores: Mapped[list[ComponentScore]] = relationship(
        "ComponentScore", back_populates="submission"
    )
    report: Mapped[AppraisalReport | None] = relationship(
        "AppraisalReport", back_populates="submission", uselist=False
    )


class AppraisalPhoto(Base):
    __tablename__ = "appraisal_photos"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    appraisal_submission_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("appraisal_submissions.id"), nullable=False
    )
    slot_label: Mapped[str] = mapped_column(String(255), nullable=False)
    gcs_path: Mapped[str] = mapped_column(String(512), nullable=False)
    capture_timestamp: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    gps_latitude: Mapped[Decimal | None] = mapped_column(Numeric(10, 7), nullable=True)
    gps_longitude: Mapped[Decimal | None] = mapped_column(Numeric(10, 7), nullable=True)
    gps_missing: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    gps_out_of_range: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    file_size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)

    submission: Mapped[AppraisalSubmission] = relationship(
        "AppraisalSubmission", back_populates="photos"
    )


class ComponentScore(Base):
    __tablename__ = "component_scores"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    appraisal_submission_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("appraisal_submissions.id"), nullable=False
    )
    category_component_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("category_components.id"), nullable=False
    )
    raw_score: Mapped[Decimal] = mapped_column(Numeric(3, 2), nullable=False)
    weight_at_time_of_scoring: Mapped[Decimal] = mapped_column(Numeric(6, 4), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    submission: Mapped[AppraisalSubmission] = relationship(
        "AppraisalSubmission", back_populates="component_scores"
    )
    component: Mapped[CategoryComponent] = relationship(
        "CategoryComponent", back_populates="scores"
    )


# --------------------------------------------------------------------------- #
# Workflow & Scheduling
# --------------------------------------------------------------------------- #


class AppraisalReport(Base):
    __tablename__ = "appraisal_reports"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    equipment_record_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("equipment_records.id"), nullable=False
    )
    appraisal_submission_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("appraisal_submissions.id"), nullable=True
    )
    gcs_path: Mapped[str] = mapped_column(String(512), nullable=False)
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    )

    equipment_record: Mapped[EquipmentRecord] = relationship(
        "EquipmentRecord", back_populates="appraisal_reports"
    )
    submission: Mapped[AppraisalSubmission | None] = relationship(
        "AppraisalSubmission", back_populates="report"
    )


class ConsignmentContract(Base):
    __tablename__ = "consignment_contracts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    equipment_record_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("equipment_records.id"), nullable=False, unique=True
    )
    envelope_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="sent")
    signed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    equipment_record: Mapped[EquipmentRecord] = relationship(
        "EquipmentRecord", back_populates="consignment_contract"
    )


class ChangeRequest(Base):
    __tablename__ = "change_requests"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    equipment_record_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("equipment_records.id"), nullable=False
    )
    request_type: Mapped[str] = mapped_column(String(30), nullable=False)
    customer_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    resolution_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    requires_manager_reapproval: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )

    equipment_record: Mapped[EquipmentRecord] = relationship(
        "EquipmentRecord", back_populates="change_requests"
    )


class LeadRoutingRule(Base):
    __tablename__ = "lead_routing_rules"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # ad_hoc | geographic | round_robin
    rule_type: Mapped[str] = mapped_column(String(20), nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    conditions: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    assigned_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    round_robin_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CalendarEvent(Base):
    __tablename__ = "calendar_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    equipment_record_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("equipment_records.id"), nullable=False
    )
    appraiser_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    site_address: Mapped[str | None] = mapped_column(Text, nullable=True)
    drive_time_buffer_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    equipment_record: Mapped[EquipmentRecord] = relationship(
        "EquipmentRecord", back_populates="calendar_events"
    )


class PublicListing(Base):
    __tablename__ = "public_listings"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    equipment_record_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("equipment_records.id"), nullable=False, unique=True
    )
    listing_title: Mapped[str] = mapped_column(String(255), nullable=False)
    asking_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    primary_photo_gcs_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sold_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    equipment_record: Mapped[EquipmentRecord] = relationship(
        "EquipmentRecord", back_populates="public_listing"
    )
    inquiries: Mapped[list[Inquiry]] = relationship("Inquiry", back_populates="listing")


# --------------------------------------------------------------------------- #
# Platform
# --------------------------------------------------------------------------- #


class AuditLog(Base):
    """Append-only audit trail. DB-level trigger blocks UPDATE/DELETE."""

    __tablename__ = "audit_logs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    actor_role: Mapped[str | None] = mapped_column(String(50), nullable=True)
    target_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    target_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    before_state: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    after_state: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    )


class RecordLock(Base):
    __tablename__ = "record_locks"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    record_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    record_type: Mapped[str] = mapped_column(String(50), nullable=False)
    locked_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    locked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    overridden_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    overridden_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (UniqueConstraint("record_id", "record_type"),)


class DriveTimeCache(Base):
    """6h-TTL cache for Google Distance Matrix calls — Phase 3 Sprint 4.

    Composite-key stand-in for ``SETEX`` in the GCP migration.
    """

    __tablename__ = "drive_time_cache"

    origin_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    dest_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    duration_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class GeocodeCache(Base):
    """30d-TTL cache for Google Geocoding calls — Phase 3 Sprint 4.

    Used by metro-area routing rules and (eventually) by the calendar UI's
    address autocomplete. Addresses move rarely; the longer TTL keeps API
    spend low without sacrificing correctness.
    """

    __tablename__ = "geocode_cache"

    address_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    lat: Mapped[float] = mapped_column(Float, nullable=False)
    lon: Mapped[float] = mapped_column(Float, nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AppConfig(Base):
    __tablename__ = "app_config"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    key: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    value: Mapped[dict] = mapped_column(JSONB, nullable=False)
    category: Mapped[str | None] = mapped_column(String(100), nullable=True)
    field_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    )


class AnalyticsEvent(Base):
    __tablename__ = "analytics_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    page: Mapped[str | None] = mapped_column(String(255), nullable=True)
    event_metadata: Mapped[dict | None] = mapped_column("metadata", JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    )


class Inquiry(Base):
    __tablename__ = "inquiries"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    public_listing_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("public_listings.id"), nullable=False
    )
    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    last_name: Mapped[str] = mapped_column(String(100), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    )

    listing: Mapped[PublicListing] = relationship("PublicListing", back_populates="inquiries")


class ComparableSale(Base):
    __tablename__ = "comparable_sales"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    make: Mapped[str | None] = mapped_column(String(100), nullable=True)
    model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    hours: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sale_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    sale_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    source: Mapped[str | None] = mapped_column(String(100), nullable=True)
    category_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("equipment_categories.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    )


class WebhookEventSeen(Base):
    """De-duplication log for incoming webhooks. Rows expire after 24 hours."""

    __tablename__ = "webhook_events_seen"

    event_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


# ---------------------------------------------------------------------------
# Mirror invariant: users.role_id changes always write a user_roles row.
#
# Phase 4 pre-work split RBAC (now via the join table) from "primary role"
# (still on users.role_id, used for default landing-page routing). This
# event listener catches every assignment to ``User.role_id`` — whether
# from a router, a test fixture, or an admin path — and inserts the
# matching join row in the same flush. Without it, an INSERT or UPDATE
# of users.role_id silently bypasses the join table and require_roles()
# starts denying perfectly-valid users.
# ---------------------------------------------------------------------------


@sa.event.listens_for(sa.orm.Session, "before_flush")
def _mirror_user_role_id_changes(session, flush_context, instances) -> None:
    pending: list[tuple[uuid.UUID, uuid.UUID]] = []
    for obj in session.new | session.dirty:
        if not isinstance(obj, User):
            continue
        history = sa.inspect(obj).attrs.role_id.history
        if not history.has_changes():
            continue
        new_role_id = history.added[0] if history.added else obj.role_id
        if new_role_id is None or obj.id is None:
            # New User without an autogenerated id yet — registration
            # callers issue an explicit grant after the first flush.
            continue
        pending.append((obj.id, new_role_id))

    for user_id, role_id in pending:
        # Idempotent insert — the join table's primary key is (user_id,
        # role_id) so this no-ops if the row already exists.
        session.execute(
            sa.dialects.postgresql.insert(UserRole.__table__)
            .values(user_id=user_id, role_id=role_id)
            .on_conflict_do_nothing(index_elements=["user_id", "role_id"])
        )


# --------------------------------------------------------------------------- #
# Phase 4 Sprint 5 — equipment record watchers + calendar multi-attendee +
# notification template overrides.
# --------------------------------------------------------------------------- #


class EquipmentRecordWatcher(Base):
    """Architectural Debt #9 — secondary followers for an equipment
    record. Notification dispatch widens to include watchers; the
    primary owner stays in ``equipment_records.assigned_sales_rep_id``
    (drives landing-page logic). Watchers are a "fan-out" set, not an
    ownership change."""

    __tablename__ = "equipment_record_watchers"

    record_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("equipment_records.id", ondelete="CASCADE"),
        primary_key=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    added_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    added_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    )

    user: Mapped[User] = relationship("User", foreign_keys=[user_id])


class CalendarEventAttendee(Base):
    """Architectural Debt #11 — multi-attendee calendar events. The
    ``role`` slot marks "primary" (mirrors ``calendar_events.appraiser_id``
    via the before_flush listener below) vs "attendee" (added later via
    the multi-attendee admin UI). The ``calendar_events.appraiser_id``
    column stays as the primary attendee for back-compat; this join
    table is the live source for "who's coming"."""

    __tablename__ = "calendar_event_attendees"

    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("calendar_events.id", ondelete="CASCADE"),
        primary_key=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="attendee")
    added_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    )

    user: Mapped[User] = relationship("User", foreign_keys=[user_id])


class NotificationTemplateOverride(Base):
    """Architectural Debt #1 — admin "edit email copy" stores its
    overrides here. One row per template name; missing row → render
    falls back to the code default in
    ``services.notification_templates``. Subject is None for SMS
    templates; body_md is the source the Jinja renderer compiles."""

    __tablename__ = "notification_template_overrides"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    subject_md: Mapped[str | None] = mapped_column(Text, nullable=True)
    body_md: Mapped[str] = mapped_column(Text, nullable=False)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    )


# --- Multi-attendee mirror invariant ---------------------------------------- #
# When a CalendarEvent is created or its appraiser_id changes, mirror that
# user into calendar_event_attendees with role='primary'. Mirrors the
# Phase 4 pre-work multi-role pattern from PR #33: keeps the join table
# in sync with the primary column without forcing every test to
# explicitly add the row.


@sa.event.listens_for(sa.orm.Session, "before_flush")
def _mirror_calendar_event_appraiser(session, _flush_context, _instances) -> None:
    """Mirror ``CalendarEvent.appraiser_id`` into the join table on
    create and on appraiser change. Adds via the ORM (not raw INSERT)
    so SQLAlchemy honors FK ordering — the join row's INSERT runs
    after the parent's, which is required for new CalendarEvents that
    don't yet exist in the DB."""
    new_pending: list[tuple[CalendarEvent, uuid.UUID]] = []
    for obj in session.new:
        if isinstance(obj, CalendarEvent) and obj.appraiser_id is not None:
            new_pending.append((obj, obj.appraiser_id))

    dirty_pending: list[tuple[uuid.UUID, uuid.UUID]] = []
    for obj in session.dirty:
        if not isinstance(obj, CalendarEvent):
            continue
        attrs = sa.inspect(obj).attrs
        if not attrs.appraiser_id.history.has_changes():
            continue
        if obj.appraiser_id is None:
            continue
        dirty_pending.append((obj.id, obj.appraiser_id))

    # New events: ORM-add the attendee, let SQLAlchemy figure out the
    # FK dependency ordering. Pre-populate id so the relationship can
    # bind without a flush round-trip.
    for event, user_id in new_pending:
        if event.id is None:
            event.id = uuid.uuid4()
        session.add(CalendarEventAttendee(event_id=event.id, user_id=user_id, role="primary"))

    # Dirty events: parent already exists in DB, so a raw INSERT with
    # ON CONFLICT is safe + cheap (no SELECT round-trip).
    for event_id, user_id in dirty_pending:
        session.execute(
            sa.dialects.postgresql.insert(CalendarEventAttendee.__table__)
            .values(event_id=event_id, user_id=user_id, role="primary")
            .on_conflict_do_nothing(index_elements=["event_id", "user_id"])
        )

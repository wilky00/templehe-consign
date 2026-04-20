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
    tos_accepted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    tos_version: Mapped[str | None] = mapped_column(String(20), nullable=True)
    privacy_accepted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    privacy_version: Mapped[str | None] = mapped_column(String(20), nullable=True)
    deletion_requested_at: Mapped[datetime | None] = mapped_column(
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

    role: Mapped[Role] = relationship("Role", back_populates="users")
    sessions: Mapped[list[UserSession]] = relationship(
        "UserSession", back_populates="user", cascade="all, delete-orphan"
    )
    totp_recovery_codes: Mapped[list[TotpRecoveryCode]] = relationship(
        "TotpRecoveryCode", back_populates="user", cascade="all, delete-orphan"
    )
    notification_preferences: Mapped[list[NotificationPreference]] = relationship(
        "NotificationPreference", back_populates="user", cascade="all, delete-orphan"
    )
    customer_profile: Mapped[Customer | None] = relationship(
        "Customer", back_populates="user", uselist=False
    )
    known_devices: Mapped[list[KnownDevice]] = relationship(
        "KnownDevice", back_populates="user", cascade="all, delete-orphan"
    )


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

    user: Mapped[User] = relationship("User", back_populates="notification_preferences")


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
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, unique=True
    )
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

    user: Mapped[User] = relationship("User", back_populates="customer_profile")
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
    approved_purchase_offer: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 2), nullable=True
    )
    suggested_consignment_price: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 2), nullable=True
    )
    red_flags: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    comparable_sales_data: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    # JSONB blob storing all inspection prompt responses keyed by prompt ID
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
    overridden_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (UniqueConstraint("record_id", "record_type"),)


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

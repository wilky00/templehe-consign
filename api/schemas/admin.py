# ABOUTME: Admin panel request/response shapes — operations dashboard + manual transitions.
# ABOUTME: Dedicated to /admin/* endpoints; keeps Phase 4 surface separate from sales schemas.
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class AdminOperationsRow(BaseModel):
    id: uuid.UUID
    reference_number: str | None
    status: str
    status_display: str
    days_in_status: int
    customer_id: uuid.UUID
    customer_name: str
    business_name: str | None
    state: str | None
    make: str | None
    model: str | None
    year: int | None
    assigned_sales_rep_id: uuid.UUID | None
    assigned_sales_rep_name: str | None
    assigned_appraiser_id: uuid.UUID | None
    assigned_appraiser_name: str | None
    is_overdue: bool
    submitted_at: datetime | None
    updated_at: datetime


class AdminOperationsResponse(BaseModel):
    rows: list[AdminOperationsRow]
    total: int
    page: int
    per_page: int


class ManualTransitionRequest(BaseModel):
    to_status: str = Field(min_length=1, max_length=40)
    reason: str = Field(min_length=1, max_length=2000)
    send_notifications: bool | None = Field(
        default=None,
        description=(
            "When None, dispatch follows the registry defaults for the "
            "destination status. When True/False, both customer + sales-rep "
            "notifications are forced on/off for this transition."
        ),
    )


class ManualTransitionResponse(BaseModel):
    record_id: uuid.UUID
    from_status: str
    to_status: str
    notifications_dispatched: bool
    audit_log_id: uuid.UUID


SortField = Literal[
    "updated_at",
    "submitted_at",
    "days_in_status",
    "customer_name",
    "status",
]
SortDirection = Literal["asc", "desc"]


# --- Customer admin (Sprint 2) --------------------------------------------- #


class AdminCustomerEquipmentSummary(BaseModel):
    id: uuid.UUID
    reference_number: str | None
    status: str
    make: str | None
    model: str | None
    year: int | None
    deleted_at: datetime | None


class AdminCustomerOut(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID | None
    user_email: str | None
    invite_email: str | None
    business_name: str | None
    submitter_name: str
    title: str | None
    address_street: str | None
    address_city: str | None
    address_state: str | None
    address_zip: str | None
    business_phone: str | None
    business_phone_ext: str | None
    cell_phone: str | None
    is_walkin: bool
    is_deleted: bool
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None
    equipment_records: list[AdminCustomerEquipmentSummary] = Field(default_factory=list)


class AdminCustomerListResponse(BaseModel):
    customers: list[AdminCustomerOut]
    total: int
    page: int
    per_page: int


class AdminCustomerCreate(BaseModel):
    """Walk-in customer creation — admin types details for someone who
    hasn't registered. ``invite_email`` is required; the admin can later
    click "Send Portal Invite" to email a registration link."""

    submitter_name: str = Field(min_length=1, max_length=200)
    invite_email: str = Field(min_length=3, max_length=255)
    business_name: str | None = Field(default=None, max_length=200)
    title: str | None = Field(default=None, max_length=100)
    address_street: str | None = Field(default=None, max_length=255)
    address_city: str | None = Field(default=None, max_length=100)
    address_state: str | None = Field(default=None, max_length=2)
    address_zip: str | None = Field(default=None, max_length=10)
    business_phone: str | None = Field(default=None, max_length=20)
    business_phone_ext: str | None = Field(default=None, max_length=10)
    cell_phone: str | None = Field(default=None, max_length=20)


class AdminCustomerPatch(BaseModel):
    submitter_name: str | None = Field(default=None, max_length=200)
    business_name: str | None = Field(default=None, max_length=200)
    title: str | None = Field(default=None, max_length=100)
    address_street: str | None = Field(default=None, max_length=255)
    address_city: str | None = Field(default=None, max_length=100)
    address_state: str | None = Field(default=None, max_length=2)
    address_zip: str | None = Field(default=None, max_length=10)
    business_phone: str | None = Field(default=None, max_length=20)
    business_phone_ext: str | None = Field(default=None, max_length=10)
    cell_phone: str | None = Field(default=None, max_length=20)
    invite_email: str | None = Field(default=None, max_length=255)


class SendInviteResponse(BaseModel):
    customer_id: uuid.UUID
    invite_email: str
    sent_at: datetime


# --- User deactivation (Sprint 2) ------------------------------------------ #


class DeactivateUserRequest(BaseModel):
    reassign_to_id: uuid.UUID | None = Field(
        default=None,
        description=(
            "Required when the user has open equipment records or future "
            "calendar events. Must be an active user with an overlapping "
            "role (sales rep replacement → another sales rep; appraiser → "
            "another appraiser)."
        ),
    )


class DeactivateUserOpenWork(BaseModel):
    """409 payload when admin tries to deactivate a user with open
    work but didn't pick a reassignment target. Lists the impacted
    counts so the SPA modal can show "this user has N records assigned"
    before asking for the new assignee."""

    detail: str
    open_record_count: int
    future_event_count: int


class DeactivateUserResponse(BaseModel):
    user_id: uuid.UUID
    reassigned_records: list[uuid.UUID] = Field(default_factory=list)
    reassigned_events: list[uuid.UUID] = Field(default_factory=list)
    new_status: str


# --- AppConfig admin (Sprint 3) -------------------------------------------- #


class AppConfigItem(BaseModel):
    """One AppConfig key as the admin form sees it: schema metadata
    (name, category, type, description, default) + the live value.
    Frontend renders the right input widget per ``field_type``."""

    name: str
    category: str
    field_type: str
    description: str
    default: object | None = None
    value: object | None = None


class AppConfigListResponse(BaseModel):
    items: list[AppConfigItem]


class AppConfigUpdateRequest(BaseModel):
    """PATCH body for /admin/config/{key}. ``value`` is the typed value
    the admin chose; the registry's per-key serializer wraps it into the
    JSONB shape the consumer expects."""

    value: object | None = None


# --- Watchers + unified prefs + template overrides (Sprint 5) -------------- #


class WatcherOut(BaseModel):
    user_id: uuid.UUID
    email: str
    first_name: str
    last_name: str
    added_by: uuid.UUID | None
    added_at: datetime


class WatcherListResponse(BaseModel):
    watchers: list[WatcherOut]


class AddWatcherRequest(BaseModel):
    user_id: uuid.UUID


class UnifiedNotificationPrefsOut(BaseModel):
    user_id: uuid.UUID
    email: str
    role_slug: str | None
    channel: str
    phone_number: str | None
    slack_user_id: str | None
    intake_confirmations: bool | None
    status_updates: bool | None
    marketing: bool | None
    sms_opt_in: bool | None


class NotificationTemplateOut(BaseModel):
    name: str
    channel: str
    category: str
    description: str
    variables: list[str]
    subject_template: str | None
    body_template: str
    has_override: bool
    override_subject: str | None = None
    override_body: str | None = None


class NotificationTemplateListResponse(BaseModel):
    templates: list[NotificationTemplateOut]


class NotificationTemplateOverrideRequest(BaseModel):
    """PATCH body. Pass null subject_md / body_md to delete the
    override and revert to the code default."""

    subject_md: str | None = Field(default=None)
    body_md: str | None = Field(default=None)
    delete: bool = Field(
        default=False,
        description="When true, drop any existing override and revert to the code default.",
    )


# --- Equipment categories admin (Sprint 6) -------------------------------- #


class CategoryComponentOut(BaseModel):
    id: uuid.UUID
    name: str
    weight_pct: float
    display_order: int
    active: bool


class CategoryInspectionPromptOut(BaseModel):
    id: uuid.UUID
    label: str
    response_type: str
    required: bool
    display_order: int
    active: bool
    version: int


class CategoryAttachmentOut(BaseModel):
    id: uuid.UUID
    label: str
    description: str | None
    display_order: int
    active: bool


class CategoryPhotoSlotOut(BaseModel):
    id: uuid.UUID
    label: str
    helper_text: str | None
    required: bool
    display_order: int
    active: bool


class CategoryRedFlagRuleOut(BaseModel):
    id: uuid.UUID
    label: str
    condition_field: str
    condition_operator: str
    condition_value: str | None
    actions: dict
    active: bool
    version: int


class CategoryOut(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    status: str
    display_order: int
    version: int
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None
    replaced_at: datetime | None


class CategoryDetail(CategoryOut):
    """Full category bundle for the admin edit page. ``weight_warning``
    surfaces the 'components don't sum to 100%' banner without forcing
    the admin to do mental math; the scorer normalizes at runtime."""

    components: list[CategoryComponentOut] = Field(default_factory=list)
    inspection_prompts: list[CategoryInspectionPromptOut] = Field(default_factory=list)
    attachments: list[CategoryAttachmentOut] = Field(default_factory=list)
    photo_slots: list[CategoryPhotoSlotOut] = Field(default_factory=list)
    red_flag_rules: list[CategoryRedFlagRuleOut] = Field(default_factory=list)
    weight_total: float = 0.0
    weight_warning: bool = False


class CategoryListResponse(BaseModel):
    categories: list[CategoryOut]


class CategoryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    slug: str = Field(min_length=1, max_length=100, pattern=r"^[a-z0-9][a-z0-9_-]*$")
    display_order: int = Field(default=0, ge=0)


class CategoryPatch(BaseModel):
    """Identity-affecting edits (name, slug, status) supersede the row;
    pure ``display_order`` tweaks also route through supersede so the
    audit trail stays consistent."""

    name: str | None = Field(default=None, max_length=100)
    slug: str | None = Field(default=None, max_length=100, pattern=r"^[a-z0-9][a-z0-9_-]*$")
    display_order: int | None = Field(default=None, ge=0)
    status: str | None = Field(default=None, pattern=r"^(active|inactive)$")


class ComponentCreate(BaseModel):
    # weight_pct is NUMERIC(6, 4) — max storable value is 99.9999.
    # Components share weight across siblings; "100% in one component"
    # is degenerate (no scoring) and intentionally rejected.
    name: str = Field(min_length=1, max_length=100)
    weight_pct: float = Field(ge=0, lt=100)
    display_order: int = Field(default=0, ge=0)


class ComponentPatch(BaseModel):
    name: str | None = Field(default=None, max_length=100)
    weight_pct: float | None = Field(default=None, ge=0, lt=100)
    display_order: int | None = Field(default=None, ge=0)
    active: bool | None = None


class InspectionPromptCreate(BaseModel):
    label: str = Field(min_length=1, max_length=255)
    response_type: Literal["yes_no_na", "text", "scale_1_5"]
    required: bool = True
    display_order: int = Field(default=0, ge=0)


class InspectionPromptPatch(BaseModel):
    label: str | None = Field(default=None, max_length=255)
    response_type: Literal["yes_no_na", "text", "scale_1_5"] | None = None
    required: bool | None = None
    display_order: int | None = Field(default=None, ge=0)
    active: bool | None = None


class AttachmentCreate(BaseModel):
    label: str = Field(min_length=1, max_length=255)
    description: str | None = None
    display_order: int = Field(default=0, ge=0)


class AttachmentPatch(BaseModel):
    label: str | None = Field(default=None, max_length=255)
    description: str | None = None
    display_order: int | None = Field(default=None, ge=0)
    active: bool | None = None


class PhotoSlotCreate(BaseModel):
    label: str = Field(min_length=1, max_length=255)
    helper_text: str | None = None
    required: bool = True
    display_order: int = Field(default=0, ge=0)


class PhotoSlotPatch(BaseModel):
    label: str | None = Field(default=None, max_length=255)
    helper_text: str | None = None
    required: bool | None = None
    display_order: int | None = Field(default=None, ge=0)
    active: bool | None = None


class RedFlagRuleCreate(BaseModel):
    label: str = Field(min_length=1, max_length=255)
    condition_field: str = Field(min_length=1, max_length=100)
    condition_operator: Literal["equals", "is_true", "is_false"]
    condition_value: str | None = Field(default=None, max_length=255)
    actions: dict = Field(default_factory=dict)


class RedFlagRulePatch(BaseModel):
    label: str | None = Field(default=None, max_length=255)
    condition_field: str | None = Field(default=None, max_length=100)
    condition_operator: Literal["equals", "is_true", "is_false"] | None = None
    condition_value: str | None = Field(default=None, max_length=255)
    actions: dict | None = None
    active: bool | None = None


class CategoryExportPayload(BaseModel):
    """Serialization of a category at a point in time. Re-importing the
    same payload (matched on slug) supersedes prompts + rules whose body
    changed and creates new ones for additions; it never duplicates an
    existing item with the same identity. ``version`` + ``replaced_at``
    are emitted so the file documents history but they're advisory on
    re-import — the importer doesn't trust client timestamps."""

    name: str
    slug: str
    status: str
    display_order: int
    version: int
    replaced_at: datetime | None = None
    components: list[dict] = Field(default_factory=list)
    inspection_prompts: list[dict] = Field(default_factory=list)
    attachments: list[dict] = Field(default_factory=list)
    photo_slots: list[dict] = Field(default_factory=list)
    red_flag_rules: list[dict] = Field(default_factory=list)


class CategoryImportResult(BaseModel):
    category_id: uuid.UUID
    created: bool
    superseded_prompt_ids: list[uuid.UUID] = Field(default_factory=list)
    superseded_rule_ids: list[uuid.UUID] = Field(default_factory=list)
    added_component_ids: list[uuid.UUID] = Field(default_factory=list)
    added_prompt_ids: list[uuid.UUID] = Field(default_factory=list)
    added_attachment_ids: list[uuid.UUID] = Field(default_factory=list)
    added_photo_slot_ids: list[uuid.UUID] = Field(default_factory=list)
    added_rule_ids: list[uuid.UUID] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# Sprint 7 — Integration credentials + health
# --------------------------------------------------------------------------- #


class IntegrationOut(BaseModel):
    """Metadata-only view of an integration. Plaintext is never serialized;
    reveal goes through the dedicated step-up endpoint."""

    name: str
    is_set: bool
    set_by: uuid.UUID | None = None
    set_at: datetime | None = None
    last_tested_at: datetime | None = None
    last_test_status: Literal["success", "failure", "stubbed"] | None = None
    last_test_detail: str | None = None
    last_test_latency_ms: int | None = None


class IntegrationListResponse(BaseModel):
    integrations: list[IntegrationOut]


class IntegrationStoreRequest(BaseModel):
    """``plaintext`` is the credential value. For multi-field integrations
    (Twilio) it's a JSON-serialized blob; the per-tester knows how to
    parse it."""

    plaintext: str = Field(min_length=1)


class IntegrationRevealRequest(BaseModel):
    password: str = Field(min_length=1)
    totp_code: str = Field(min_length=4, max_length=10)


class IntegrationRevealResponse(BaseModel):
    name: str
    plaintext: str
    revealed_at: datetime


class IntegrationTestRequest(BaseModel):
    """Per-integration extra arguments. Twilio accepts ``to_number`` for an
    SMS dispatch; SendGrid accepts ``to_email`` for a real send. Empty
    extras run the cred-validation-only path."""

    extra_args: dict | None = None


class IntegrationTestResponse(BaseModel):
    name: str
    success: bool
    status: Literal["success", "failure", "stubbed"]
    detail: str
    latency_ms: int


class HealthStateRow(BaseModel):
    service_name: str
    status: Literal["green", "yellow", "red", "unknown", "stubbed"]
    last_checked_at: datetime | None = None
    last_alerted_at: datetime | None = None
    error_detail: dict | None = None
    latency_ms: int | None = None


class HealthSnapshotResponse(BaseModel):
    services: list[HealthStateRow]
    snapshot_at: datetime

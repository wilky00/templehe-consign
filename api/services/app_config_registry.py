# ABOUTME: Single source of truth for every app_config key — type, default,
# ABOUTME: validator, admin-form metadata. Callers go through get_typed().
"""AppConfig key registry.

The ``app_config`` table is a JSONB key/value store for org-wide
runtime settings (current ToS version, lead-routing fallback rep,
drive-time fallback minutes, notification-preferences hidden roles,
etc). Phase 1 added the table; Phases 2/3 added consumers — each one
parses the JSONB blob differently and applies its own defaults. Phase 4
ships an admin UI that needs to render an input per key + validate
writes; that's only sound when there's a single registry the admin form
and the runtime callers both read.

Each key registers a ``KeySpec`` with:

- ``name`` — the ``app_config.key`` string.
- ``category`` — admin-form section grouping ("legal", "notifications",
  "calendar", "lead_routing", ...).
- ``field_type`` — admin-form widget hint ("string", "int", "uuid",
  "list[string]"). Determines the React input rendered.
- ``default`` — fallback when the key is missing or malformed; keeps
  callers free of "what if it's not set" branching.
- ``description`` — admin-form tooltip / help text.
- ``parser(raw)`` — extract the typed value from the raw JSONB blob.
  Per-key because Phase 1/2 picked different shapes (``{"version": ...}``
  vs ``{"minutes": ...}`` vs ``{"roles": [...]}``); the registry
  preserves them rather than forcing a data migration.
- ``serializer(typed)`` — inverse of ``parser``; produces the JSONB
  blob to write back. Phase 4 admin calls ``set_typed`` which uses this.
- ``validator(typed)`` — raises ``ValueError`` if the typed value is
  invalid. Phase 4 admin's save handler maps this to a 422.

Adding a new key = one ``register(...)`` call here + a write to the
seed migration. Callers read via ``get_typed(db, "key_name")``.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import AppConfig

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class KeySpec:
    """Declared shape of one ``app_config.key``."""

    name: str
    category: str
    field_type: str  # "string" | "int" | "uuid" | "list[string]"
    description: str
    default: Any
    parser: Callable[[Any], Any]
    serializer: Callable[[Any], dict[str, Any]]
    validator: Callable[[Any], None] = lambda v: None


_REGISTRY: dict[str, KeySpec] = {}


def register(spec: KeySpec) -> KeySpec:
    """Register a new key spec. Idempotent on import — modules that
    declare keys at import time are safe to re-import (test fixtures
    and the like). Re-registering with a different spec raises so the
    registry stays a single source of truth."""
    existing = _REGISTRY.get(spec.name)
    if existing is not None and existing != spec:
        raise RuntimeError(
            f"AppConfig key '{spec.name}' already registered with a different spec; "
            "rename or deduplicate."
        )
    _REGISTRY[spec.name] = spec
    return spec


def get_spec(key: str) -> KeySpec:
    """Lookup a registered KeySpec. Raises ``KeyError`` for unknown keys."""
    return _REGISTRY[key]


def all_specs() -> tuple[KeySpec, ...]:
    """Every registered KeySpec, sorted by ``(category, name)`` so the
    Phase 4 admin form has a deterministic render order."""
    return tuple(sorted(_REGISTRY.values(), key=lambda s: (s.category, s.name)))


async def get_typed(db: AsyncSession, key: str) -> Any:
    """Return the typed value for ``key``. Falls back to the spec's
    ``default`` when the row is missing or the parser raises. Logs
    parse failures so a malformed seed is visible in the logs but
    doesn't crash the caller."""
    spec = get_spec(key)
    raw = (
        await db.execute(select(AppConfig.value).where(AppConfig.key == key))
    ).scalar_one_or_none()
    if raw is None:
        return spec.default
    try:
        return spec.parser(raw)
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        logger.warning(
            "app_config_parse_failed",
            key=key,
            raw=raw,
            error=str(exc),
        )
        return spec.default


async def set_typed(
    db: AsyncSession,
    key: str,
    typed_value: Any,
    *,
    updated_by: uuid.UUID | None,
) -> None:
    """Validate + serialize + upsert. Phase 4 admin write path goes
    through here; the YAML seed loader (planned in Phase 4) will too,
    so both surfaces enforce the same per-key validator."""
    spec = get_spec(key)
    spec.validator(typed_value)
    payload = spec.serializer(typed_value)
    stmt = (
        pg_insert(AppConfig)
        .values(key=key, value=payload, updated_by=updated_by)
        .on_conflict_do_update(
            index_elements=["key"],
            set_={"value": payload, "updated_by": updated_by},
        )
    )
    await db.execute(stmt)
    await db.flush()


# ---------------------------------------------------------------------------
# Built-in key specs.
#
# Each consumer that previously parsed ``app_config.value`` inline now reads
# through ``get_typed(db, KEY)``. The JSONB shapes are preserved (Phase 1/2
# picked different ones — ``{"version": ...}`` vs ``{"minutes": ...}`` vs
# ``{"roles": [...]}``) so no data migration is required.
# ---------------------------------------------------------------------------


def _parse_dict_field(field: str) -> Callable[[Any], Any]:
    def parser(raw: Any) -> Any:
        if isinstance(raw, dict):
            return raw.get(field)
        return None

    return parser


def _serialize_dict_field(field: str) -> Callable[[Any], dict[str, Any]]:
    def serializer(value: Any) -> dict[str, Any]:
        return {field: value}

    return serializer


def _validate_positive_int(v: Any) -> None:
    if not isinstance(v, int) or v <= 0:
        raise ValueError("must be a positive integer")


def _validate_uuid_or_none(v: Any) -> None:
    if v is None:
        return
    if not isinstance(v, str):
        raise ValueError("must be a UUID string or null")
    try:
        uuid.UUID(v)
    except (ValueError, TypeError) as exc:
        raise ValueError("must be a valid UUID") from exc


def _validate_role_list(v: Any) -> None:
    if not isinstance(v, list):
        raise ValueError("must be a list of role slugs")
    for slug in v:
        if not isinstance(slug, str):
            raise ValueError("every entry must be a role slug string")


def _validate_nonempty_string(v: Any) -> None:
    if not isinstance(v, str) or not v.strip():
        raise ValueError("must be a non-empty string")


# Legal — current ToS / Privacy versions. Read by legal_service.
TOS_CURRENT_VERSION = register(
    KeySpec(
        name="tos_current_version",
        category="legal",
        field_type="string",
        description=(
            "Current Terms of Service document version. Bumping this forces "
            "every active user through the re-accept interstitial on next request."
        ),
        default=None,
        parser=_parse_dict_field("version"),
        serializer=_serialize_dict_field("version"),
        validator=_validate_nonempty_string,
    )
)

PRIVACY_CURRENT_VERSION = register(
    KeySpec(
        name="privacy_current_version",
        category="legal",
        field_type="string",
        description=("Current Privacy Policy document version. Same re-accept semantics as ToS."),
        default=None,
        parser=_parse_dict_field("version"),
        serializer=_serialize_dict_field("version"),
        validator=_validate_nonempty_string,
    )
)

# Calendar — drive-time fallback when Google Maps unavailable. Read by
# google_maps_service.fallback_drive_time_minutes.
DRIVE_TIME_FALLBACK_MINUTES = register(
    KeySpec(
        name="drive_time_fallback_minutes",
        category="calendar",
        field_type="int",
        description=(
            "Minutes blocked between back-to-back appraisals when the Google "
            "Maps Distance Matrix API is unavailable or unconfigured."
        ),
        default=60,
        parser=_parse_dict_field("minutes"),
        serializer=_serialize_dict_field("minutes"),
        validator=_validate_positive_int,
    )
)

# Lead routing — fallback rep when no rule matches. Read by
# lead_routing_service._read_default_sales_rep.
DEFAULT_SALES_REP_ID = register(
    KeySpec(
        name="default_sales_rep_id",
        category="lead_routing",
        field_type="uuid",
        description=(
            "User ID of the sales rep who receives any submission no routing "
            "rule matches. Leave unset to surface unmatched leads to manual triage."
        ),
        default=None,
        # Stored as {"user_id": "<uuid>"} per Phase 3 Sprint 3 — kept as
        # the existing shape to avoid a data migration; consumers read
        # the typed UUID via get_typed.
        parser=_parse_dict_field("user_id"),
        serializer=_serialize_dict_field("user_id"),
        validator=_validate_uuid_or_none,
    )
)

# Notifications — roles for which the per-employee preferences page is
# entirely hidden. Read by notification_preferences_service.is_hidden_for_role.
NOTIFICATION_PREFERENCES_HIDDEN_ROLES = register(
    KeySpec(
        name="notification_preferences_hidden_roles",
        category="notifications",
        field_type="list[string]",
        description=(
            "Role slugs for which the /account/notifications page returns 404 "
            "outright. The customer role is read-only by default (separate "
            "hardcoded gate; see ADR-016 #5)."
        ),
        default=[],
        parser=_parse_dict_field("roles"),
        serializer=_serialize_dict_field("roles"),
        validator=_validate_role_list,
    )
)


# ---------------------------------------------------------------------------
# Phase 4 Sprint 3 keys.
# ---------------------------------------------------------------------------

# Canonical intake fields. Mirrors the field list rendered on the customer
# intake form (web/src/pages/IntakeForm.tsx) and the IntakeSubmission Pydantic
# model. Admin can hide / reorder these without a deploy via the AppConfig
# keys below; the customer form fetches the config and renders accordingly.
INTAKE_FIELDS_CANONICAL: tuple[str, ...] = (
    "category_id",
    "make",
    "model",
    "year",
    "serial_number",
    "hours",
    "running_status",
    "ownership_type",
    "location_text",
    "description",
)


def _validate_int_at_least(min_value: int) -> Callable[[Any], None]:
    def validator(v: Any) -> None:
        if not isinstance(v, int) or v < min_value:
            raise ValueError(f"must be an integer ≥ {min_value}")

    return validator


def _validate_int_in_range(min_value: int, max_value: int) -> Callable[[Any], None]:
    def validator(v: Any) -> None:
        if not isinstance(v, int) or v < min_value or v > max_value:
            raise ValueError(f"must be an integer in [{min_value}, {max_value}]")

    return validator


def _validate_string_list(v: Any) -> None:
    if not isinstance(v, list):
        raise ValueError("must be a list of strings")
    for s in v:
        if not isinstance(s, str) or not s.strip():
            raise ValueError("every entry must be a non-empty string")


def _validate_intake_field_subset(v: Any) -> None:
    """Each entry must name a canonical intake field. Prevents typos that
    silently render an empty form (or omit a critical field like make)."""
    _validate_string_list(v)
    canonical = set(INTAKE_FIELDS_CANONICAL)
    unknown = [s for s in v if s not in canonical]
    if unknown:
        raise ValueError(
            f"unknown intake field(s): {sorted(unknown)}. Allowed: {sorted(canonical)}"
        )


# Intake — admin can hide individual fields without a code deploy. Reading
# `intake_fields_visible` returns the list of fields the customer form
# should render; defaults to ALL canonical fields (no fields hidden).
INTAKE_FIELDS_VISIBLE = register(
    KeySpec(
        name="intake_fields_visible",
        category="intake",
        field_type="list[string]",
        description=(
            "Intake form field slugs that the customer-facing form should "
            "render. Defaults to every canonical field. Removing a slug here "
            "hides the field on the customer intake page without a deploy."
        ),
        default=list(INTAKE_FIELDS_CANONICAL),
        parser=_parse_dict_field("fields"),
        serializer=_serialize_dict_field("fields"),
        validator=_validate_intake_field_subset,
    )
)


# Intake — render order. Default mirrors the canonical tuple.
INTAKE_FIELDS_ORDER = register(
    KeySpec(
        name="intake_fields_order",
        category="intake",
        field_type="list[string]",
        description=(
            "Intake form field render order, top-to-bottom. Fields not "
            "listed render in canonical order at the bottom; unknown slugs "
            "are rejected."
        ),
        default=list(INTAKE_FIELDS_CANONICAL),
        parser=_parse_dict_field("fields"),
        serializer=_serialize_dict_field("fields"),
        validator=_validate_intake_field_subset,
    )
)


# Consignment — manager-approval threshold. Phase 6 (manager approval flow)
# will consume this; registering it now so the admin UI surface lands ahead.
CONSIGNMENT_PRICE_CHANGE_THRESHOLD_PCT = register(
    KeySpec(
        name="consignment_price_change_threshold_pct",
        category="consignment",
        field_type="int",
        description=(
            "Percent change between an appraiser's recommended consignment "
            "price and the customer's counter-offer that triggers a manager "
            "approval requirement (Phase 6). Stored as a whole number, "
            "e.g. 10 = 10%."
        ),
        default=10,
        parser=_parse_dict_field("pct"),
        serializer=_serialize_dict_field("pct"),
        validator=_validate_int_in_range(0, 100),
    )
)


# Calendar — default buffer (minutes) between appraisals when no
# Google-Maps-driven travel time is available. Distinct from
# DRIVE_TIME_FALLBACK_MINUTES (which is the Maps-API-failed branch);
# this is the pre-routing default applied by the calendar service when
# scheduling without an explicit override.
CALENDAR_BUFFER_MINUTES_DEFAULT = register(
    KeySpec(
        name="calendar_buffer_minutes_default",
        category="calendar",
        field_type="int",
        description=(
            "Minutes of gap inserted between back-to-back calendar events "
            "when no Google-Maps drive-time is available and no explicit "
            "buffer was passed at schedule time."
        ),
        default=30,
        parser=_parse_dict_field("minutes"),
        serializer=_serialize_dict_field("minutes"),
        validator=_validate_positive_int,
    )
)


# Security — access-token TTL in minutes. JWT_ACCESS_TTL_MINUTES env var
# remains the floor (set in config.py) but admin can raise it within
# operational limits without a redeploy. auth_service reads through this
# key during token mint when the value is set.
SECURITY_SESSION_TTL_MINUTES = register(
    KeySpec(
        name="security_session_ttl_minutes",
        category="security",
        field_type="int",
        description=(
            "Access-token TTL in minutes. Range 5–720 (12h max). Bumping "
            "this affects newly-minted tokens only; existing tokens keep "
            "their original expiry."
        ),
        default=60,
        parser=_parse_dict_field("minutes"),
        serializer=_serialize_dict_field("minutes"),
        validator=_validate_int_in_range(5, 720),
    )
)


# Notifications — roles for which the /account/notifications page is
# read-only (the user can SEE their preference but can't EDIT it).
# Distinct from NOTIFICATION_PREFERENCES_HIDDEN_ROLES (which 404s the
# page outright). Architectural Debt #2 from the Phase 4 dev plan:
# previously hard-coded as `_READ_ONLY_ROLES = {"customer"}` in
# notification_preferences_service; reading through AppConfig means
# admin can revoke/grant edit access without a deploy.
NOTIFICATION_PREFERENCES_READ_ONLY_ROLES = register(
    KeySpec(
        name="notification_preferences_read_only_roles",
        category="notifications",
        field_type="list[string]",
        description=(
            "Role slugs that can VIEW their notification preferences but "
            "cannot edit them. Defaults to [customer] to preserve the "
            "pre-Phase-4 behavior. Distinct from _hidden_roles which "
            "404s the page outright."
        ),
        default=["customer"],
        parser=_parse_dict_field("roles"),
        serializer=_serialize_dict_field("roles"),
        validator=_validate_role_list,
    )
)


# Operations — overdue threshold for the admin operations dashboard.
# Sprint 1 hard-coded 7 days in admin_operations_service; lifting to
# AppConfig lets admin tune the highlight without a deploy.
EQUIPMENT_RECORD_OVERDUE_THRESHOLD_DAYS = register(
    KeySpec(
        name="equipment_record_overdue_threshold_days",
        category="operations",
        field_type="int",
        description=(
            "Days a record can sit in its current status before the admin "
            "operations dashboard flags it overdue. Used for the row "
            "highlight + the `overdue_only` filter."
        ),
        default=7,
        parser=_parse_dict_field("days"),
        serializer=_serialize_dict_field("days"),
        validator=_validate_int_at_least(1),
    )
)

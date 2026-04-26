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

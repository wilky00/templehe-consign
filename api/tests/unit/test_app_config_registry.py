# ABOUTME: Unit tests for the AppConfig registry — parser, serializer, validator round-trips.
# ABOUTME: No DB; exercises the typed-value extraction + write-path validation in pure functions.
from __future__ import annotations

import pytest

from services import app_config_registry
from services.app_config_registry import (
    DEFAULT_SALES_REP_ID,
    DRIVE_TIME_FALLBACK_MINUTES,
    NOTIFICATION_PREFERENCES_HIDDEN_ROLES,
    PRIVACY_CURRENT_VERSION,
    TOS_CURRENT_VERSION,
)


def test_all_specs_returns_every_registered_key():
    names = {s.name for s in app_config_registry.all_specs()}
    expected = {
        TOS_CURRENT_VERSION.name,
        PRIVACY_CURRENT_VERSION.name,
        DRIVE_TIME_FALLBACK_MINUTES.name,
        DEFAULT_SALES_REP_ID.name,
        NOTIFICATION_PREFERENCES_HIDDEN_ROLES.name,
    }
    # Subset: future keys can register without breaking the test.
    assert expected.issubset(names)


def test_get_spec_raises_for_unknown_key():
    with pytest.raises(KeyError):
        app_config_registry.get_spec("not_a_real_key")


def test_register_idempotent_for_identical_spec():
    app_config_registry.register(TOS_CURRENT_VERSION)  # no-op


# --- ToS / Privacy version: {"version": <str>} ---


def test_tos_version_parser_extracts_version_string():
    assert TOS_CURRENT_VERSION.parser({"version": "1.2"}) == "1.2"


def test_tos_version_parser_returns_none_on_unexpected_shape():
    assert TOS_CURRENT_VERSION.parser({"value": "1"}) is None
    assert TOS_CURRENT_VERSION.parser([1, 2, 3]) is None
    assert TOS_CURRENT_VERSION.parser(None) is None


def test_tos_version_serializer_round_trips():
    assert TOS_CURRENT_VERSION.serializer("2") == {"version": "2"}
    assert TOS_CURRENT_VERSION.parser(TOS_CURRENT_VERSION.serializer("3.0")) == "3.0"


def test_tos_version_validator_requires_nonempty_string():
    TOS_CURRENT_VERSION.validator("1")  # passes
    with pytest.raises(ValueError):
        TOS_CURRENT_VERSION.validator("")
    with pytest.raises(ValueError):
        TOS_CURRENT_VERSION.validator(1)
    with pytest.raises(ValueError):
        TOS_CURRENT_VERSION.validator(None)


# --- Drive-time fallback: {"minutes": <int>} ---


def test_drive_time_minutes_parser_returns_int():
    assert DRIVE_TIME_FALLBACK_MINUTES.parser({"minutes": 90}) == 90


def test_drive_time_minutes_validator_rejects_zero_and_negative():
    DRIVE_TIME_FALLBACK_MINUTES.validator(60)  # passes
    with pytest.raises(ValueError):
        DRIVE_TIME_FALLBACK_MINUTES.validator(0)
    with pytest.raises(ValueError):
        DRIVE_TIME_FALLBACK_MINUTES.validator(-5)
    with pytest.raises(ValueError):
        DRIVE_TIME_FALLBACK_MINUTES.validator("60")  # type: ignore[arg-type]


def test_drive_time_minutes_default_is_60():
    # The runtime default lives on the spec — keeps consumers free of
    # "if missing, use 60" branching.
    assert DRIVE_TIME_FALLBACK_MINUTES.default == 60


# --- Default sales rep: {"user_id": "<uuid>"} ---


def test_default_sales_rep_validator_accepts_none_and_uuid():
    DEFAULT_SALES_REP_ID.validator(None)  # passes
    DEFAULT_SALES_REP_ID.validator("550e8400-e29b-41d4-a716-446655440000")  # passes
    with pytest.raises(ValueError):
        DEFAULT_SALES_REP_ID.validator("not-a-uuid")
    with pytest.raises(ValueError):
        DEFAULT_SALES_REP_ID.validator(42)  # type: ignore[arg-type]


def test_default_sales_rep_uses_existing_jsonb_shape():
    """The Phase 3 Sprint 3 schema picked {"user_id": ...}; the registry
    preserves the shape to avoid a data migration."""
    assert DEFAULT_SALES_REP_ID.serializer("u-1") == {"user_id": "u-1"}
    assert DEFAULT_SALES_REP_ID.parser({"user_id": "u-1"}) == "u-1"


# --- Hidden roles: {"roles": [...]} ---


def test_hidden_roles_parser_extracts_list():
    out = NOTIFICATION_PREFERENCES_HIDDEN_ROLES.parser({"roles": ["customer", "appraiser"]})
    assert out == ["customer", "appraiser"]


def test_hidden_roles_validator_rejects_non_list_and_non_string_entries():
    NOTIFICATION_PREFERENCES_HIDDEN_ROLES.validator([])  # passes
    NOTIFICATION_PREFERENCES_HIDDEN_ROLES.validator(["customer"])  # passes
    with pytest.raises(ValueError):
        NOTIFICATION_PREFERENCES_HIDDEN_ROLES.validator("customer")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        NOTIFICATION_PREFERENCES_HIDDEN_ROLES.validator(["customer", 42])  # type: ignore[list-item]


def test_hidden_roles_default_is_empty_list():
    assert NOTIFICATION_PREFERENCES_HIDDEN_ROLES.default == []

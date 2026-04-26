# ABOUTME: Phase 4 Sprint 4 — discriminated-union variant validators per rule_type.
# ABOUTME: Pure-function tests; no DB. Confirms parse_conditions raises on bad shape per type.
from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from schemas.routing import (
    AdHocConditions,
    GeographicConditions,
    MetroArea,
    RoundRobinConditions,
    parse_conditions,
)

# --- AdHoc ---------------------------------------------------------------- #


def test_ad_hoc_accepts_email_domain():
    cond = AdHocConditions(condition_type="email_domain", value="acme.com")
    assert cond.condition_type == "email_domain"
    assert cond.value == "acme.com"


def test_ad_hoc_rejects_unknown_condition_type():
    with pytest.raises(ValidationError) as exc:
        AdHocConditions(condition_type="not_a_type", value="x")  # type: ignore[arg-type]
    assert "condition_type" in str(exc.value)


def test_ad_hoc_rejects_empty_value():
    with pytest.raises(ValidationError) as exc:
        AdHocConditions(condition_type="email_domain", value="")
    assert "value" in str(exc.value)


def test_ad_hoc_rejects_extra_keys():
    with pytest.raises(ValidationError):
        AdHocConditions.model_validate(
            {"condition_type": "email_domain", "value": "x", "stowaway": True}
        )


# --- Geographic ----------------------------------------------------------- #


def test_geographic_requires_at_least_one_condition():
    with pytest.raises(ValidationError) as exc:
        GeographicConditions()
    assert "at least one" in str(exc.value).lower()


def test_geographic_state_list_must_be_two_letters():
    with pytest.raises(ValidationError) as exc:
        GeographicConditions(state_list=["California"])
    assert "state_list" in str(exc.value).lower()


def test_geographic_state_list_lowercase_two_chars_passes():
    # Validator only checks length 2; uppercase enforcement is admin-side
    # (handled by the customer schema's state validator, not here).
    cond = GeographicConditions(state_list=["ca", "TX"])
    assert cond.state_list == ["ca", "TX"]


def test_geographic_metro_radius_must_be_positive():
    with pytest.raises(ValidationError) as exc:
        GeographicConditions(
            metro_area=MetroArea(center_lat=39.7, center_lon=-104.9, radius_miles=0)
        )
    assert "radius_miles" in str(exc.value).lower()


def test_geographic_metro_lat_lon_clamped():
    with pytest.raises(ValidationError):
        MetroArea(center_lat=99, center_lon=0, radius_miles=10)
    with pytest.raises(ValidationError):
        MetroArea(center_lat=0, center_lon=200, radius_miles=10)


def test_geographic_with_zip_list_alone_passes():
    cond = GeographicConditions(zip_list=["80210", "80211"])
    assert cond.zip_list == ["80210", "80211"]


# --- RoundRobin ----------------------------------------------------------- #


def test_round_robin_rejects_empty_rep_ids():
    with pytest.raises(ValidationError) as exc:
        RoundRobinConditions(rep_ids=[])
    assert "rep_ids" in str(exc.value).lower()


def test_round_robin_accepts_uuid_strings_or_objects():
    rid = uuid.uuid4()
    cond = RoundRobinConditions(rep_ids=[rid, str(uuid.uuid4())])
    assert len(cond.rep_ids) == 2
    assert cond.rep_ids[0] == rid


def test_round_robin_rejects_non_uuid_string():
    with pytest.raises(ValidationError) as exc:
        RoundRobinConditions(rep_ids=["not-a-uuid"])
    assert "rep_ids" in str(exc.value).lower()


# --- parse_conditions dispatch ------------------------------------------- #


def test_parse_conditions_dispatches_per_rule_type():
    a = parse_conditions("ad_hoc", {"condition_type": "email_domain", "value": "x.com"})
    assert isinstance(a, AdHocConditions)
    g = parse_conditions("geographic", {"state_list": ["CA"]})
    assert isinstance(g, GeographicConditions)
    rid = uuid.uuid4()
    r = parse_conditions("round_robin", {"rep_ids": [str(rid)]})
    assert isinstance(r, RoundRobinConditions)


def test_parse_conditions_unknown_rule_type_raises_value_error():
    with pytest.raises(ValueError) as exc:
        parse_conditions("not_a_type", {})
    assert "unknown rule_type" in str(exc.value).lower()

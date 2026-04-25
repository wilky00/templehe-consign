# ABOUTME: Pure-function tests for the lead routing matcher logic — no DB required.
# ABOUTME: Waterfall + counter behavior is covered by integration tests; this nails the matchers.
from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from services.lead_routing_service import (
    _ad_hoc_matches,
    _geo_matches,
    _normalize_zip,
    _round_robin_rep_ids,
    _zip_entry_matches,
)


def _rule(conditions: dict | None) -> SimpleNamespace:
    """Tiny stand-in for LeadRoutingRule — only ``conditions`` is read here."""
    return SimpleNamespace(conditions=conditions)


# --- ad-hoc matcher --------------------------------------------------------- #


def test_ad_hoc_matches_customer_id():
    cust_id = uuid.uuid4()
    rule = _rule({"condition_type": "customer_id", "value": str(cust_id)})
    assert _ad_hoc_matches(rule, customer_id=cust_id, customer_email=None) is True


def test_ad_hoc_skips_when_customer_id_differs():
    rule = _rule({"condition_type": "customer_id", "value": str(uuid.uuid4())})
    assert _ad_hoc_matches(rule, customer_id=uuid.uuid4(), customer_email=None) is False


def test_ad_hoc_matches_email_domain_with_or_without_at_sign():
    bare = _rule({"condition_type": "email_domain", "value": "acme.com"})
    prefixed = _rule({"condition_type": "email_domain", "value": "@acme.com"})
    cust = uuid.uuid4()
    assert _ad_hoc_matches(bare, customer_id=cust, customer_email="ceo@ACME.com") is True
    assert _ad_hoc_matches(prefixed, customer_id=cust, customer_email="ceo@acme.com") is True
    assert _ad_hoc_matches(bare, customer_id=cust, customer_email="ceo@other.com") is False


def test_ad_hoc_returns_false_for_malformed_rule():
    cust = uuid.uuid4()
    assert _ad_hoc_matches(_rule(None), customer_id=cust, customer_email=None) is False
    assert (
        _ad_hoc_matches(_rule({"condition_type": "weird"}), customer_id=cust, customer_email=None)
        is False
    )
    bad_uuid = _rule({"condition_type": "customer_id", "value": "not-a-uuid"})
    assert _ad_hoc_matches(bad_uuid, customer_id=cust, customer_email=None) is False


# --- geographic matcher ----------------------------------------------------- #


def test_geo_matches_state_list_case_insensitive():
    rule = _rule({"state_list": ["CA", "OR", "WA"]})
    assert _geo_matches(rule, state="ca", zip_code=None) is True
    assert _geo_matches(rule, state="NV", zip_code=None) is False


def test_geo_matches_zip_exact_and_range():
    rule = _rule({"zip_list": ["90210", "30301-30399"]})
    assert _geo_matches(rule, state=None, zip_code="90210") is True
    assert _geo_matches(rule, state=None, zip_code="30350") is True
    assert _geo_matches(rule, state=None, zip_code="30400") is False
    # zip+4 still matches against the 5-digit head
    assert _geo_matches(rule, state=None, zip_code="90210-1234") is True


def test_geo_does_not_match_when_neither_field_present():
    rule = _rule({"zip_list": ["90210"]})
    assert _geo_matches(rule, state="CA", zip_code=None) is False


def test_geo_skips_metro_area_silently():
    """Metro-area routing is deferred to Sprint 4 — must not blow up if present."""
    rule = _rule(
        {
            "metro_area": {
                "name": "LA",
                "center_lat": 34,
                "center_lon": -118,
                "radius_miles": 50,
            }
        }
    )
    assert _geo_matches(rule, state="CA", zip_code="90210") is False


# --- zip helpers ------------------------------------------------------------ #


def test_normalize_zip_handles_plus_four_and_short_inputs():
    assert _normalize_zip("90210") == 90210
    assert _normalize_zip("90210-1234") == 90210
    assert _normalize_zip("abcde") is None
    assert _normalize_zip("123") is None


def test_zip_entry_matches_exact_and_range():
    assert _zip_entry_matches("90210", 90210) is True
    assert _zip_entry_matches("30301-30399", 30350) is True
    assert _zip_entry_matches("30301-30399", 30300) is False
    assert _zip_entry_matches("not-a-zip", 12345) is False
    # Malformed range is treated as no match, not an error.
    assert _zip_entry_matches("foo-bar", 12345) is False


# --- round robin parsing ---------------------------------------------------- #


def test_round_robin_rep_ids_filters_invalid():
    a = uuid.uuid4()
    b = uuid.uuid4()
    rule = _rule({"rep_ids": [str(a), "not-a-uuid", str(b)]})
    assert _round_robin_rep_ids(rule) == [a, b]


def test_round_robin_rep_ids_returns_empty_for_missing_or_wrong_shape():
    assert _round_robin_rep_ids(_rule(None)) == []
    assert _round_robin_rep_ids(_rule({"rep_ids": "not-a-list"})) == []
    assert _round_robin_rep_ids(_rule({})) == []


# --- pytest sanity --------------------------------------------------------- #


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("00000", 0),
        ("12345", 12345),
        ("12345-6789", 12345),
        ("99999", 99999),
    ],
)
def test_normalize_zip_parametric(raw: str, expected: int):
    assert _normalize_zip(raw) == expected

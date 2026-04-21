# ABOUTME: Unit tests for the rate-limit middleware helpers — client IP resolution only.
# ABOUTME: Counter behaviour is covered by integration tests in test_auth_flows.py / test_rbac.py.
from __future__ import annotations

from starlette.requests import Request

from middleware.rate_limit import get_client_ip


def _make_request(headers: dict[str, str], client: tuple[str, int] | None = ("4.5.6.7", 1234)):
    scope = {
        "type": "http",
        "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
        "client": client,
    }
    return Request(scope)


def test_client_ip_prefers_cf_connecting_ip():
    req = _make_request({"CF-Connecting-IP": "1.2.3.4", "X-Forwarded-For": "9.9.9.9, 8.8.8.8"})
    assert get_client_ip(req) == "1.2.3.4"


def test_client_ip_falls_back_to_xff():
    req = _make_request({"X-Forwarded-For": "1.2.3.4, 5.6.7.8"})
    assert get_client_ip(req) == "1.2.3.4"


def test_client_ip_strips_whitespace_from_xff_first_entry():
    req = _make_request({"X-Forwarded-For": "   1.2.3.4 , 5.6.7.8"})
    assert get_client_ip(req) == "1.2.3.4"


def test_client_ip_falls_back_to_socket_peer():
    req = _make_request({})
    assert get_client_ip(req) == "4.5.6.7"


def test_client_ip_returns_unknown_when_no_client():
    req = _make_request({}, client=None)
    assert get_client_ip(req) == "unknown"


def test_client_ip_trims_cf_header_whitespace():
    req = _make_request({"CF-Connecting-IP": "  1.2.3.4  "})
    assert get_client_ip(req) == "1.2.3.4"

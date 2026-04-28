# ABOUTME: Phase 4 Sprint 7 — per-integration "test" implementations behind one interface.
# ABOUTME: Used by admin_credentials_service.test() and the health poller.
"""Integration testers — Phase 4 Sprint 7.

Each integration has its own probe: hit the upstream service with a
minimum-cost call and report back. The admin UI shows the result; the
health poller writes it to ``service_health_state`` for the dashboard.

Public surface:

- :class:`TestResult` — uniform return type so the admin UI / poller
  can render any tester's output without dispatch.
- :func:`run` — single dispatch function; maps integration name to the
  right tester. Unknown name → ``TestResult(success=False, detail=...)``,
  not an exception, so the admin UI renders the failure inline.

Multi-field integrations (Twilio, eSign, valuation) accept a JSON
plaintext blob. Tester parses it; bad JSON or missing keys → graceful
``failure`` result, again so the admin UI surfaces the misconfiguration.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any

import httpx

from config import settings

# Each tester is a coroutine: ``async def test(plaintext, **kwargs) -> TestResult``.
# Caller supplies whatever extra arguments make sense (e.g. ``to_email`` for
# SendGrid). All testers are written to keep credentials in process memory only.


@dataclass(frozen=True)
class TestResult:
    success: bool
    detail: str
    latency_ms: int
    status: str = "success"  # 'success' | 'failure' | 'stubbed'


def _ms_since(t0: float) -> int:
    return int((time.perf_counter() - t0) * 1000)


# --------------------------------------------------------------------------- #
# Slack
# --------------------------------------------------------------------------- #


async def test_slack(plaintext: str, **_: Any) -> TestResult:
    """POST a minimal message to a Slack webhook URL.

    Slack accepts ``{"text": "..."}`` to a webhook. A 200 with body
    ``"ok"`` indicates the webhook is wired correctly. Anything else
    (4xx/5xx, non-"ok" body) → failure with the upstream detail.
    """
    t0 = time.perf_counter()
    if not plaintext.startswith("https://hooks.slack.com/"):
        return TestResult(
            success=False,
            detail="Slack webhook URL must start with https://hooks.slack.com/",
            latency_ms=_ms_since(t0),
            status="failure",
        )
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                plaintext,
                json={"text": "TempleHE admin connectivity test ✓"},
            )
        if response.status_code == 200 and response.text.strip() == "ok":
            return TestResult(
                success=True,
                detail="Webhook accepted the test message.",
                latency_ms=_ms_since(t0),
            )
        return TestResult(
            success=False,
            detail=(f"Slack returned HTTP {response.status_code}: {response.text[:200]}"),
            latency_ms=_ms_since(t0),
            status="failure",
        )
    except httpx.HTTPError as exc:
        return TestResult(
            success=False,
            detail=f"Slack request failed: {type(exc).__name__}: {exc}",
            latency_ms=_ms_since(t0),
            status="failure",
        )


# --------------------------------------------------------------------------- #
# Twilio (multi-field — JSON plaintext)
# --------------------------------------------------------------------------- #


def _parse_twilio(plaintext: str) -> tuple[str, str, str] | None:
    try:
        data = json.loads(plaintext)
    except (json.JSONDecodeError, TypeError):
        return None
    sid = data.get("account_sid", "")
    token = data.get("auth_token", "")
    from_number = data.get("from_number", "")
    if not (sid and token and from_number):
        return None
    return sid, token, from_number


async def test_twilio(plaintext: str, *, to_number: str = "", **_: Any) -> TestResult:
    """Validate Twilio creds against the Account API (no message sent).

    Hitting ``GET /2010-04-01/Accounts/{sid}.json`` with HTTP Basic
    auth confirms the account_sid + auth_token are valid without
    consuming a message segment. If a ``to_number`` is supplied we
    also send a test SMS — admin opt-in, not the default."""
    t0 = time.perf_counter()
    parsed = _parse_twilio(plaintext)
    if parsed is None:
        return TestResult(
            success=False,
            detail=(
                "Twilio credential payload must be JSON with "
                "account_sid + auth_token + from_number."
            ),
            latency_ms=_ms_since(t0),
            status="failure",
        )
    sid, token, from_number = parsed
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                f"https://api.twilio.com/2010-04-01/Accounts/{sid}.json",
                auth=(sid, token),
            )
            if response.status_code != 200:
                return TestResult(
                    success=False,
                    detail=(
                        f"Twilio account fetch returned HTTP {response.status_code}: "
                        f"{response.text[:200]}"
                    ),
                    latency_ms=_ms_since(t0),
                    status="failure",
                )
            # Optional: send a real test SMS when admin supplied a number.
            if to_number:
                sms = await client.post(
                    f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json",
                    auth=(sid, token),
                    data={
                        "From": from_number,
                        "To": to_number,
                        "Body": "TempleHE admin connectivity test",
                    },
                )
                if sms.status_code not in (200, 201):
                    return TestResult(
                        success=False,
                        detail=(f"Twilio SMS failed (HTTP {sms.status_code}): {sms.text[:200]}"),
                        latency_ms=_ms_since(t0),
                        status="failure",
                    )
                return TestResult(
                    success=True,
                    detail=f"Twilio creds valid; test SMS dispatched to {to_number}.",
                    latency_ms=_ms_since(t0),
                )
        return TestResult(
            success=True,
            detail="Twilio creds valid (account fetch succeeded).",
            latency_ms=_ms_since(t0),
        )
    except httpx.HTTPError as exc:
        return TestResult(
            success=False,
            detail=f"Twilio request failed: {type(exc).__name__}: {exc}",
            latency_ms=_ms_since(t0),
            status="failure",
        )


# --------------------------------------------------------------------------- #
# SendGrid
# --------------------------------------------------------------------------- #


async def test_sendgrid(plaintext: str, *, to_email: str = "", **_: Any) -> TestResult:
    """Validate the SendGrid API key against ``GET /v3/scopes``.

    Phase 5 Sprint 0 — when ``to_email`` is supplied (admin opt-in), an
    actual test email is sent via ``POST /v3/mail/send`` after the scope
    check passes. Mirrors the Twilio + ``to_number`` pattern. Without
    ``to_email``, no email is sent."""
    t0 = time.perf_counter()
    if not plaintext.startswith("SG."):
        return TestResult(
            success=False,
            detail="SendGrid API keys conventionally start with 'SG.'.",
            latency_ms=_ms_since(t0),
            status="failure",
        )
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                "https://api.sendgrid.com/v3/scopes",
                headers={"Authorization": f"Bearer {plaintext}"},
            )
            if response.status_code != 200:
                return TestResult(
                    success=False,
                    detail=(
                        f"SendGrid scope fetch returned HTTP {response.status_code}: "
                        f"{response.text[:200]}"
                    ),
                    latency_ms=_ms_since(t0),
                    status="failure",
                )
            if to_email:
                send = await client.post(
                    "https://api.sendgrid.com/v3/mail/send",
                    headers={
                        "Authorization": f"Bearer {plaintext}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "personalizations": [{"to": [{"email": to_email}]}],
                        "from": {
                            "email": settings.sendgrid_from_email,
                            "name": settings.sendgrid_from_name,
                        },
                        "subject": "TempleHE admin connectivity test",
                        "content": [
                            {
                                "type": "text/plain",
                                "value": "TempleHE admin SendGrid test message.",
                            }
                        ],
                    },
                )
                if send.status_code not in (200, 202):
                    return TestResult(
                        success=False,
                        detail=(
                            f"SendGrid mail send failed (HTTP {send.status_code}): "
                            f"{send.text[:200]}"
                        ),
                        latency_ms=_ms_since(t0),
                        status="failure",
                    )
                return TestResult(
                    success=True,
                    detail=f"SendGrid key valid; test email dispatched to {to_email}.",
                    latency_ms=_ms_since(t0),
                )
        return TestResult(
            success=True,
            detail="SendGrid API key valid (scope fetch succeeded).",
            latency_ms=_ms_since(t0),
        )
    except httpx.HTTPError as exc:
        return TestResult(
            success=False,
            detail=f"SendGrid request failed: {type(exc).__name__}: {exc}",
            latency_ms=_ms_since(t0),
            status="failure",
        )


# --------------------------------------------------------------------------- #
# Google Maps Platform — Geocoding API
# --------------------------------------------------------------------------- #


async def test_google_maps(plaintext: str, **_: Any) -> TestResult:
    """Geocode a known US address — sanity-check the API key."""
    t0 = time.perf_counter()
    if not plaintext:
        return TestResult(
            success=False,
            detail="Google Maps API key is empty.",
            latency_ms=_ms_since(t0),
            status="failure",
        )
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                "https://maps.googleapis.com/maps/api/geocode/json",
                params={
                    "address": "1600 Amphitheatre Parkway, Mountain View, CA",
                    "key": plaintext,
                },
            )
        if response.status_code != 200:
            return TestResult(
                success=False,
                detail=(f"Google Maps returned HTTP {response.status_code}: {response.text[:200]}"),
                latency_ms=_ms_since(t0),
                status="failure",
            )
        body = response.json()
        if body.get("status") != "OK":
            return TestResult(
                success=False,
                detail=(
                    f"Geocode status={body.get('status')}; "
                    f"error={body.get('error_message', '(none)')}"
                ),
                latency_ms=_ms_since(t0),
                status="failure",
            )
        return TestResult(
            success=True,
            detail="Geocode succeeded for sample US address.",
            latency_ms=_ms_since(t0),
        )
    except httpx.HTTPError as exc:
        return TestResult(
            success=False,
            detail=f"Google Maps request failed: {type(exc).__name__}: {exc}",
            latency_ms=_ms_since(t0),
            status="failure",
        )


# --------------------------------------------------------------------------- #
# Stubbed providers (Phase 5+ / Phase 6+ wiring)
# --------------------------------------------------------------------------- #


async def test_stubbed(plaintext: str, **_: Any) -> TestResult:  # noqa: ARG001
    return TestResult(
        success=True,
        detail="Provider is stubbed — connection not validated.",
        latency_ms=0,
        status="stubbed",
    )


# --------------------------------------------------------------------------- #
# Dispatch
# --------------------------------------------------------------------------- #

# Single source of truth for "which integrations exist + how to test them".
# Order matches the admin UI render order; "stubbed" providers stay in the
# list so admin can still save credentials for them ahead of integration.
_TESTERS = {
    "slack": test_slack,
    "twilio": test_twilio,
    "sendgrid": test_sendgrid,
    "google_maps": test_google_maps,
    "esign": test_stubbed,
    "valuation": test_stubbed,
}


def known_integrations() -> list[str]:
    return list(_TESTERS.keys())


def is_known(name: str) -> bool:
    return name in _TESTERS


async def run(name: str, plaintext: str, **kwargs: Any) -> TestResult:
    """Dispatch to the named tester. Unknown name → graceful failure."""
    tester = _TESTERS.get(name)
    if tester is None:
        return TestResult(
            success=False,
            detail=f"Unknown integration: {name}",
            latency_ms=0,
            status="failure",
        )
    return await tester(plaintext, **kwargs)

# ABOUTME: Unit tests for per-integration testers — uses respx to mock httpx.
from __future__ import annotations

import json

import httpx
import pytest
import respx

from services import integration_testers


@pytest.mark.asyncio
@respx.mock
async def test_slack_success() -> None:
    respx.post("https://hooks.slack.com/services/T/B/X").respond(status_code=200, text="ok")
    result = await integration_testers.test_slack("https://hooks.slack.com/services/T/B/X")
    assert result.success is True
    assert result.status == "success"
    assert result.latency_ms >= 0


@pytest.mark.asyncio
async def test_slack_rejects_non_slack_url() -> None:
    result = await integration_testers.test_slack("https://example.com/bogus")
    assert result.success is False
    assert "https://hooks.slack.com/" in result.detail


@pytest.mark.asyncio
@respx.mock
async def test_slack_failure_propagates_status() -> None:
    respx.post("https://hooks.slack.com/services/T/B/X").respond(
        status_code=403, text="invalid_token"
    )
    result = await integration_testers.test_slack("https://hooks.slack.com/services/T/B/X")
    assert result.success is False
    assert "403" in result.detail


@pytest.mark.asyncio
@respx.mock
async def test_twilio_creds_valid_no_sms() -> None:
    payload = json.dumps({"account_sid": "ACxxxx", "auth_token": "tok", "from_number": "+15551234"})
    respx.get("https://api.twilio.com/2010-04-01/Accounts/ACxxxx.json").respond(
        status_code=200, json={"sid": "ACxxxx", "status": "active"}
    )
    result = await integration_testers.test_twilio(payload)
    assert result.success is True
    assert "valid" in result.detail.lower()


@pytest.mark.asyncio
@respx.mock
async def test_twilio_creds_invalid() -> None:
    payload = json.dumps(
        {"account_sid": "ACxxxx", "auth_token": "wrong", "from_number": "+15551234"}
    )
    respx.get("https://api.twilio.com/2010-04-01/Accounts/ACxxxx.json").respond(
        status_code=401, text="auth required"
    )
    result = await integration_testers.test_twilio(payload)
    assert result.success is False
    assert "401" in result.detail


@pytest.mark.asyncio
async def test_twilio_payload_must_be_json() -> None:
    result = await integration_testers.test_twilio("not-a-json-blob")
    assert result.success is False
    assert "JSON" in result.detail


@pytest.mark.asyncio
@respx.mock
async def test_twilio_with_to_number_sends_sms() -> None:
    payload = json.dumps({"account_sid": "ACxxxx", "auth_token": "tok", "from_number": "+15551234"})
    respx.get("https://api.twilio.com/2010-04-01/Accounts/ACxxxx.json").respond(
        status_code=200, json={"sid": "ACxxxx"}
    )
    sms_route = respx.post(
        "https://api.twilio.com/2010-04-01/Accounts/ACxxxx/Messages.json"
    ).respond(status_code=201, json={"sid": "MSGxxxx", "status": "queued"})
    result = await integration_testers.test_twilio(payload, to_number="+15559999999")
    assert result.success is True
    assert sms_route.called
    assert "+15559999999" in result.detail


@pytest.mark.asyncio
@respx.mock
async def test_sendgrid_success() -> None:
    respx.get("https://api.sendgrid.com/v3/scopes").respond(
        status_code=200, json={"scopes": ["mail.send"]}
    )
    result = await integration_testers.test_sendgrid("SG.testkey")
    assert result.success is True


@pytest.mark.asyncio
async def test_sendgrid_rejects_non_sg_key() -> None:
    result = await integration_testers.test_sendgrid("plain-string")
    assert result.success is False
    assert "SG." in result.detail


@pytest.mark.asyncio
@respx.mock
async def test_google_maps_success() -> None:
    respx.get("https://maps.googleapis.com/maps/api/geocode/json").respond(
        status_code=200, json={"status": "OK", "results": [{}]}
    )
    result = await integration_testers.test_google_maps("AIzaXYZ")
    assert result.success is True


@pytest.mark.asyncio
@respx.mock
async def test_google_maps_invalid_key() -> None:
    respx.get("https://maps.googleapis.com/maps/api/geocode/json").respond(
        status_code=200,
        json={"status": "REQUEST_DENIED", "error_message": "API key invalid"},
    )
    result = await integration_testers.test_google_maps("AIzaBAD")
    assert result.success is False
    assert "REQUEST_DENIED" in result.detail


@pytest.mark.asyncio
async def test_run_unknown_returns_failure_not_exception() -> None:
    result = await integration_testers.run("not-a-real-integration", "value")
    assert result.success is False
    assert "Unknown integration" in result.detail


@pytest.mark.asyncio
async def test_run_stubbed_provider() -> None:
    result = await integration_testers.run("esign", "anything")
    assert result.success is True
    assert result.status == "stubbed"


@pytest.mark.asyncio
@respx.mock
async def test_network_error_surfaces_as_failure() -> None:
    respx.post("https://hooks.slack.com/services/T/B/X").mock(
        side_effect=httpx.ConnectError("connection refused")
    )
    result = await integration_testers.test_slack("https://hooks.slack.com/services/T/B/X")
    assert result.success is False
    assert "ConnectError" in result.detail


def test_known_integrations_lists_all_six() -> None:
    names = integration_testers.known_integrations()
    assert {"slack", "twilio", "sendgrid", "google_maps", "esign", "valuation"} == set(names)

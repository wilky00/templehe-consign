# ABOUTME: Unit tests for slack_dispatch_service staging-channel guard (Phase 5 Sprint 0).
# ABOUTME: Verifies non-prod overrides the channel field; prod passes through unchanged.
from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest
import respx
from httpx import Response

from config import settings
from services import slack_dispatch_service


@pytest.fixture(autouse=True)
def _restore_settings():
    original_env = settings.environment
    original_channel = settings.slack_staging_channel_id
    yield
    settings.environment = original_env
    settings.slack_staging_channel_id = original_channel


@pytest.mark.asyncio
@respx.mock
async def test_non_prod_with_staging_channel_overrides_payload() -> None:
    """environment != 'production' AND slack_staging_channel_id set →
    outbound payload carries the override channel."""
    settings.environment = "staging"
    settings.slack_staging_channel_id = "C-STAGING-123"

    route = respx.post("https://hooks.slack.com/services/T/B/X").mock(
        return_value=Response(status_code=200, text="ok")
    )

    with patch.object(
        slack_dispatch_service,
        "_load_webhook_url",
        AsyncMock(return_value="https://hooks.slack.com/services/T/B/X"),
    ):
        await slack_dispatch_service.send(db=None, text_body="hello")  # type: ignore[arg-type]

    assert route.called
    sent_body = json.loads(route.calls[0].request.content)
    assert sent_body["channel"] == "C-STAGING-123"
    assert sent_body["text"] == "hello"


@pytest.mark.asyncio
@respx.mock
async def test_prod_environment_does_not_override_channel() -> None:
    """environment == 'production' → no override even when staging
    channel is set (defensive: shouldn't be set in prod, but guard
    against config drift)."""
    settings.environment = "production"
    settings.slack_staging_channel_id = "C-STAGING-123"

    route = respx.post("https://hooks.slack.com/services/T/B/X").mock(
        return_value=Response(status_code=200, text="ok")
    )

    with patch.object(
        slack_dispatch_service,
        "_load_webhook_url",
        AsyncMock(return_value="https://hooks.slack.com/services/T/B/X"),
    ):
        await slack_dispatch_service.send(db=None, text_body="hello")  # type: ignore[arg-type]

    sent_body = json.loads(route.calls[0].request.content)
    assert "channel" not in sent_body


@pytest.mark.asyncio
@respx.mock
async def test_non_prod_without_staging_channel_passes_through() -> None:
    """environment != 'production' AND staging channel unset → no
    override; webhook's saved channel routing wins."""
    settings.environment = "development"
    settings.slack_staging_channel_id = ""

    route = respx.post("https://hooks.slack.com/services/T/B/X").mock(
        return_value=Response(status_code=200, text="ok")
    )

    with patch.object(
        slack_dispatch_service,
        "_load_webhook_url",
        AsyncMock(return_value="https://hooks.slack.com/services/T/B/X"),
    ):
        await slack_dispatch_service.send(db=None, text_body="hi")  # type: ignore[arg-type]

    sent_body = json.loads(route.calls[0].request.content)
    assert "channel" not in sent_body

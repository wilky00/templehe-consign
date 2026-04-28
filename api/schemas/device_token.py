# ABOUTME: Phase 5 Sprint 1 — request/response shapes for /me/device-token.
# ABOUTME: Mobile clients POST here with their APNs token after authorizing for push.
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class DeviceTokenRegisterRequest(BaseModel):
    """POST /me/device-token body. ``platform`` and ``environment`` are
    enums today; widening the platform set requires a migration to
    update the CHECK constraint."""

    platform: Literal["ios", "android"]
    token: str = Field(min_length=1, max_length=4096)
    environment: Literal["development", "production"]


class DeviceTokenRevokeRequest(BaseModel):
    """DELETE /me/device-token body. Token-only — `user_id` is taken
    from the bearer token on the request, so cross-user revocation is
    impossible by construction."""

    token: str = Field(min_length=1, max_length=4096)


class DeviceTokenOut(BaseModel):
    """Single device-token row, as the SPA / iOS client sees it.

    The raw ``token`` is intentionally NOT echoed back — the client
    already has it, and a leak point through GET would defeat the
    "tokens identify devices" model. ``token_preview`` (last 8 chars)
    helps the client UI distinguish multiple device rows without
    exposing the full token."""

    id: uuid.UUID
    platform: str
    environment: str
    token_preview: str
    registered_at: datetime
    last_seen_at: datetime


class DeviceTokenListResponse(BaseModel):
    """GET /me/device-token response wrapper."""

    tokens: list[DeviceTokenOut]

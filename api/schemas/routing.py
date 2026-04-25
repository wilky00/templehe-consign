# ABOUTME: Phase 3 Sprint 3 — Pydantic shapes for the admin lead-routing-rules API.
# ABOUTME: rule_type-specific condition validation lives in the service; schemas keep the surface narrow.
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

RuleType = Literal["ad_hoc", "geographic", "round_robin"]


class RoutingRuleCreate(BaseModel):
    """Body for POST /admin/routing-rules."""

    rule_type: RuleType
    priority: int = Field(default=100, ge=0, le=10_000)
    conditions: dict | None = None
    assigned_user_id: uuid.UUID | None = None
    is_active: bool = True


class RoutingRulePatch(BaseModel):
    """Body for PATCH /admin/routing-rules/{id}.

    Every field is optional. Use ``model_fields_set`` to distinguish "absent"
    from "explicit null" — clears assigned_user_id when null is sent.
    """

    model_config = ConfigDict(extra="forbid")

    priority: int | None = Field(default=None, ge=0, le=10_000)
    conditions: dict | None = None
    assigned_user_id: uuid.UUID | None = None
    is_active: bool | None = None


class RoutingRuleOut(BaseModel):
    id: uuid.UUID
    rule_type: RuleType
    priority: int
    conditions: dict | None
    assigned_user_id: uuid.UUID | None
    round_robin_index: int
    is_active: bool
    created_by: uuid.UUID | None
    created_at: datetime
    deleted_at: datetime | None


class RoutingRuleListResponse(BaseModel):
    rules: list[RoutingRuleOut]
    total: int

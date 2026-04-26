# ABOUTME: Phase 3 Sprint 3 + Phase 4 Sprint 4 — admin lead-routing API shapes.
# ABOUTME: Discriminated-union per rule_type so OpenAPI exposes the variant structure.
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

RuleType = Literal["ad_hoc", "geographic", "round_robin"]


# --- Per-rule-type condition sub-models (Phase 4 Sprint 4) ---------------- #


class AdHocConditions(BaseModel):
    """Match on a specific customer or all customers from one email
    domain. ``condition_type`` is the discriminator inside the ad_hoc
    variant — ``customer_id`` matches a single customer.id; ``email_domain``
    matches every customer whose user's email ends with the domain."""

    model_config = ConfigDict(extra="forbid")

    condition_type: Literal["customer_id", "email_domain"]
    value: str = Field(min_length=1, max_length=255)


class MetroArea(BaseModel):
    """Lat/lng + radius_miles defining a geographic catchment area."""

    model_config = ConfigDict(extra="forbid")

    center_lat: float = Field(ge=-90, le=90)
    center_lon: float = Field(ge=-180, le=180)
    radius_miles: float = Field(gt=0, le=500)
    name: str | None = Field(default=None, max_length=100)


class GeographicConditions(BaseModel):
    """At least one of (state_list, zip_list, metro_area) is required.
    Multiple may be supplied; runtime treats them as OR'd."""

    model_config = ConfigDict(extra="forbid")

    state_list: list[str] | None = Field(default=None)
    zip_list: list[str] | None = Field(default=None)
    metro_area: MetroArea | None = Field(default=None)

    @model_validator(mode="after")
    def at_least_one_condition(self) -> GeographicConditions:
        if not self.state_list and not self.zip_list and self.metro_area is None:
            raise ValueError(
                "geographic rules need at least one of state_list, zip_list, or metro_area"
            )
        if self.state_list is not None:
            for s in self.state_list:
                if not isinstance(s, str) or len(s.strip()) != 2:
                    raise ValueError("state_list entries must be 2-letter USPS state codes")
        if self.zip_list is not None:
            for z in self.zip_list:
                if not isinstance(z, str) or not z.strip():
                    raise ValueError("zip_list entries must be non-empty strings")
        return self


class RoundRobinConditions(BaseModel):
    """``rep_ids`` is the rotation pool. Order matters — runtime steps
    through them via ``round_robin_index % len(rep_ids)``."""

    model_config = ConfigDict(extra="forbid")

    rep_ids: list[uuid.UUID] = Field(min_length=1)


# Convenience union for OpenAPI doc generation. Discriminator is the
# parent rule_type (lives on the LeadRoutingRule row), not on the
# conditions dict itself, so the union doesn't carry a Pydantic
# `Field(discriminator=...)` annotation. The parse_conditions helper
# below dispatches by rule_type explicitly.
RoutingRuleConditions = Annotated[
    AdHocConditions | GeographicConditions | RoundRobinConditions,
    Field(description="Per-rule-type conditions; shape is one of the variant models."),
]


def parse_conditions(rule_type: str, raw: dict | None) -> BaseModel:
    """Validate ``raw`` against the variant model for ``rule_type``.
    Raises ``ValueError`` (Pydantic ValidationError unwrapped) so the
    admin endpoint maps straight to 422 with the inline detail."""
    if rule_type == "ad_hoc":
        return AdHocConditions.model_validate(raw or {})
    if rule_type == "geographic":
        return GeographicConditions.model_validate(raw or {})
    if rule_type == "round_robin":
        return RoundRobinConditions.model_validate(raw or {})
    raise ValueError(f"unknown rule_type: {rule_type}")


# --- API shapes ---------------------------------------------------------- #


class RoutingRuleCreate(BaseModel):
    """Body for POST /admin/routing-rules.

    Conditions shape is governed by ``rule_type``; the service calls
    ``parse_conditions`` to enforce per-variant rules. Keeping the
    inbound conditions field as ``dict`` here avoids a Pydantic
    discriminated-union dance at the wire level — see ``parse_conditions``
    for the per-type validation.
    """

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


# --- Sprint 4: reorder + test-rule shapes -------------------------------- #


class RoutingRuleReorderRequest(BaseModel):
    """Body for POST /admin/routing-rules/reorder.

    ``ordered_ids`` MUST contain every active rule in the bucket — the
    service rejects partial lists with 422 to prevent leftover rules
    from inheriting a conflicting priority slot.
    """

    rule_type: RuleType
    ordered_ids: list[uuid.UUID] = Field(min_length=1)


class RoutingRuleReorderResponse(BaseModel):
    rules: list[RoutingRuleOut]


class RoutingRuleTestRequest(BaseModel):
    """Body for POST /admin/routing-rules/{id}/test. All fields optional;
    the service applies whichever ones the rule_type cares about."""

    customer_id: uuid.UUID | None = None
    customer_email: str | None = None
    customer_state: str | None = Field(default=None, max_length=2)
    customer_zip: str | None = Field(default=None, max_length=10)
    customer_lat: float | None = Field(default=None, ge=-90, le=90)
    customer_lng: float | None = Field(default=None, ge=-180, le=180)


class RoutingRuleTestResponse(BaseModel):
    rule_id: uuid.UUID
    rule_type: RuleType
    matched: bool
    would_assign_to: uuid.UUID | None
    reason: str

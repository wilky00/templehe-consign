# ABOUTME: Admin endpoints for lead routing rule CRUD — admin-only RBAC, soft delete.
# ABOUTME: Phase 4 ships the UI; Sprint 3 ships the API so admins can configure rules early.
from __future__ import annotations

import uuid

import structlog
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from database.base import get_db
from database.models import LeadRoutingRule, User
from middleware.rbac import require_roles
from schemas.routing import (
    RoutingRuleCreate,
    RoutingRuleListResponse,
    RoutingRuleOut,
    RoutingRulePatch,
)
from services import lead_routing_service

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/admin/routing-rules", tags=["admin-routing"])

_require_admin = require_roles("admin")


def _to_out(rule: LeadRoutingRule) -> RoutingRuleOut:
    return RoutingRuleOut(
        id=rule.id,
        rule_type=rule.rule_type,  # type: ignore[arg-type]
        priority=rule.priority,
        conditions=rule.conditions,
        assigned_user_id=rule.assigned_user_id,
        round_robin_index=rule.round_robin_index,
        is_active=rule.is_active,
        created_by=rule.created_by,
        created_at=rule.created_at,
        deleted_at=rule.deleted_at,
    )


@router.get("", response_model=RoutingRuleListResponse)
async def list_rules(
    include_deleted: bool = Query(default=False),
    _admin: User = Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
) -> RoutingRuleListResponse:
    rules = await lead_routing_service.list_rules(db, include_deleted=include_deleted)
    return RoutingRuleListResponse(
        rules=[_to_out(r) for r in rules],
        total=len(rules),
    )


@router.post("", response_model=RoutingRuleOut, status_code=201)
async def create_rule(
    body: RoutingRuleCreate,
    admin: User = Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
) -> RoutingRuleOut:
    rule = await lead_routing_service.create_rule(
        db,
        creator=admin,
        rule_type=body.rule_type,
        priority=body.priority,
        conditions=body.conditions,
        assigned_user_id=body.assigned_user_id,
        is_active=body.is_active,
    )
    return _to_out(rule)


@router.patch("/{rule_id}", response_model=RoutingRuleOut)
async def update_rule(
    rule_id: uuid.UUID,
    body: RoutingRulePatch,
    _admin: User = Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
) -> RoutingRuleOut:
    rule = await lead_routing_service.update_rule(
        db,
        rule_id=rule_id,
        set_priority="priority" in body.model_fields_set,
        priority=body.priority,
        set_conditions="conditions" in body.model_fields_set,
        conditions=body.conditions,
        set_assigned_user="assigned_user_id" in body.model_fields_set,
        assigned_user_id=body.assigned_user_id,
        set_is_active="is_active" in body.model_fields_set,
        is_active=body.is_active,
    )
    return _to_out(rule)


@router.delete("/{rule_id}", response_model=RoutingRuleOut)
async def delete_rule(
    rule_id: uuid.UUID,
    _admin: User = Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
) -> RoutingRuleOut:
    rule = await lead_routing_service.soft_delete_rule(db, rule_id=rule_id)
    return _to_out(rule)

# ABOUTME: Phase 3 Sprint 3 — lead routing waterfall: ad_hoc → geographic → round_robin → fallback.
# ABOUTME: Pure routing decision; caller owns the assignment, audit, and notification side effects.
"""Lead routing engine.

The waterfall (spec Feature 3.3.2):

1. **Ad hoc rules** (highest precedence) — match the customer by id or
   email domain. First match wins.
2. **Geographic rules** in ascending ``priority`` order — match on
   state list, ZIP exact, or ZIP range. First match wins. Metro-area
   matching is deferred to Sprint 4 (needs Google geocoding from
   Epic 3.4 calendar work).
3. **Round-robin rule** (catch-all) — the lowest-priority rule with
   ``rule_type='round_robin'`` and a ``rep_ids`` list in conditions.
   Rotates with an atomic ``UPDATE ... RETURNING round_robin_index``
   under row lock so concurrent intakes don't double-assign or skip.
4. **AppConfig fallback** — if no rule matched, read
   ``default_sales_rep_id`` from ``app_config``. If unset, leave
   the record unassigned and let the manager triage.

ADR-013 addendum: the round-robin counter uses a Postgres row lock
(``UPDATE ... RETURNING round_robin_index``) rather than Redis ``INCR``
for the POC. Same atomicity, no extra runtime dep. Swap to Redis at
GCP migration time without touching the public service signature.

Public surface (callers depend only on these):

- ``route_for_record(db, *, record, customer)`` →
  ``RoutingDecision`` dataclass with ``assigned_user_id`` (UUID | None),
  ``rule_id`` (UUID | None), ``rule_type`` (str | None), ``trigger``
  (``"lead_routing"`` | ``"default_sales_rep"`` | ``"unassigned"``).

- Admin CRUD helpers: ``list_rules``, ``get_rule``, ``create_rule``,
  ``update_rule``, ``soft_delete_rule``.
"""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

import structlog
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import and_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import (
    Customer,
    EquipmentRecord,
    LeadRoutingRule,
    Role,
    User,
)
from schemas.routing import parse_conditions
from services import app_config_registry, google_maps_service

logger = structlog.get_logger(__name__)

_ALLOWED_RULE_TYPES = frozenset({"ad_hoc", "geographic", "round_robin"})


@dataclass(frozen=True)
class RoutingDecision:
    """Outcome of a single routing pass.

    - ``assigned_user_id``: who to set on the record. None means "leave unassigned".
    - ``rule_id``/``rule_type``: which rule fired (None for fallback or unassigned).
    - ``trigger``: audit-event tag — ``lead_routing``, ``default_sales_rep``, or
      ``unassigned``.
    """

    assigned_user_id: uuid.UUID | None
    rule_id: uuid.UUID | None
    rule_type: str | None
    trigger: str


# --------------------------------------------------------------------------- #
# Waterfall
# --------------------------------------------------------------------------- #


async def route_for_record(
    db: AsyncSession,
    *,
    record: EquipmentRecord,
    customer: Customer,
) -> RoutingDecision:
    """Run the full waterfall for one record.

    Caller is responsible for:
    - applying the returned ``assigned_user_id`` to ``record.assigned_sales_rep_id``
    - writing the audit event (event_type='equipment_record.routed', after_state
      includes rule_id + rule_type + trigger)
    - enqueueing the assigned-rep notification

    Never raises on "no rule matched" — returns ``trigger='unassigned'`` instead.
    """
    customer_email = customer.user.email if customer.user is not None else None

    # Pull active, non-deleted rules ordered by type bucket and priority.
    rules = await _load_active_rules(db)

    # 1. Ad hoc — first match by customer_id or email_domain.
    for rule in (r for r in rules if r.rule_type == "ad_hoc"):
        if _ad_hoc_matches(rule, customer_id=customer.id, customer_email=customer_email):
            if rule.assigned_user_id is not None:
                return RoutingDecision(
                    assigned_user_id=rule.assigned_user_id,
                    rule_id=rule.id,
                    rule_type="ad_hoc",
                    trigger="lead_routing",
                )

    # 2. Geographic — ascending priority.
    geo_rules = sorted(
        (r for r in rules if r.rule_type == "geographic"),
        key=lambda r: r.priority,
    )
    for rule in geo_rules:
        matched = _geo_matches(rule, state=customer.address_state, zip_code=customer.address_zip)
        if not matched:
            matched = await _metro_matches(db, rule, customer=customer)
        if matched and rule.assigned_user_id is not None:
            return RoutingDecision(
                assigned_user_id=rule.assigned_user_id,
                rule_id=rule.id,
                rule_type="geographic",
                trigger="lead_routing",
            )

    # 3. Round robin — pick the lowest-priority active RR rule.
    rr_rules = sorted(
        (r for r in rules if r.rule_type == "round_robin"),
        key=lambda r: r.priority,
    )
    for rule in rr_rules:
        rep_ids = _round_robin_rep_ids(rule)
        if not rep_ids:
            continue
        next_user_id = await _claim_next_round_robin(db, rule_id=rule.id, rep_ids=rep_ids)
        if next_user_id is not None:
            return RoutingDecision(
                assigned_user_id=next_user_id,
                rule_id=rule.id,
                rule_type="round_robin",
                trigger="lead_routing",
            )

    # 4. AppConfig fallback.
    default_rep_id = await _read_default_sales_rep(db)
    if default_rep_id is not None:
        return RoutingDecision(
            assigned_user_id=default_rep_id,
            rule_id=None,
            rule_type=None,
            trigger="default_sales_rep",
        )

    return RoutingDecision(
        assigned_user_id=None,
        rule_id=None,
        rule_type=None,
        trigger="unassigned",
    )


async def _load_active_rules(db: AsyncSession) -> list[LeadRoutingRule]:
    stmt = select(LeadRoutingRule).where(
        and_(
            LeadRoutingRule.deleted_at.is_(None),
            LeadRoutingRule.is_active.is_(True),
        )
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


# --------------------------------------------------------------------------- #
# Matchers
# --------------------------------------------------------------------------- #


def _ad_hoc_matches(
    rule: LeadRoutingRule,
    *,
    customer_id: uuid.UUID,
    customer_email: str | None,
) -> bool:
    """Ad-hoc rule shape:
    {"condition_type": "customer_id", "value": "<uuid>"}
    {"condition_type": "email_domain", "value": "@acme.com"}
    """
    cond = rule.conditions or {}
    ctype = cond.get("condition_type")
    value = cond.get("value")
    if not ctype or not value:
        return False
    if ctype == "customer_id":
        try:
            return uuid.UUID(str(value)) == customer_id
        except (ValueError, TypeError):
            return False
    if ctype == "email_domain":
        if not customer_email:
            return False
        domain = str(value).strip().lower()
        if not domain.startswith("@"):
            domain = "@" + domain
        return customer_email.lower().endswith(domain)
    return False


def _geo_matches(
    rule: LeadRoutingRule,
    *,
    state: str | None,
    zip_code: str | None,
) -> bool:
    """Geographic rule shape:
        {
          "state_list": ["CA", "OR"],
          "zip_list": ["90210", "30301-30399"]
        }

    Metro-area matching is deferred — silently skipped if present.
    """
    cond = rule.conditions or {}
    state_list = cond.get("state_list")
    if state and isinstance(state_list, list):
        norm_state = state.strip().upper()
        for s in state_list:
            if isinstance(s, str) and s.strip().upper() == norm_state:
                return True

    zip_list = cond.get("zip_list")
    if zip_code and isinstance(zip_list, list):
        norm_zip = _normalize_zip(zip_code)
        if norm_zip is not None:
            for entry in zip_list:
                if isinstance(entry, str) and _zip_entry_matches(entry, norm_zip):
                    return True
    return False


async def _metro_matches(
    db: AsyncSession,
    rule: LeadRoutingRule,
    *,
    customer: Customer,
) -> bool:
    """Metro-area rule shape (Sprint 4):
        {"metro_area": {"center_lat": 33.7, "center_lon": -84.4, "radius_miles": 50}}

    Geocodes the customer's address via google_maps_service (cache-first,
    silent fallback when no API key) and compares the haversine distance
    against the metro radius. Returns False if any input is missing or
    the geocode fails — never raises so a flaky geocoder can't drop a
    customer's intake.
    """
    cond = rule.conditions or {}
    metro = cond.get("metro_area")
    if not isinstance(metro, dict):
        return False
    try:
        center_lat = float(metro["center_lat"])
        center_lon = float(metro["center_lon"])
        radius_miles = float(metro["radius_miles"])
    except (KeyError, TypeError, ValueError):
        return False
    if radius_miles <= 0:
        return False

    address = _format_customer_address(customer)
    if not address:
        return False
    coords = await google_maps_service.geocode(db, address=address)
    if coords is None:
        return False
    customer_lat, customer_lon = coords
    distance_miles = _haversine_miles(center_lat, center_lon, customer_lat, customer_lon)
    return distance_miles <= radius_miles


def _format_customer_address(customer: Customer) -> str | None:
    """Build a single-string address suitable for the Google Geocoding API.

    Returns None when there's nothing useful to geocode.
    """
    parts = [
        customer.address_street,
        customer.address_city,
        customer.address_state,
        customer.address_zip,
    ]
    cleaned = [p.strip() for p in parts if isinstance(p, str) and p.strip()]
    if not cleaned:
        return None
    return ", ".join(cleaned)


def _haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in statute miles."""
    earth_radius_miles = 3958.7613
    rlat1, rlat2 = math.radians(lat1), math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(rlat1) * math.cos(rlat2) * math.sin(dlon / 2) ** 2
    c = 2 * math.asin(math.sqrt(a))
    return earth_radius_miles * c


def _normalize_zip(raw: str) -> int | None:
    """Strip ZIP+4, return integer for range comparison. None if not a US ZIP."""
    head = raw.split("-")[0].strip()
    if len(head) < 5 or not head[:5].isdigit():
        return None
    return int(head[:5])


def _zip_entry_matches(entry: str, customer_zip: int) -> bool:
    """``entry`` is either an exact "90210" or a range "30301-30399"."""
    cleaned = entry.strip()
    if "-" in cleaned:
        parts = cleaned.split("-", 1)
        if len(parts) != 2:
            return False
        lo, hi = parts[0].strip(), parts[1].strip()
        if not (lo.isdigit() and hi.isdigit()):
            return False
        return int(lo) <= customer_zip <= int(hi)
    if cleaned.isdigit():
        return int(cleaned) == customer_zip
    return False


def _round_robin_rep_ids(rule: LeadRoutingRule) -> list[uuid.UUID]:
    """Round-robin rule shape: {"rep_ids": ["<uuid>", "<uuid>", ...]}."""
    cond = rule.conditions or {}
    raw = cond.get("rep_ids")
    if not isinstance(raw, list):
        return []
    out: list[uuid.UUID] = []
    for item in raw:
        try:
            out.append(uuid.UUID(str(item)))
        except (ValueError, TypeError):
            continue
    return out


async def _claim_next_round_robin(
    db: AsyncSession,
    *,
    rule_id: uuid.UUID,
    rep_ids: list[uuid.UUID],
) -> uuid.UUID | None:
    """Atomic increment + pick the next rep.

    Postgres ``UPDATE ... RETURNING`` is atomic on a single row; concurrent
    intake submissions will serialize on the row lock and each see a
    distinct counter value. Same semantics as Redis ``INCR``.
    """
    if not rep_ids:
        return None
    result = await db.execute(
        text(
            """
            UPDATE lead_routing_rules
            SET round_robin_index = round_robin_index + 1
            WHERE id = :rule_id
            RETURNING round_robin_index
            """
        ),
        {"rule_id": rule_id},
    )
    next_index = result.scalar_one_or_none()
    if next_index is None:
        return None
    # Cycle through the list; the +1 above means the first call returns 1, so
    # subtract 1 to land on rep_ids[0] for the first intake after a fresh rule.
    return rep_ids[(next_index - 1) % len(rep_ids)]


async def _read_default_sales_rep(db: AsyncSession) -> uuid.UUID | None:
    """Resolve the AppConfig fallback rep. Registry returns the raw
    UUID string; coerce here so callers downstream stay typed."""
    raw = await app_config_registry.get_typed(db, app_config_registry.DEFAULT_SALES_REP_ID.name)
    if not raw:
        return None
    try:
        return uuid.UUID(str(raw))
    except (ValueError, TypeError):
        return None


# --------------------------------------------------------------------------- #
# Admin CRUD helpers
# --------------------------------------------------------------------------- #


async def list_rules(
    db: AsyncSession,
    *,
    include_deleted: bool = False,
) -> list[LeadRoutingRule]:
    stmt = select(LeadRoutingRule)
    if not include_deleted:
        stmt = stmt.where(LeadRoutingRule.deleted_at.is_(None))
    stmt = stmt.order_by(LeadRoutingRule.rule_type.asc(), LeadRoutingRule.priority.asc())
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_rule(db: AsyncSession, rule_id: uuid.UUID) -> LeadRoutingRule:
    result = await db.execute(select(LeadRoutingRule).where(LeadRoutingRule.id == rule_id))
    rule = result.scalar_one_or_none()
    if rule is None or rule.deleted_at is not None:
        raise HTTPException(status_code=404, detail="routing rule not found")
    return rule


async def create_rule(
    db: AsyncSession,
    *,
    creator: User,
    rule_type: str,
    priority: int,
    conditions: dict | None,
    assigned_user_id: uuid.UUID | None,
    is_active: bool,
) -> LeadRoutingRule:
    if rule_type not in _ALLOWED_RULE_TYPES:
        raise HTTPException(
            status_code=422,
            detail=f"rule_type must be one of: {sorted(_ALLOWED_RULE_TYPES)}",
        )
    _validate_conditions(rule_type, conditions)
    if assigned_user_id is not None:
        await _require_sales_role(db, assigned_user_id)
    # Sprint 4: pre-check the unique (rule_type, priority) slot so we
    # return a clean 409 instead of bubbling the IntegrityError. The
    # partial UNIQUE INDEX is the source of truth; this just gives the
    # admin a useful error message + avoids leaving the session in a
    # broken state mid-request.
    await _check_priority_slot_free(db, rule_type=rule_type, priority=priority)

    rule = LeadRoutingRule(
        rule_type=rule_type,
        priority=priority,
        conditions=conditions,
        assigned_user_id=assigned_user_id,
        round_robin_index=0,
        is_active=is_active,
        created_by=creator.id,
    )
    db.add(rule)
    await db.flush()
    return rule


async def _check_priority_slot_free(
    db: AsyncSession,
    *,
    rule_type: str,
    priority: int,
    excluding_rule_id: uuid.UUID | None = None,
) -> None:
    stmt = select(LeadRoutingRule.id).where(
        and_(
            LeadRoutingRule.rule_type == rule_type,
            LeadRoutingRule.priority == priority,
            LeadRoutingRule.deleted_at.is_(None),
        )
    )
    if excluding_rule_id is not None:
        stmt = stmt.where(LeadRoutingRule.id != excluding_rule_id)
    if (await db.execute(stmt)).scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=409,
            detail=(
                f"priority {priority} is already taken in the {rule_type} bucket; "
                "use the reorder endpoint to renumber"
            ),
        )


async def update_rule(
    db: AsyncSession,
    *,
    rule_id: uuid.UUID,
    set_priority: bool,
    priority: int | None,
    set_conditions: bool,
    conditions: dict | None,
    set_assigned_user: bool,
    assigned_user_id: uuid.UUID | None,
    set_is_active: bool,
    is_active: bool | None,
) -> LeadRoutingRule:
    rule = await get_rule(db, rule_id)
    if set_priority and priority is not None:
        if priority != rule.priority:
            await _check_priority_slot_free(
                db,
                rule_type=rule.rule_type,
                priority=priority,
                excluding_rule_id=rule.id,
            )
        rule.priority = priority
    if set_conditions:
        _validate_conditions(rule.rule_type, conditions)
        rule.conditions = conditions
    if set_assigned_user:
        if assigned_user_id is not None:
            await _require_sales_role(db, assigned_user_id)
        rule.assigned_user_id = assigned_user_id
    if set_is_active and is_active is not None:
        rule.is_active = is_active
    db.add(rule)
    await db.flush()
    return rule


async def soft_delete_rule(db: AsyncSession, rule_id: uuid.UUID) -> LeadRoutingRule:
    rule = await get_rule(db, rule_id)
    rule.deleted_at = datetime.now(UTC)
    rule.is_active = False
    db.add(rule)
    await db.flush()
    return rule


def _validate_conditions(rule_type: str, conditions: dict | None) -> None:
    """Phase 4 Sprint 4 — delegates to the Pydantic variant models in
    ``schemas.routing.parse_conditions`` so the service layer + the
    OpenAPI surface enforce identical shape checks. Pydantic
    ``ValidationError`` (with field names like ``rep_ids``,
    ``metro_area.radius_miles``, etc) maps straight to a 422 detail."""
    try:
        parse_conditions(rule_type, conditions)
    except (ValidationError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


async def _require_sales_role(db: AsyncSession, user_id: uuid.UUID) -> None:
    result = await db.execute(
        select(User, Role.slug).join(Role, Role.id == User.role_id).where(User.id == user_id)
    )
    row = result.first()
    if row is None:
        raise HTTPException(status_code=422, detail=f"user {user_id} not found")
    _, slug = row
    if slug not in ("sales", "sales_manager", "admin"):
        raise HTTPException(
            status_code=422,
            detail=f"user {user_id} has role '{slug}', expected sales/sales_manager/admin",
        )


# --------------------------------------------------------------------------- #
# Phase 4 Sprint 4 — atomic priority reorder + test-rule.
# --------------------------------------------------------------------------- #


async def reorder_priorities(
    db: AsyncSession,
    *,
    rule_type: str,
    ordered_ids: list[uuid.UUID],
) -> list[LeadRoutingRule]:
    """Atomically renumber all active rules in a ``rule_type`` bucket so
    priorities match ``ordered_ids`` (index 0 → priority 0, index 1 → 1,
    ...). Two-phase under one transaction:

    1. Lock every affected row with ``SELECT ... FOR UPDATE``.
    2. Shift each to a negative scratch priority (``-1 - target_index``)
       so we never violate the partial UNIQUE index mid-renumber.
    3. Shift each scratch row to its final positive target.

    Caller must pass *every* active rule in the bucket; missing ids are
    rejected as 422 (otherwise an unmentioned rule could end up with a
    duplicate priority once everyone else moves).
    """
    if rule_type not in _ALLOWED_RULE_TYPES:
        raise HTTPException(
            status_code=422,
            detail=f"rule_type must be one of: {sorted(_ALLOWED_RULE_TYPES)}",
        )
    if not ordered_ids:
        return []
    if len(set(ordered_ids)) != len(ordered_ids):
        raise HTTPException(status_code=422, detail="ordered_ids contains duplicates")

    # Lock every active rule in this bucket so concurrent admin edits
    # block, and we have the full set to validate against.
    locked_stmt = (
        select(LeadRoutingRule)
        .where(
            and_(
                LeadRoutingRule.rule_type == rule_type,
                LeadRoutingRule.deleted_at.is_(None),
            )
        )
        .with_for_update()
    )
    locked = list((await db.execute(locked_stmt)).scalars().all())
    locked_ids = {r.id for r in locked}
    requested_ids = set(ordered_ids)
    if locked_ids != requested_ids:
        missing = locked_ids - requested_ids
        unknown = requested_ids - locked_ids
        raise HTTPException(
            status_code=422,
            detail=(
                "ordered_ids does not match the set of active rules in this bucket "
                f"(missing: {sorted(str(i) for i in missing)}, "
                f"unknown: {sorted(str(i) for i in unknown)})"
            ),
        )
    rules_by_id = {r.id: r for r in locked}

    # Phase 1: scratch-space negatives. Each row's scratch priority is
    # unique (-1, -2, -3, ...) so the partial UNIQUE index is honored.
    for idx, rule_id in enumerate(ordered_ids):
        rule = rules_by_id[rule_id]
        rule.priority = -1 - idx
        db.add(rule)
    await db.flush()

    # Phase 2: final positive priorities matching the requested order.
    for idx, rule_id in enumerate(ordered_ids):
        rule = rules_by_id[rule_id]
        rule.priority = idx
        db.add(rule)
    await db.flush()

    return [rules_by_id[rid] for rid in ordered_ids]


@dataclass(frozen=True)
class TestRuleResult:
    """Outcome of a synthetic test against one routing rule. ``matched``
    is True when the rule's conditions evaluate True for the synthetic
    input; ``would_assign_to`` mirrors the runtime behavior — the
    rule's static ``assigned_user_id`` for ad_hoc/geographic, or the
    *next* round-robin rep without actually claiming it."""

    rule_id: uuid.UUID
    rule_type: str
    matched: bool
    would_assign_to: uuid.UUID | None
    reason: str


async def test_rule(
    db: AsyncSession,
    *,
    rule_id: uuid.UUID,
    customer_id: uuid.UUID | None = None,
    customer_email: str | None = None,
    customer_state: str | None = None,
    customer_zip: str | None = None,
    customer_lat: float | None = None,
    customer_lng: float | None = None,
) -> TestRuleResult:
    """Read-only "would this rule match this customer?" check. Mirrors
    the runtime match logic from ``route_for_record`` but never writes
    (no round_robin_index increment, no audit log, no assignment).
    Phase 4 admin uses this to debug routing rules before activating."""
    rule = await get_rule(db, rule_id)

    if rule.rule_type == "ad_hoc":
        matched = _ad_hoc_matches(rule, customer_id=customer_id, customer_email=customer_email)
        return TestRuleResult(
            rule_id=rule.id,
            rule_type=rule.rule_type,
            matched=matched,
            would_assign_to=rule.assigned_user_id if matched else None,
            reason=(
                "ad_hoc matched on the supplied customer_id/email_domain"
                if matched
                else "ad_hoc conditions did not match the supplied input"
            ),
        )

    if rule.rule_type == "geographic":
        matched_state_zip = _geo_matches(rule, state=customer_state, zip_code=customer_zip)
        matched_metro = False
        if not matched_state_zip and customer_lat is not None and customer_lng is not None:
            matched_metro = _metro_matches_synthetic(rule, lat=customer_lat, lng=customer_lng)
        matched = matched_state_zip or matched_metro
        reason_parts = []
        if matched_state_zip:
            reason_parts.append("state/zip matched")
        if matched_metro:
            reason_parts.append("metro radius matched")
        if not matched:
            reason_parts.append("no condition matched the supplied input")
        return TestRuleResult(
            rule_id=rule.id,
            rule_type=rule.rule_type,
            matched=matched,
            would_assign_to=rule.assigned_user_id if matched else None,
            reason="; ".join(reason_parts),
        )

    # round_robin: the rule "matches" any input — its real selection is
    # which rep is next. Report the next rep without claiming.
    rep_ids = _round_robin_rep_ids(rule)
    if not rep_ids:
        return TestRuleResult(
            rule_id=rule.id,
            rule_type=rule.rule_type,
            matched=False,
            would_assign_to=None,
            reason="round_robin rule has no eligible reps",
        )
    next_idx = rule.round_robin_index % len(rep_ids)
    return TestRuleResult(
        rule_id=rule.id,
        rule_type=rule.rule_type,
        matched=True,
        would_assign_to=rep_ids[next_idx],
        reason=f"round_robin would pick rep at index {next_idx} (no claim)",
    )


def _metro_matches_synthetic(rule: LeadRoutingRule, *, lat: float, lng: float) -> bool:
    """Synchronous metro-area check for the test-rule path. The runtime
    ``_metro_matches`` geocodes the customer's address; here the caller
    has already supplied lat/lng so we skip the geocode step + the cache
    write."""
    metro = (rule.conditions or {}).get("metro_area")
    if not isinstance(metro, dict):
        return False
    try:
        center_lat = float(metro["center_lat"])
        center_lng = float(metro["center_lon"])
        radius = float(metro["radius_miles"])
    except (KeyError, TypeError, ValueError):
        return False
    return _haversine_miles(lat, lng, center_lat, center_lng) <= radius

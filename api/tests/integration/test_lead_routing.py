# ABOUTME: Phase 3 Sprint 3 — full waterfall test: ad_hoc → geographic → round_robin → AppConfig fallback.
# ABOUTME: Drives routing through the real intake endpoint and inspects record + audit + notification side effects.
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import (
    AppConfig,
    AuditLog,
    Customer,
    EquipmentRecord,
    LeadRoutingRule,
    NotificationJob,
    Role,
    User,
)

_VALID_PASSWORD = "TestPassword1!"


async def _user_with_role(
    client: AsyncClient, db: AsyncSession, email: str, role_slug: str
) -> dict:
    with patch("services.email_service.send_email", new_callable=AsyncMock):
        reg = await client.post(
            "/api/v1/auth/register",
            json={
                "email": email,
                "password": _VALID_PASSWORD,
                "first_name": "T",
                "last_name": "U",
                "tos_version": "1",
                "privacy_version": "1",
            },
        )
    assert reg.status_code == 201, reg.json()
    user = (await db.execute(select(User).where(User.email == email.lower()))).scalar_one()
    role = (await db.execute(select(Role).where(Role.slug == role_slug))).scalar_one()
    user.status = "active"
    user.role_id = role.id
    await db.flush()
    with patch("services.email_service.send_email", new_callable=AsyncMock):
        login = await client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": _VALID_PASSWORD},
        )
    body = login.json()
    body["user_id"] = str(user.id)
    return body


async def _activated_customer(
    client: AsyncClient,
    db: AsyncSession,
    email: str,
    *,
    state: str | None = None,
    zip_code: str | None = None,
) -> dict:
    """Register a customer, activate them, optionally set address fields, return tokens + ids."""
    with patch("services.email_service.send_email", new_callable=AsyncMock):
        reg = await client.post(
            "/api/v1/auth/register",
            json={
                "email": email,
                "password": _VALID_PASSWORD,
                "first_name": "C",
                "last_name": "U",
                "tos_version": "1",
                "privacy_version": "1",
            },
        )
    assert reg.status_code == 201, reg.json()
    user = (await db.execute(select(User).where(User.email == email.lower()))).scalar_one()
    user.status = "active"
    await db.flush()

    with patch("services.email_service.send_email", new_callable=AsyncMock):
        login = await client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": _VALID_PASSWORD},
        )
    tok = login.json()["access_token"]

    if state is not None or zip_code is not None:
        # Profile is created lazily on intake; pre-create here so we can set
        # address_state / address_zip the routing engine reads.
        customer = Customer(
            user_id=user.id,
            submitter_name=f"{user.first_name} {user.last_name}".strip(),
            address_state=state,
            address_zip=zip_code,
        )
        db.add(customer)
        await db.flush()

    return {"user_id": str(user.id), "email": user.email, "access_token": tok}


def _auth(tok: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {tok}"}


async def _intake(client: AsyncClient, tok: str) -> uuid.UUID:
    resp = await client.post(
        "/api/v1/me/equipment",
        json={"photos": []},
        headers=_auth(tok),
    )
    assert resp.status_code == 201, resp.json()
    return uuid.UUID(resp.json()["id"])


async def _routing_audit_for(db: AsyncSession, record_id: uuid.UUID) -> AuditLog:
    rows = (
        await db.execute(
            select(AuditLog).where(AuditLog.event_type == "equipment_record.routed")
        )
    ).scalars().all()
    match = next((a for a in rows if a.target_id == record_id), None)
    assert match is not None, f"no routing audit row for record {record_id}"
    return match


# --- ad-hoc routing --------------------------------------------------------- #


@pytest.mark.asyncio
async def test_ad_hoc_customer_id_match_assigns_rep(
    client: AsyncClient, db_session: AsyncSession
):
    rep = await _user_with_role(client, db_session, "lr_adhoc_rep@example.com", "sales")
    cust = await _activated_customer(client, db_session, "lr_adhoc_c@example.com")

    customer_row = (
        await db_session.execute(
            select(Customer).where(Customer.user_id == uuid.UUID(cust["user_id"]))
        )
    ).scalar_one_or_none()
    # The customer profile only exists if the test pre-created it (state/zip path).
    # For ad_hoc by customer_id we need an explicit customer to build the rule against,
    # so create the profile up-front.
    if customer_row is None:
        customer_row = Customer(
            user_id=uuid.UUID(cust["user_id"]),
            submitter_name="C U",
        )
        db_session.add(customer_row)
        await db_session.flush()

    rule = LeadRoutingRule(
        rule_type="ad_hoc",
        priority=10,
        conditions={"condition_type": "customer_id", "value": str(customer_row.id)},
        assigned_user_id=uuid.UUID(rep["user_id"]),
        is_active=True,
    )
    db_session.add(rule)
    await db_session.flush()

    rec_id = await _intake(client, cust["access_token"])

    record = (
        await db_session.execute(select(EquipmentRecord).where(EquipmentRecord.id == rec_id))
    ).scalar_one()
    assert record.assigned_sales_rep_id == uuid.UUID(rep["user_id"])

    audit = await _routing_audit_for(db_session, rec_id)
    assert audit.after_state["trigger"] == "lead_routing"
    assert audit.after_state["rule_type"] == "ad_hoc"
    assert audit.after_state["rule_id"] == str(rule.id)
    assert audit.after_state["assigned_sales_rep_id"] == rep["user_id"]

    notifs = (
        await db_session.execute(
            select(NotificationJob).where(NotificationJob.template == "record_assigned")
        )
    ).scalars().all()
    assert any(str(rec_id) in n.idempotency_key for n in notifs)


@pytest.mark.asyncio
async def test_ad_hoc_email_domain_match_assigns_rep(
    client: AsyncClient, db_session: AsyncSession
):
    rep = await _user_with_role(client, db_session, "lr_em_rep@example.com", "sales")
    cust = await _activated_customer(client, db_session, "buyer@acme.example")

    rule = LeadRoutingRule(
        rule_type="ad_hoc",
        priority=20,
        conditions={"condition_type": "email_domain", "value": "acme.example"},
        assigned_user_id=uuid.UUID(rep["user_id"]),
        is_active=True,
    )
    db_session.add(rule)
    await db_session.flush()

    rec_id = await _intake(client, cust["access_token"])

    record = (
        await db_session.execute(select(EquipmentRecord).where(EquipmentRecord.id == rec_id))
    ).scalar_one()
    assert record.assigned_sales_rep_id == uuid.UUID(rep["user_id"])


# --- geographic ------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_geographic_state_match_assigns_rep(
    client: AsyncClient, db_session: AsyncSession
):
    rep = await _user_with_role(client, db_session, "lr_state_rep@example.com", "sales")
    cust = await _activated_customer(
        client, db_session, "lr_state_c@example.com", state="CA"
    )

    rule = LeadRoutingRule(
        rule_type="geographic",
        priority=50,
        conditions={"state_list": ["CA", "OR", "WA"]},
        assigned_user_id=uuid.UUID(rep["user_id"]),
        is_active=True,
    )
    db_session.add(rule)
    await db_session.flush()

    rec_id = await _intake(client, cust["access_token"])

    record = (
        await db_session.execute(select(EquipmentRecord).where(EquipmentRecord.id == rec_id))
    ).scalar_one()
    assert record.assigned_sales_rep_id == uuid.UUID(rep["user_id"])

    audit = await _routing_audit_for(db_session, rec_id)
    assert audit.after_state["rule_type"] == "geographic"


@pytest.mark.asyncio
async def test_geographic_zip_range_match_assigns_rep(
    client: AsyncClient, db_session: AsyncSession
):
    rep = await _user_with_role(client, db_session, "lr_zip_rep@example.com", "sales")
    cust = await _activated_customer(
        client, db_session, "lr_zip_c@example.com", zip_code="30350"
    )

    rule = LeadRoutingRule(
        rule_type="geographic",
        priority=50,
        conditions={"zip_list": ["30301-30399"]},
        assigned_user_id=uuid.UUID(rep["user_id"]),
        is_active=True,
    )
    db_session.add(rule)
    await db_session.flush()

    rec_id = await _intake(client, cust["access_token"])

    record = (
        await db_session.execute(select(EquipmentRecord).where(EquipmentRecord.id == rec_id))
    ).scalar_one()
    assert record.assigned_sales_rep_id == uuid.UUID(rep["user_id"])


@pytest.mark.asyncio
async def test_geographic_metro_area_match_assigns_rep(
    client: AsyncClient, db_session: AsyncSession
):
    """Metro-area routing geocodes the customer's address (mocked) and
    matches when the haversine distance is within ``radius_miles``."""
    from unittest.mock import AsyncMock, patch as _patch

    from database.models import Customer

    rep = await _user_with_role(client, db_session, "lr_metro_rep@example.com", "sales")
    cust = await _activated_customer(
        client, db_session, "lr_metro_c@example.com"
    )

    # Pre-create profile with a usable address.
    customer = (
        await db_session.execute(
            select(Customer).where(Customer.user_id == uuid.UUID(cust["user_id"]))
        )
    ).scalar_one_or_none()
    if customer is None:
        customer = Customer(
            user_id=uuid.UUID(cust["user_id"]),
            submitter_name="C U",
            address_street="123 Peachtree St",
            address_city="Atlanta",
            address_state="GA",
            address_zip="30303",
        )
        db_session.add(customer)
    else:
        customer.address_street = "123 Peachtree St"
        customer.address_city = "Atlanta"
        customer.address_state = "GA"
        customer.address_zip = "30303"
    await db_session.flush()

    rule = LeadRoutingRule(
        rule_type="geographic",
        priority=50,
        conditions={
            "metro_area": {
                "center_lat": 33.7490,
                "center_lon": -84.3880,
                "radius_miles": 25,
            }
        },
        assigned_user_id=uuid.UUID(rep["user_id"]),
        is_active=True,
    )
    db_session.add(rule)
    await db_session.flush()

    # Customer is 5 miles from Atlanta center per the mocked geocoder.
    with _patch(
        "services.google_maps_service.geocode",
        new_callable=AsyncMock,
        return_value=(33.78, -84.40),
    ):
        rec_id = await _intake(client, cust["access_token"])

    record = (
        await db_session.execute(select(EquipmentRecord).where(EquipmentRecord.id == rec_id))
    ).scalar_one()
    assert record.assigned_sales_rep_id == uuid.UUID(rep["user_id"])


@pytest.mark.asyncio
async def test_geographic_metro_area_skips_when_outside_radius(
    client: AsyncClient, db_session: AsyncSession
):
    from unittest.mock import AsyncMock, patch as _patch

    from database.models import Customer

    rep = await _user_with_role(client, db_session, "lr_metro_far_rep@example.com", "sales")
    cust = await _activated_customer(
        client, db_session, "lr_metro_far_c@example.com"
    )
    customer = Customer(
        user_id=uuid.UUID(cust["user_id"]),
        submitter_name="C U",
        address_street="1 Far Out Rd",
        address_city="Boise",
        address_state="ID",
        address_zip="83702",
    )
    db_session.add(customer)
    await db_session.flush()

    db_session.add(
        LeadRoutingRule(
            rule_type="geographic",
            priority=50,
            conditions={
                "metro_area": {
                    "center_lat": 33.7490,
                    "center_lon": -84.3880,
                    "radius_miles": 25,
                }
            },
            assigned_user_id=uuid.UUID(rep["user_id"]),
            is_active=True,
        )
    )
    await db_session.flush()

    with _patch(
        "services.google_maps_service.geocode",
        new_callable=AsyncMock,
        return_value=(43.6, -116.2),  # Boise — far outside Atlanta radius
    ):
        rec_id = await _intake(client, cust["access_token"])

    record = (
        await db_session.execute(select(EquipmentRecord).where(EquipmentRecord.id == rec_id))
    ).scalar_one()
    assert record.assigned_sales_rep_id is None


@pytest.mark.asyncio
async def test_ad_hoc_takes_priority_over_geographic(
    client: AsyncClient, db_session: AsyncSession
):
    rep_adhoc = await _user_with_role(client, db_session, "lr_pr_a@example.com", "sales")
    rep_geo = await _user_with_role(client, db_session, "lr_pr_g@example.com", "sales")
    cust = await _activated_customer(
        client, db_session, "lr_pr_c@example.com", state="CA"
    )

    db_session.add(
        LeadRoutingRule(
            rule_type="ad_hoc",
            priority=10,
            conditions={"condition_type": "email_domain", "value": "example.com"},
            assigned_user_id=uuid.UUID(rep_adhoc["user_id"]),
            is_active=True,
        )
    )
    db_session.add(
        LeadRoutingRule(
            rule_type="geographic",
            priority=50,
            conditions={"state_list": ["CA"]},
            assigned_user_id=uuid.UUID(rep_geo["user_id"]),
            is_active=True,
        )
    )
    await db_session.flush()

    rec_id = await _intake(client, cust["access_token"])
    record = (
        await db_session.execute(select(EquipmentRecord).where(EquipmentRecord.id == rec_id))
    ).scalar_one()
    assert record.assigned_sales_rep_id == uuid.UUID(rep_adhoc["user_id"])


# --- round robin ------------------------------------------------------------ #


@pytest.mark.asyncio
async def test_round_robin_cycles_through_reps(
    client: AsyncClient, db_session: AsyncSession
):
    rep_a = await _user_with_role(client, db_session, "lr_rr_a@example.com", "sales")
    rep_b = await _user_with_role(client, db_session, "lr_rr_b@example.com", "sales")
    cust1 = await _activated_customer(client, db_session, "lr_rr_c1@example.com")
    cust2 = await _activated_customer(client, db_session, "lr_rr_c2@example.com")
    cust3 = await _activated_customer(client, db_session, "lr_rr_c3@example.com")

    rule = LeadRoutingRule(
        rule_type="round_robin",
        priority=1000,
        conditions={"rep_ids": [rep_a["user_id"], rep_b["user_id"]]},
        assigned_user_id=None,
        is_active=True,
    )
    db_session.add(rule)
    await db_session.flush()

    r1 = await _intake(client, cust1["access_token"])
    r2 = await _intake(client, cust2["access_token"])
    r3 = await _intake(client, cust3["access_token"])

    records = {
        rid: (
            await db_session.execute(select(EquipmentRecord).where(EquipmentRecord.id == rid))
        ).scalar_one()
        for rid in (r1, r2, r3)
    }
    assignees = [records[rid].assigned_sales_rep_id for rid in (r1, r2, r3)]
    # First three intakes should land on a, b, a (the rule starts at index 0,
    # the atomic UPDATE returns 1 → rep_ids[0], 2 → rep_ids[1], 3 → rep_ids[0]).
    assert assignees == [
        uuid.UUID(rep_a["user_id"]),
        uuid.UUID(rep_b["user_id"]),
        uuid.UUID(rep_a["user_id"]),
    ]

    # Counter was bumped via raw SQL — bypass the identity map.
    counter = (
        await db_session.execute(
            select(LeadRoutingRule.round_robin_index).where(LeadRoutingRule.id == rule.id)
        )
    ).scalar_one()
    assert counter == 3


# --- fallbacks -------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_appconfig_default_fallback_when_no_rule_matches(
    client: AsyncClient, db_session: AsyncSession
):
    rep = await _user_with_role(client, db_session, "lr_def_rep@example.com", "sales")
    cust = await _activated_customer(client, db_session, "lr_def_c@example.com")

    db_session.add(
        AppConfig(
            key="default_sales_rep_id",
            value={"user_id": rep["user_id"]},
        )
    )
    await db_session.flush()

    rec_id = await _intake(client, cust["access_token"])
    record = (
        await db_session.execute(select(EquipmentRecord).where(EquipmentRecord.id == rec_id))
    ).scalar_one()
    assert record.assigned_sales_rep_id == uuid.UUID(rep["user_id"])

    audit = await _routing_audit_for(db_session, rec_id)
    assert audit.after_state["trigger"] == "default_sales_rep"
    assert audit.after_state["rule_id"] is None
    assert audit.after_state["rule_type"] is None


@pytest.mark.asyncio
async def test_unassigned_when_nothing_matches(
    client: AsyncClient, db_session: AsyncSession
):
    cust = await _activated_customer(client, db_session, "lr_ua_c@example.com")
    rec_id = await _intake(client, cust["access_token"])

    record = (
        await db_session.execute(select(EquipmentRecord).where(EquipmentRecord.id == rec_id))
    ).scalar_one()
    assert record.assigned_sales_rep_id is None

    audit = await _routing_audit_for(db_session, rec_id)
    assert audit.after_state["trigger"] == "unassigned"
    assert audit.after_state["assigned_sales_rep_id"] is None


# --- safety: routing failure must not block intake ------------------------- #


@pytest.mark.asyncio
async def test_routing_failure_does_not_block_intake(
    client: AsyncClient, db_session: AsyncSession
):
    cust = await _activated_customer(client, db_session, "lr_fail_c@example.com")

    with patch(
        "services.lead_routing_service.route_for_record",
        new_callable=AsyncMock,
        side_effect=RuntimeError("simulated routing crash"),
    ):
        resp = await client.post(
            "/api/v1/me/equipment",
            json={"photos": []},
            headers=_auth(cust["access_token"]),
        )

    assert resp.status_code == 201, resp.json()
    rec_id = uuid.UUID(resp.json()["id"])
    record = (
        await db_session.execute(select(EquipmentRecord).where(EquipmentRecord.id == rec_id))
    ).scalar_one()
    assert record.assigned_sales_rep_id is None


# --- soft delete + inactive ------------------------------------------------- #


@pytest.mark.asyncio
async def test_soft_deleted_rule_excluded_from_waterfall(
    client: AsyncClient, db_session: AsyncSession
):
    from datetime import UTC, datetime

    rep = await _user_with_role(client, db_session, "lr_sd_rep@example.com", "sales")
    cust = await _activated_customer(
        client, db_session, "lr_sd_c@example.com", state="CA"
    )

    rule = LeadRoutingRule(
        rule_type="geographic",
        priority=50,
        conditions={"state_list": ["CA"]},
        assigned_user_id=uuid.UUID(rep["user_id"]),
        is_active=True,
        deleted_at=datetime.now(UTC),
    )
    db_session.add(rule)
    await db_session.flush()

    rec_id = await _intake(client, cust["access_token"])
    record = (
        await db_session.execute(select(EquipmentRecord).where(EquipmentRecord.id == rec_id))
    ).scalar_one()
    assert record.assigned_sales_rep_id is None


@pytest.mark.asyncio
async def test_inactive_rule_excluded_from_waterfall(
    client: AsyncClient, db_session: AsyncSession
):
    rep = await _user_with_role(client, db_session, "lr_inact_rep@example.com", "sales")
    cust = await _activated_customer(
        client, db_session, "lr_inact_c@example.com", state="CA"
    )

    rule = LeadRoutingRule(
        rule_type="geographic",
        priority=50,
        conditions={"state_list": ["CA"]},
        assigned_user_id=uuid.UUID(rep["user_id"]),
        is_active=False,
    )
    db_session.add(rule)
    await db_session.flush()

    rec_id = await _intake(client, cust["access_token"])
    record = (
        await db_session.execute(select(EquipmentRecord).where(EquipmentRecord.id == rec_id))
    ).scalar_one()
    assert record.assigned_sales_rep_id is None

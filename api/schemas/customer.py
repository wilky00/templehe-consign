# ABOUTME: Pydantic schemas for the customer profile + email preferences endpoints.
# ABOUTME: Used by api/routers/customers.py; shape mirrors the customers + users rows.
from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict, Field, field_validator

# US state codes validated at the schema boundary so bad inputs never reach
# the service layer or the DB CHECK. Kept broad — full USPS list incl. DC/PR.
_US_STATES = frozenset(
    {
        "AL",
        "AK",
        "AZ",
        "AR",
        "CA",
        "CO",
        "CT",
        "DE",
        "FL",
        "GA",
        "HI",
        "ID",
        "IL",
        "IN",
        "IA",
        "KS",
        "KY",
        "LA",
        "ME",
        "MD",
        "MA",
        "MI",
        "MN",
        "MS",
        "MO",
        "MT",
        "NE",
        "NV",
        "NH",
        "NJ",
        "NM",
        "NY",
        "NC",
        "ND",
        "OH",
        "OK",
        "OR",
        "PA",
        "RI",
        "SC",
        "SD",
        "TN",
        "TX",
        "UT",
        "VT",
        "VA",
        "WA",
        "WV",
        "WI",
        "WY",
        "DC",
        "PR",
    }
)


class EmailPrefs(BaseModel):
    """Per-user email/SMS opt-in matrix. Stored as JSONB on customers.communication_prefs."""

    intake_confirmations: bool = True
    status_updates: bool = True
    marketing: bool = False
    sms_opt_in: bool = False


class CustomerProfileRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    business_name: str | None = None
    submitter_name: str
    title: str | None = None
    address_street: str | None = None
    address_city: str | None = None
    address_state: str | None = None
    address_zip: str | None = None
    business_phone: str | None = None
    business_phone_ext: str | None = None
    cell_phone: str | None = None
    email_prefs: EmailPrefs


class CustomerProfileUpdate(BaseModel):
    """PATCH payload — every field optional; only supplied fields are updated."""

    business_name: str | None = Field(default=None, max_length=200)
    submitter_name: str | None = Field(default=None, max_length=200)
    title: str | None = Field(default=None, max_length=100)
    address_street: str | None = Field(default=None, max_length=255)
    address_city: str | None = Field(default=None, max_length=100)
    address_state: str | None = Field(default=None, max_length=2)
    address_zip: str | None = Field(default=None, max_length=10)
    business_phone: str | None = Field(default=None, max_length=20)
    business_phone_ext: str | None = Field(default=None, max_length=10)
    cell_phone: str | None = Field(default=None, max_length=20)

    @field_validator("address_state")
    @classmethod
    def state_is_valid_us_code(cls, v: str | None) -> str | None:
        if v is None:
            return v
        upper = v.strip().upper()
        if upper not in _US_STATES:
            raise ValueError("address_state must be a 2-letter USPS state code.")
        return upper

    @field_validator(
        "business_name",
        "submitter_name",
        "title",
        "address_street",
        "address_city",
        "address_zip",
        "business_phone",
        "business_phone_ext",
        "cell_phone",
    )
    @classmethod
    def strip_or_null(cls, v: str | None) -> str | None:
        if v is None:
            return v
        v = v.strip()
        return v or None

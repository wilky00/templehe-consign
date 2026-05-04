# ABOUTME: Public listing and inquiry request/response schemas — Phase 8.
# ABOUTME: All listing fields are safe for unauthenticated callers; no internal IDs exposed.
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class PublicListingCard(BaseModel):
    """Compact listing row for the paginated /public/listings index."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    listing_title: str
    asking_price: Decimal | None
    status: str
    published_at: datetime | None
    # Equipment fields (joined via equipment_record)
    make: str | None
    model: str | None
    year: int | None
    category_name: str | None
    hours_condition: str | None
    marketability_rating: str | None
    state: str | None
    primary_photo_url: str | None


class PublicListingDetail(BaseModel):
    """Full listing detail for /public/listings/:id."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    listing_title: str
    asking_price: Decimal | None
    published_at: datetime | None
    make: str | None
    model: str | None
    year: int | None
    serial_number: str | None
    category_name: str | None
    hours_condition: str | None
    running_status: str | None
    marketability_rating: str | None
    transport_notes: str | None
    listing_notes: str | None
    state: str | None
    primary_photo_url: str | None
    # Sales rep contact (name only — no email/phone to protect staff PII)
    assigned_rep_name: str | None
    contact_phone: str | None  # business phone from customer record


class PublicListingsResponse(BaseModel):
    items: list[PublicListingCard]
    total: int
    page: int
    page_size: int
    total_pages: int


class InquiryCreate(BaseModel):
    first_name: str = Field(..., min_length=1, max_length=100)
    last_name: str = Field(..., min_length=1, max_length=100)
    email: EmailStr
    phone: str | None = Field(None, max_length=20)
    message: str | None = Field(None, max_length=2000)
    # Honeypot — bots fill this in; humans leave it empty
    web_address: str | None = Field(None, max_length=500)


class InquiryResponse(BaseModel):
    id: uuid.UUID
    message: str = "Thank you for your inquiry. A sales representative will be in touch shortly."


class ListingPatch(BaseModel):
    """Sales rep update to a public listing — asking price or status only."""

    asking_price: Decimal | None = None
    status: Literal["active", "sold", "withdrawn"] | None = None

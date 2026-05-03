# ABOUTME: Phase 7 — Pydantic models for the appraisal PDF report data assembly.
# ABOUTME: ReportData + section models are the contract between ReportDataService and the template layer.
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel


class ComponentScoreRow(BaseModel):
    component_name: str
    raw_score: Decimal
    weight_pct: Decimal
    weighted_contribution: Decimal


class ComparableSaleRow(BaseModel):
    sale_price: Decimal | None = None
    sale_date: str | None = None
    make: str | None = None
    model: str | None = None
    year: int | None = None
    hours: int | None = None
    source: str | None = None


class RedFlagEntry(BaseModel):
    rule_id: str | None = None
    label: str | None = None
    triggered_at: str | None = None


class EquipmentDetailsSection(BaseModel):
    reference_number: str | None
    make: str | None
    model: str | None
    year: int | None
    serial_number: str | None
    hours_condition: str | None
    running_status: str | None
    title_status: str | None
    transport_notes: str | None
    category_name: str | None
    appraisal_date: datetime | None


class ValuationSection(BaseModel):
    approved_purchase_offer: Decimal | None
    suggested_consignment_price: Decimal | None
    overall_score: Decimal | None
    score_band: str | None
    marketability_rating: str | None
    component_scores: list[ComponentScoreRow]
    comparable_sales: list[ComparableSaleRow]
    red_flags: list[RedFlagEntry]
    management_review_required: bool
    manager_notes: str | None


class PhotoRecord(BaseModel):
    photo_id: uuid.UUID
    slot_label: str
    gcs_path: str
    capture_timestamp: datetime | None
    gps_latitude: Decimal | None
    gps_longitude: Decimal | None
    gps_missing: bool
    gps_out_of_range: bool


class PhotoGallerySection(BaseModel):
    photos: list[PhotoRecord]


class PersonnelMember(BaseModel):
    full_name: str
    email: str | None
    role_label: str


class PersonnelSection(BaseModel):
    appraiser: PersonnelMember | None
    sales_rep: PersonnelMember | None


class BrandingSection(BaseModel):
    company_logo_url: str
    brand_primary_color: str
    font_family: str
    page_size: str


class ReportData(BaseModel):
    submission_id: uuid.UUID
    equipment_record_id: uuid.UUID
    equipment: EquipmentDetailsSection
    valuation: ValuationSection
    gallery: PhotoGallerySection
    personnel: PersonnelSection
    branding: BrandingSection


class ReportDownloadResponse(BaseModel):
    download_url: str
    expires_at: datetime


class ReportGeneratingResponse(BaseModel):
    status: str = "generating"
    message: str = "Your report is being prepared. Please check back in a few minutes."

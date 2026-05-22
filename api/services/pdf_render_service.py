# ABOUTME: Phase 7 — renders a ReportData model into a PDF using Jinja2 + WeasyPrint.
# ABOUTME: Photos are fetched from R2 and re-compressed to 60% JPEG at max 800x800px for embedding.
"""PDF rendering service.

:func:`render_pdf` is the single public entry point. It:

1. Renders the Jinja2 HTML template with the report data.
2. Fetches and re-compresses each photo from R2 to a 800×800px / 60% JPEG.
3. Passes the HTML string to WeasyPrint to produce the final PDF bytes.

The photo fetch is best-effort: a failed fetch embeds nothing (``inline_image_data=None``)
so the gallery cell renders the "Photo unavailable" placeholder.
"""

from __future__ import annotations

import base64
import io
import logging
from datetime import UTC, datetime
from pathlib import Path

import boto3
import structlog
from botocore.client import Config as BotoConfig
from jinja2 import Environment, FileSystemLoader, select_autoescape
from PIL import Image
from weasyprint import HTML as WeasyHTML

from config import settings
from schemas.report import PhotoRecord, ReportData

logger = structlog.get_logger(__name__)

# Suppress WeasyPrint's font warnings at the logging level — they flood
# test output and are cosmetic on the dev machine (fonts fall back gracefully).
logging.getLogger("weasyprint").setLevel(logging.ERROR)
logging.getLogger("fontTools").setLevel(logging.ERROR)

_TEMPLATES_DIR = Path(__file__).parent.parent / "templates"

_PDF_PHOTO_MAX_PX = 800
_PDF_PHOTO_JPEG_QUALITY = 60


def _jinja_env() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(_TEMPLATES_DIR)),
        autoescape=select_autoescape(["html"]),
    )


def _r2_client():
    return boto3.client(
        "s3",
        endpoint_url=settings.storage_endpoint_url or f"https://{settings.r2_account_id}.r2.cloudflarestorage.com",
        aws_access_key_id=settings.r2_access_key_id,
        aws_secret_access_key=settings.r2_secret_access_key,
        region_name="auto",
        config=BotoConfig(
            signature_version="s3v4",
            s3={"addressing_style": "path"},
        ),
    )


def _fetch_and_compress_photo(gcs_path: str) -> str | None:
    """Fetch a photo from R2, re-compress for PDF embedding, return base64."""
    if not (settings.r2_access_key_id and settings.r2_secret_access_key):
        return None
    try:
        client = _r2_client()
        obj = client.get_object(Bucket=settings.r2_bucket_photos, Key=gcs_path)
        raw = obj["Body"].read()
    except Exception:
        logger.warning("pdf_photo_fetch_failed", gcs_path=gcs_path)
        return None

    try:
        img = Image.open(io.BytesIO(raw)).convert("RGB")
        img.thumbnail((_PDF_PHOTO_MAX_PX, _PDF_PHOTO_MAX_PX), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=_PDF_PHOTO_JPEG_QUALITY, optimize=True)
        return base64.b64encode(buf.getvalue()).decode()
    except Exception:
        logger.warning("pdf_photo_compress_failed", gcs_path=gcs_path)
        return None


def _enrich_photos(photos: list[PhotoRecord]) -> list[dict]:
    """Return photo dicts augmented with ``inline_image_data`` (base64 or None)."""
    enriched = []
    for photo in photos:
        data = photo.model_dump()
        data["inline_image_data"] = _fetch_and_compress_photo(photo.gcs_path)
        enriched.append(data)
    return enriched


def render_pdf(report_data: ReportData) -> bytes:
    """Render a ReportData into PDF bytes.

    Photos are fetched and re-compressed inline. A failed photo fetch
    renders a placeholder cell — it does not abort the PDF.
    """
    enriched_photos = _enrich_photos(report_data.gallery.photos)

    # Build a serialisable copy of the report for the template
    report_dict = report_data.model_dump()
    report_dict["gallery"]["photos"] = enriched_photos

    # Re-wrap as a simple namespace for template attribute access
    report_ns = _dict_to_ns(report_dict)

    env = _jinja_env()
    tmpl = env.get_template("pdf/appraisal_report.html.j2")

    page_size = report_data.branding.page_size or "A4"
    brand_color = report_data.branding.brand_primary_color or "#1E3A5F"
    font_family = report_data.branding.font_family or "Inter, sans-serif"
    generated_date = datetime.now(UTC).strftime("%B %d, %Y")

    html_str = tmpl.render(
        report=report_ns,
        page_size=page_size,
        brand_color=brand_color,
        font_family=font_family,
        generated_date=generated_date,
    )

    return WeasyHTML(string=html_str, base_url=str(_TEMPLATES_DIR)).write_pdf()


class _NS:
    """Thin namespace — converts nested dicts to attribute-accessible objects."""

    def __init__(self, d: dict) -> None:
        for k, v in d.items():
            setattr(self, k, _dict_to_ns(v) if isinstance(v, dict) else v)

    def __repr__(self) -> str:
        return f"_NS({self.__dict__!r})"


def _dict_to_ns(val):
    if isinstance(val, dict):
        return _NS(val)
    if isinstance(val, list):
        return [_dict_to_ns(item) for item in val]
    return val

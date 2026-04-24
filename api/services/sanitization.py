# ABOUTME: bleach-based sanitization wrappers for customer-supplied free-text fields.
# ABOUTME: All customer intake/description/caption values route through these before DB writes.
"""Centralized sanitization so every free-text path applies the same rules.

Two surfaces:
- ``sanitize_plain`` — strips all markup. For fields we never intend to
  render as HTML (names, descriptions shown as plain text).
- ``sanitize_html`` — allows a narrow inline-formatting allowlist. For
  fields that render in rich email templates or the future admin UI.

Both strip ``<script>`` content entirely (not just the tags) and drop
any ``javascript:`` / ``data:`` URI attributes. Security baseline §3.
"""

from __future__ import annotations

import bleach

# Nothing but text — no tags, no attributes. Strip comments + scripts.
_PLAIN_TAGS: list[str] = []
_PLAIN_ATTRS: dict[str, list[str]] = {}

# Narrow allowlist for fields we render in HTML contexts (e.g. email bodies).
# Block-level structure + inline emphasis; no images, no scripts, no iframes.
_HTML_TAGS: list[str] = [
    "p",
    "br",
    "strong",
    "em",
    "u",
    "b",
    "i",
    "ul",
    "ol",
    "li",
    "blockquote",
    "a",
]
_HTML_ATTRS: dict[str, list[str]] = {
    "a": ["href", "title", "rel"],
}
# http/https/mailto only — blocks javascript:, data:, vbscript:, etc.
_HTML_PROTOCOLS: list[str] = ["http", "https", "mailto"]


def sanitize_plain(value: str | None) -> str | None:
    """Return plain text with all markup stripped. Safe to render anywhere."""
    if value is None:
        return None
    cleaned = bleach.clean(
        value,
        tags=_PLAIN_TAGS,
        attributes=_PLAIN_ATTRS,
        strip=True,
        strip_comments=True,
    )
    return cleaned.strip() or None


def sanitize_html(value: str | None) -> str | None:
    """Return HTML with only the narrow allowlist tags kept. Unsafe URIs blocked."""
    if value is None:
        return None
    cleaned = bleach.clean(
        value,
        tags=_HTML_TAGS,
        attributes=_HTML_ATTRS,
        protocols=_HTML_PROTOCOLS,
        strip=True,
        strip_comments=True,
    )
    return cleaned.strip() or None

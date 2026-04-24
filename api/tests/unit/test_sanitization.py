# ABOUTME: Unit tests for api/services/sanitization.py.
# ABOUTME: Ensures bleach strips scripts and blocks unsafe URIs per security baseline §3.
from __future__ import annotations

from services.sanitization import sanitize_html, sanitize_plain


def test_sanitize_plain_strips_all_tags():
    """bleach with strip=True drops tags but keeps the inner text. The
    important invariant is 'no executable markup survives'; literal text
    like 'alert(1)' may remain as plain characters, which is safe."""
    out = sanitize_plain("<script>alert(1)</script>Hello <b>world</b>")
    assert out is not None
    assert "<" not in out
    assert ">" not in out
    assert "Hello" in out
    assert "world" in out


def test_sanitize_plain_returns_none_for_empty_input():
    assert sanitize_plain(None) is None
    assert sanitize_plain("") is None
    assert sanitize_plain("    ") is None


def test_sanitize_html_preserves_allowlisted_tags():
    out = sanitize_html("<p>Hi <strong>there</strong></p>")
    assert out == "<p>Hi <strong>there</strong></p>"


def test_sanitize_html_blocks_scripts_and_iframes():
    out = sanitize_html("<p>ok</p><script>bad()</script><iframe src=x></iframe>")
    assert out is not None
    assert "<script" not in out
    assert "<iframe" not in out
    assert "<p>ok</p>" in out


def test_sanitize_html_blocks_javascript_href():
    out = sanitize_html('<a href="javascript:alert(1)">click</a>')
    # bleach strips the disallowed protocol from the href.
    assert out is not None
    assert "javascript:" not in out
    assert "click" in out


def test_sanitize_html_blocks_data_uri_href():
    out = sanitize_html('<a href="data:text/html,<script>bad()</script>">x</a>')
    assert out is not None
    assert "data:" not in out

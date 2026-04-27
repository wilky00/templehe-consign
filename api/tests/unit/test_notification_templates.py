# ABOUTME: Phase 4 Sprint 5 — pure tests for the notification template registry.
# ABOUTME: Render w/ vars, autoescape, missing-var raises; no DB.
from __future__ import annotations

import pytest
from jinja2 import UndefinedError

from services import notification_templates


def test_status_update_renders_subject_and_body():
    rendered = notification_templates.render(
        "status_update",
        variables={
            "first_name": "Alice",
            "reference_number": "THE-123",
            "to_status_display": "Listed publicly",
            "to_status": "listed",
            "note_html": "",
        },
    )
    assert rendered.subject == "Listed publicly — THE-123"
    assert "Hi Alice" in rendered.body
    assert "<strong>listed</strong>" in rendered.body


def test_render_raises_for_missing_required_variable():
    with pytest.raises(UndefinedError):
        notification_templates.render(
            "status_update",
            variables={"first_name": "x", "reference_number": "y"},
        )


def test_render_autoescapes_html_in_email_variables():
    rendered = notification_templates.render(
        "status_update",
        variables={
            "first_name": "<script>alert('xss')</script>",
            "reference_number": "THE-1",
            "to_status_display": "Listed",
            "to_status": "listed",
            "note_html": "",
        },
    )
    assert "<script>" not in rendered.body
    assert "&lt;script&gt;" in rendered.body


def test_render_does_not_autoescape_sms_template():
    # SMS body is plain text — autoescape would corrupt punctuation
    # like "&" in "rep & manager".
    rendered = notification_templates.render(
        "record_lock_overridden_sms",
        variables={"reference": "THE-1", "manager_first_name": "Pat & Sam"},
    )
    assert "Pat & Sam" in rendered.body
    assert "&amp;" not in rendered.body


def test_all_specs_returns_every_registered_template():
    names = {t.name for t in notification_templates.all_specs()}
    expected = {
        "status_update",
        "sales_rep_approved_pending_esign",
        "sales_rep_esigned_pending_publish",
        "sales_rep_generic_status",
        "sales_rep_approved_pending_esign_sms",
        "sales_rep_esigned_pending_publish_sms",
        "sales_rep_generic_status_sms",
        "record_lock_overridden",
        "record_lock_overridden_sms",
    }
    assert expected.issubset(names)


def test_email_template_must_have_subject():
    """Subject is required for every email template; the registry's
    register() rejects email specs without one."""
    with pytest.raises(RuntimeError):
        notification_templates.register(
            notification_templates.Template(
                name="bad_email",
                channel="email",
                category="test",
                variables=(),
                body_template="...",
                subject_template=None,
            )
        )


def test_get_spec_raises_for_unknown_name():
    with pytest.raises(KeyError):
        notification_templates.get_spec("not_a_real_template")

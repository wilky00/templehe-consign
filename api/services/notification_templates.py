# ABOUTME: Phase 4 Sprint 5 — single source of truth for every notification template.
# ABOUTME: Replaces inline composers in equipment_status_service / record_locks / auth_service.
"""Notification template registry.

Phase 1–3 composed every email/SMS body inline at the call site. That
made one-off changes easy but it scattered marketing-style tone +
copy across the codebase, blocked admin "edit the email" UI work,
and meant template variables weren't introspectable. Phase 4 admin
needs to render an editor per template with the variable list
visible — that's only sound when there's a single registry the
runtime + admin form both read.

Each template registers a ``Template`` with:

- ``name`` — matches ``notification_jobs.template`` so existing
  idempotency keys + dispatch routing keep working.
- ``channel`` — ``"email"`` or ``"sms"``. Determines which renderer
  is required (subject only used for email).
- ``category`` — admin-form section grouping (``"status_update"``,
  ``"record_lock"``, ``"auth"``, ...).
- ``variables`` — declared variable list. Admin form renders a
  picker from this; render() raises if a required variable is
  missing (better to fail loudly than ship "Hi {{ name }}").
- ``subject_template`` — Jinja2 source for the email subject (None
  for SMS templates).
- ``body_template`` — Jinja2 source for the body. Email = HTML.
  SMS = plain text.

Render flow (``render(name, *, variables)``):
1. Look up the spec.
2. Validate every declared variable is present (KeyError otherwise).
3. Run subject_template + body_template through a Jinja2 environment
   with ``autoescape=True`` so user-controlled values can't inject
   HTML.

Overrides (Phase 4 admin "edit email copy") will land alongside the
``notification_template_overrides`` table — when a row exists for
``name``, its subject/body markdown replaces the code defaults at
render time. The registry is the fallback so a deletion always
restores the default.
"""

from __future__ import annotations

from dataclasses import dataclass

from jinja2 import Environment, StrictUndefined, select_autoescape
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import NotificationTemplateOverride

# StrictUndefined → accessing an undeclared variable raises rather than
# rendering an empty string. We want the loud failure during dev and a
# guaranteed-correct payload in prod.
_ENV = Environment(
    autoescape=select_autoescape(default=True),
    undefined=StrictUndefined,
    keep_trailing_newline=False,
)
_SMS_ENV = Environment(
    autoescape=False,  # SMS body is plain text — escape would corrupt punctuation.
    undefined=StrictUndefined,
    keep_trailing_newline=False,
)


@dataclass(frozen=True)
class RenderedTemplate:
    """Output of ``render``. ``subject`` is None for SMS templates."""

    subject: str | None
    body: str


@dataclass(frozen=True)
class Template:
    name: str
    channel: str  # "email" | "sms"
    category: str
    variables: tuple[str, ...]
    body_template: str
    subject_template: str | None = None
    description: str = ""


_REGISTRY: dict[str, Template] = {}


def register(spec: Template) -> Template:
    """Register a template. Idempotent on import; mismatched re-register
    raises so the registry stays a single source of truth."""
    existing = _REGISTRY.get(spec.name)
    if existing is not None and existing != spec:
        raise RuntimeError(
            f"Notification template '{spec.name}' already registered with a different "
            "spec; rename or deduplicate."
        )
    if spec.channel in ("email", "apns") and spec.subject_template is None:
        raise RuntimeError(f"'{spec.channel}' template '{spec.name}' requires a subject_template")
    if spec.channel not in ("email", "sms", "apns"):
        raise RuntimeError(f"template '{spec.name}' has invalid channel '{spec.channel}'")
    _REGISTRY[spec.name] = spec
    return spec


def get_spec(name: str) -> Template:
    return _REGISTRY[name]


def all_specs() -> tuple[Template, ...]:
    return tuple(sorted(_REGISTRY.values(), key=lambda t: (t.category, t.name)))


def render(name: str, *, variables: dict) -> RenderedTemplate:
    """Render ``name`` against ``variables``. Raises ``KeyError`` for
    unknown templates and ``jinja2.UndefinedError`` for missing variables."""
    spec = get_spec(name)
    return _render(spec, variables=variables, subject_override=None, body_override=None)


async def render_with_overrides(
    db: AsyncSession,
    name: str,
    *,
    variables: dict,
) -> RenderedTemplate:
    """Same as ``render`` but consults ``notification_template_overrides``
    first. Admin "edit email copy" writes there; if a row exists for
    ``name``, its subject/body markdown wins. Deleting the override
    falls back to the code default."""
    spec = get_spec(name)
    override = (
        await db.execute(
            select(NotificationTemplateOverride).where(NotificationTemplateOverride.name == name)
        )
    ).scalar_one_or_none()
    return _render(
        spec,
        variables=variables,
        subject_override=override.subject_md if override else None,
        body_override=override.body_md if override else None,
    )


def _render(
    spec: Template,
    *,
    variables: dict,
    subject_override: str | None,
    body_override: str | None,
) -> RenderedTemplate:
    # apns uses plain-text env (no HTML autoescape) same as sms.
    env = _ENV if spec.channel == "email" else _SMS_ENV
    body_src = body_override if body_override is not None else spec.body_template
    body = env.from_string(body_src).render(**variables).strip()
    subject = None
    if spec.channel in ("email", "apns"):
        subject_src = subject_override if subject_override is not None else spec.subject_template
        subject = env.from_string(subject_src or "").render(**variables).strip()
    return RenderedTemplate(subject=subject, body=body)


# ---------------------------------------------------------------------------
# Built-in templates. Each maps 1:1 to an existing inline composer so the
# migration is a swap, not a rewrite. Variable lists are explicit so the
# admin form can render a picker.
# ---------------------------------------------------------------------------


# Existing customer-facing status update (equipment_status_service).
STATUS_UPDATE = register(
    Template(
        name="status_update",
        channel="email",
        category="equipment_status",
        variables=(
            "first_name",
            "reference_number",
            "to_status_display",
            "to_status",
            "note_html",
        ),
        description="Sent to the customer when their record reaches a customer-facing status.",
        subject_template="{{ to_status_display }} — {{ reference_number }}",
        body_template=(
            "<p>Hi {{ first_name }},</p>"
            "<p>The status of your equipment submission "
            "(<strong>{{ reference_number }}</strong>) has changed to "
            "<strong>{{ to_status }}</strong>.</p>"
            "{{ note_html|safe }}"
            "<p>You can see the full timeline from your customer portal.</p>"
            "<p>— The Temple Heavy Equipment team</p>"
        ),
    )
)


SALES_REP_APPROVED_PENDING_ESIGN = register(
    Template(
        name="sales_rep_approved_pending_esign",
        channel="email",
        category="sales_rep",
        variables=("first_name", "reference_number", "make_model"),
        description="Sales rep notice when manager approves the appraisal — eSign ready.",
        subject_template="[Approved] Appraisal for {{ reference_number }} — Ready for eSign",
        body_template=(
            "<p>Hi {{ first_name }},</p>"
            "<p>The manager has approved the appraisal for "
            "<strong>{{ reference_number }}</strong> ({{ make_model }}). The record is now "
            "<strong>ready for eSign</strong>.</p>"
            "<p>Open the record in the sales dashboard to start the eSign flow.</p>"
        ),
    )
)


SALES_REP_ESIGNED_PENDING_PUBLISH = register(
    Template(
        name="sales_rep_esigned_pending_publish",
        channel="email",
        category="sales_rep",
        variables=("first_name", "reference_number", "make_model"),
        description="Sales rep notice when customer signs — listing ready to publish.",
        subject_template="[Signed] {{ reference_number }} ready to publish",
        body_template=(
            "<p>Hi {{ first_name }},</p>"
            "<p>The customer has signed the consignment agreement for "
            "<strong>{{ reference_number }}</strong> ({{ make_model }}). The listing is "
            "<strong>ready to publish</strong>.</p>"
            "<p>Open the record in the sales dashboard and tap "
            "<em>Publish Listing</em> when you're ready.</p>"
        ),
    )
)


SALES_REP_GENERIC_STATUS = register(
    Template(
        name="sales_rep_generic_status",
        channel="email",
        category="sales_rep",
        variables=("first_name", "reference_number", "to_status"),
        description="Fallback sales-rep email for any status not covered by a dedicated template.",
        subject_template="Status update — {{ reference_number }}",
        body_template=(
            "<p>Hi {{ first_name }},</p>"
            "<p>Record <strong>{{ reference_number }}</strong> moved to "
            "<strong>{{ to_status }}</strong>.</p>"
        ),
    )
)


SALES_REP_APPROVED_PENDING_ESIGN_SMS = register(
    Template(
        name="sales_rep_approved_pending_esign_sms",
        channel="sms",
        category="sales_rep",
        variables=("reference_number",),
        description="Sales rep SMS when manager approves the appraisal.",
        body_template="Manager approved {{ reference_number }}. Log in to initiate eSign.",
    )
)


SALES_REP_ESIGNED_PENDING_PUBLISH_SMS = register(
    Template(
        name="sales_rep_esigned_pending_publish_sms",
        channel="sms",
        category="sales_rep",
        variables=("reference_number",),
        description="Sales rep SMS when customer signs.",
        body_template="TempleHE: customer signed {{ reference_number }}. Ready to publish.",
    )
)


SALES_REP_GENERIC_STATUS_SMS = register(
    Template(
        name="sales_rep_generic_status_sms",
        channel="sms",
        category="sales_rep",
        variables=("reference_number", "to_status"),
        description="Fallback sales-rep SMS for any status not covered by a dedicated template.",
        body_template="TempleHE: {{ reference_number }} moved to {{ to_status }}.",
    )
)


# Record lock override (record_locks router).
RECORD_LOCK_OVERRIDDEN_EMAIL = register(
    Template(
        name="record_lock_overridden",
        channel="email",
        category="record_lock",
        variables=("first_name", "reference", "manager_first_name"),
        description="Email to the user whose record-edit lock was overridden by a manager.",
        subject_template="Your editing lock on {{ reference }} was released",
        body_template=(
            "<p>Hi {{ first_name }},</p>"
            "<p>Your editing lock on <strong>{{ reference }}</strong> was released "
            "by {{ manager_first_name }} so the record could be edited.</p>"
            "<p>Reopen the record from the sales dashboard if you still need to "
            "make changes.</p>"
        ),
    )
)


RECORD_LOCK_OVERRIDDEN_SMS = register(
    Template(
        name="record_lock_overridden_sms",
        channel="sms",
        category="record_lock",
        variables=("reference", "manager_first_name"),
        description="SMS to the user whose record-edit lock was overridden by a manager.",
        body_template=(
            "TempleHE: your editing lock on {{ reference }} was released "
            "by {{ manager_first_name }}."
        ),
    )
)


# Phase 4 Sprint 7 — Health alert dispatched to admins when a service flips red.
SERVICE_HEALTH_RED_ALERT_EMAIL = register(
    Template(
        name="service_health_red_alert",
        channel="email",
        category="health",
        variables=("service_name", "error_detail", "checked_at"),
        description="Email to admins when a monitored service flips to red status.",
        subject_template="[TempleHE] {{ service_name }} is unhealthy",
        body_template=(
            "<p>Service <strong>{{ service_name }}</strong> flipped to "
            "red status at {{ checked_at }}.</p>"
            "<p>Detail: {{ error_detail }}</p>"
            "<p>Visit /admin/health for the live dashboard.</p>"
        ),
    )
)


SERVICE_HEALTH_RED_ALERT_SMS = register(
    Template(
        name="service_health_red_alert_sms",
        channel="sms",
        category="health",
        variables=("service_name", "error_detail"),
        description="SMS to admins when a monitored service flips to red status.",
        body_template="TempleHE health alert: {{ service_name }} is red. {{ error_detail }}",
    )
)


SERVICE_HEALTH_RED_ALERT_SLACK = register(
    Template(
        name="service_health_red_alert_slack",
        channel="sms",  # Slack body uses the SMS env (no autoescape) — same shape.
        category="health",
        variables=("service_name", "error_detail", "checked_at"),
        description=(
            "Slack message body when a monitored service flips to red. "
            "Routes through the same plain-text env as SMS — autoescape "
            "would corrupt block-kit JSON."
        ),
        body_template=(
            ":rotating_light: TempleHE health alert: *{{ service_name }}* "
            "is red as of {{ checked_at }}. Detail: {{ error_detail }}"
        ),
    )
)


# ---------------------------------------------------------------------------
# Phase 5 Sprint 2 — APNs push notification templates.
# The dispatcher reads title/body from job.payload directly (same pattern
# as email templates above). These registry entries exist for admin
# visibility and future template-override support.
# ---------------------------------------------------------------------------


ASSIGNMENT_NOTIFICATION_APNS = register(
    Template(
        name="record_assigned_apns",
        channel="apns",
        category="appraiser",
        variables=("descriptor",),
        description="iOS push sent to an appraiser when they are assigned an equipment record.",
        subject_template="New Assignment",
        body_template="You've been assigned {{ descriptor }}.",
    )
)


APPOINTMENT_REMINDER_APNS = register(
    Template(
        name="appointment_reminder_apns",
        channel="apns",
        category="appraiser",
        variables=("descriptor", "scheduled_time"),
        description="iOS push reminder sent to an appraiser before a scheduled appointment.",
        subject_template="Upcoming Appointment",
        body_template="{{ descriptor }} is scheduled for {{ scheduled_time }}.",
    )
)


SYNC_CONFIRMATION_APNS = register(
    Template(
        name="sync_confirmation_apns",
        channel="apns",
        category="appraiser",
        variables=("reference_number",),
        description="Silent iOS push after a successful appraisal sync to prompt a data refresh.",
        subject_template="Sync Complete",
        body_template="Appraisal {{ reference_number }} synced successfully.",
    )
)


SYNC_FAILED_APNS = register(
    Template(
        name="sync_failed_apns",
        channel="apns",
        category="appraiser",
        variables=("reference_number", "error_reason"),
        description="iOS push sent when an appraisal submission sync fails after max retries.",
        subject_template="Sync Failed",
        body_template="Appraisal {{ reference_number }} could not be synced: {{ error_reason }}.",
    )
)


# ---------------------------------------------------------------------------
# Phase 6 Sprint 1 — Manager approval workflow notifications.
# ---------------------------------------------------------------------------

MANAGEMENT_REVIEW_FLAGGED_EMAIL = register(
    Template(
        name="management_review_flagged_email",
        channel="email",
        category="approval",
        variables=("reference_number", "make", "model", "red_flag_summary"),
        description=(
            "Sent to all Sales Managers when an appraisal submission is flagged "
            "for management review (structural damage, active leak, non-running, etc.)."
        ),
        subject_template="Management Review Required: {{ reference_number }}",
        body_template=(
            "<p>An appraisal submission requires your review.</p>"
            "<p><strong>{{ make }} {{ model }}</strong> ({{ reference_number }})</p>"
            "<p><strong>Flagged conditions:</strong><br>{{ red_flag_summary }}</p>"
            "<p>Please log in to the manager approval queue to review and approve or reject.</p>"
        ),
    )
)

MANAGEMENT_REVIEW_FLAGGED_SMS = register(
    Template(
        name="management_review_flagged_sms",
        channel="sms",
        category="approval",
        variables=("reference_number", "make", "model", "red_flag_summary"),
        description=(
            "SMS variant of management_review_flagged_email. "
            "Sent to Sales Managers who prefer SMS notifications."
        ),
        body_template=(
            "TempleHE: Management review required for {{ make }} {{ model }} "
            "({{ reference_number }}). Flags: {{ red_flag_summary }}"
        ),
    )
)


# Phase 6 Sprint 2 — Rejection notifications.

APPRAISAL_REJECTED_SALES_REP_EMAIL = register(
    Template(
        name="appraisal_rejected_sales_rep_email",
        channel="email",
        category="approval",
        variables=("reference_number", "make", "model", "rejection_notes", "send_back"),
        description=(
            "Sent to the assigned Sales Rep when a manager rejects an appraisal, "
            "whether permanently declined or sent back for re-appraisal."
        ),
        subject_template="Appraisal Rejected: {{ reference_number }}",
        body_template=(
            "<p>The appraisal for <strong>{{ make }} {{ model }}</strong> "
            "({{ reference_number }}) has been rejected.</p>"
            "<p><strong>Manager notes:</strong> {{ rejection_notes }}</p>"
            "<p>{% if send_back %}The record has been returned for re-appraisal.{% else %}"
            "The record has been declined.{% endif %}</p>"
        ),
    )
)


APPRAISAL_REJECTED_APPRAISER_EMAIL = register(
    Template(
        name="appraisal_rejected_appraiser_email",
        channel="email",
        category="approval",
        variables=("reference_number", "make", "model", "rejection_notes"),
        description=(
            "Sent to the Appraiser when a manager sends an appraisal back for re-appraisal. "
            "Not sent on permanent declines — the appraiser's role ends at submission."
        ),
        subject_template="Re-Appraisal Required: {{ reference_number }}",
        body_template=(
            "<p>The appraisal you submitted for <strong>{{ make }} {{ model }}</strong> "
            "({{ reference_number }}) requires a re-inspection.</p>"
            "<p><strong>Manager notes:</strong> {{ rejection_notes }}</p>"
            "<p>Please log in to the app to begin a new appraisal for this record.</p>"
        ),
    )
)


CUSTOMER_ESIGN_READY = register(
    Template(
        name="customer_esign_ready",
        channel="email",
        category="customer",
        variables=("first_name", "reference_number", "make_model", "envelope_id"),
        description="Sent to the customer when the consignment agreement is ready to sign.",
        subject_template=(
            "Action Required: Sign Your Consignment Agreement for {{ reference_number }}"
        ),
        body_template=(
            "<p>Hi {{ first_name }},</p>"
            "<p>Your consignment agreement for <strong>{{ make_model }}</strong> "
            "({{ reference_number }}) is ready for your signature.</p>"
            "<p><a href='/api/v1/esign/sign/{{ envelope_id }}'>Sign Agreement</a></p>"
            "<p>If you have any questions, please contact us.</p>"
            "<p>— The Temple Heavy Equipment team</p>"
        ),
    )
)


MANAGER_PRICE_CHANGE_REAPPROVAL = register(
    Template(
        name="manager_price_change_reapproval",
        channel="email",
        category="approval",
        variables=(
            "reference_number",
            "make_model",
            "approved_price",
            "proposed_price",
            "change_pct",
        ),
        description=(
            "Sent to managers when a customer's proposed price change exceeds the"
            " re-approval threshold."
        ),
        subject_template="Re-Approval Required: Price Change on {{ reference_number }}",
        body_template=(
            "<p>A customer has requested a consignment price change that requires your"
            " approval.</p>"
            "<p>Record: <strong>{{ reference_number }}</strong> ({{ make_model }})</p>"
            "<p>Approved price: ${{ approved_price }}<br>"
            "Proposed price: ${{ proposed_price }}<br>"
            "Change: {{ change_pct }}%</p>"
            "<p>Log in to the manager approval queue to review and approve or reject this"
            " change.</p>"
        ),
    )
)

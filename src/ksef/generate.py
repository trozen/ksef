from __future__ import annotations

import calendar
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal

from jinja2 import Environment, StrictUndefined

from ksef.profiles import Profile

HALF_MONTH_BOUNDARY = 15


def resolve_issue_date(today: date | None = None) -> date:
    """Return invoice issue date based on current date.

    Before the 15th: end of previous month (invoice covers the month just ended).
    From the 15th on: end of current month.
    """
    today = today or date.today()
    if today.day < HALF_MONTH_BOUNDARY:
        first_of_this = today.replace(day=1)
        return first_of_this - timedelta(days=1)
    last_day = calendar.monthrange(today.year, today.month)[1]
    return today.replace(day=last_day)


def render_invoice(
    profile: Profile,
    invoice_number: str,
    net_amount_cli: str | None,
    issue_date: date,
) -> tuple[str, list[tuple[str, str, str]]]:
    """Render the profile's Jinja2 template.

    Returns (xml_string, context_log) where context_log is a list of
    (variable, value, source) tuples for display.
    """
    # Layer 1: profile defaults
    context: dict[str, str] = dict(profile.defaults)
    sources: dict[str, str] = {k: "profile default" for k in context}

    # Layer 2: CLI overrides
    if invoice_number:
        context["invoice_number"] = invoice_number
        sources["invoice_number"] = "CLI"
    if net_amount_cli:
        context["net_amount"] = net_amount_cli
        sources["net_amount"] = "CLI"

    # Resolve net_amount for computation
    raw_net = context.get("net_amount", "")
    if not raw_net:
        raise ValueError(
            "net_amount is required — pass it as CLI argument or set it under [defaults] in the profile toml"
        )
    net_amount = Decimal(raw_net)

    # Layer 3: computed
    period_from = issue_date.replace(day=1)
    period_to = issue_date
    due_date = issue_date + timedelta(days=profile.payment_days)
    vat_amount = (net_amount * Decimal(profile.vat_rate) / 100).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    gross_amount = net_amount + vat_amount
    today = date.today()

    computed = {
        "net_amount": f"{net_amount:.2f}",
        "vat_amount": f"{vat_amount:.2f}",
        "gross_amount": f"{gross_amount:.2f}",
        "issue_date": issue_date.strftime("%Y-%m-%d"),
        "period_from": period_from.strftime("%Y-%m-%d"),
        "period_to": period_to.strftime("%Y-%m-%d"),
        "due_date": due_date.strftime("%Y-%m-%d"),
        "submission_date": today.strftime("%Y-%m-%d"),
        "generation_timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    computed_source = {
        "vat_amount": f"computed ({profile.vat_rate}% VAT)",
        "gross_amount": "computed",
        "issue_date": "computed",
        "period_from": "computed",
        "period_to": "computed",
        "due_date": f"computed ({profile.payment_days} days)",
        "submission_date": "today",
        "generation_timestamp": "today",
    }
    context.update(computed)
    # Only set source for computed keys not already tracked from CLI/defaults
    for k, src in computed_source.items():
        sources.setdefault(k, src)

    # Build log in a stable order for display
    display_order = [
        "invoice_number", "net_amount", "vat_amount", "gross_amount",
        "issue_date", "period_from", "period_to", "due_date",
        "submission_date", "generation_timestamp",
    ]
    other_keys = [k for k in context if k not in display_order]
    context_log = [
        (k, context[k], sources.get(k, ""))
        for k in display_order + other_keys
        if k in context
    ]

    template_text = profile.template_path.read_text(encoding="utf-8")
    env = Environment(undefined=StrictUndefined, autoescape=False)
    xml = env.from_string(template_text).render(**context)
    return xml, context_log


def output_filename(profile: Profile, invoice_number: str) -> str:
    safe = invoice_number.replace("/", "_")
    return f"{profile.output_prefix}{safe}.xml"

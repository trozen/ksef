from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import NamedTuple, Optional

import click
import requests
import typer

from ksef import __version__

from ksef.client import KSeFError
from ksef.config import (
    KSEF_QR_BASE_URLS,
    LOCAL_CONFIG_NAME,
    load_config,
    peek_environment,
    resolve_config_path,
)
from rich.markup import escape

from ksef.display import (
    console,
    err_console,
    render_dashboard,
    render_invoice_detail,
    render_invoice_list,
)
from ksef.store import (
    get_invoice_xml_path,
    load_all_metadata,
    load_sync_state,
    resolve_invoice_id,
    search_invoices,
)
from ksef.parser import parse_invoice
from ksef.send import check_pending_sessions, run_check_session, run_send
from ksef.validate import validate_invoice_xml
from ksef.sync import run_sync
app = typer.Typer(
    name="ksef",
    help="Browse and manage Polish e-invoices from KSeF.",
    invoke_without_command=True,
    no_args_is_help=False,
    context_settings={"help_option_names": ["-h", "--help"]},
)

CONFIG_TEMPLATE = """\
[ksef]
nip = "YOUR_NIP"
environment = "prod"          # test / demo / prod
token_path = "/path/to/your/ksef.token"
data_dir = "/path/to/safe/storage/ksef"
# allow_send = true           # uncomment to enable ksef send

[ksef.sync]
date_from = "2026-01-01"
max_per_sync = 100
"""


def _print_error(e: RuntimeError) -> None:
    err_console.print(f"[red]Error:[/red] {e}")
    if isinstance(e, KSeFError):
        err_console.print(f"[dim]{escape(json.dumps(e.raw, ensure_ascii=False))}[/dim]")


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"ksef {__version__}")
        raise typer.Exit()


def _print_header(config_path: Path) -> None:
    env = peek_environment(config_path)
    env_str = f"  env: {escape(env)}" if env else ""
    console.print(f"ksef {escape(__version__)}  [dim]config: {escape(str(config_path))}{env_str}[/dim]", highlight=False)


def _print_commands_hint() -> None:
    commands = [
        ("ksef sync", "Fetch new invoices from KSeF"),
        ("ksef list", "List all invoices"),
        ("ksef show", "Show invoice details"),
        ("ksef send", "Send an invoice XML to KSeF"),
        ("ksef export", "Render an invoice as PDF"),
        ("ksef gen", "Generate an invoice XML from a profile"),
        ("ksef profile", "Manage invoice generation profiles"),
        ("ksef config", "Show resolved config"),
        ("ksef -h", "Full help"),
    ]
    for cmd, desc in commands:
        console.print(f"  [bold]{cmd}[/bold]  [dim]{desc}[/dim]")


@app.callback(invoke_without_command=True)
def dashboard(
    ctx: typer.Context,
    config: Optional[str] = typer.Option(None, "-c", "--config", help="Path to config file", is_eager=True),
    version: Optional[bool] = typer.Option(None, "--version", "-V", callback=_version_callback, is_eager=True, help="Show version and exit"),
) -> None:
    """Show dashboard with config summary and recent invoices."""
    ctx.ensure_object(dict)
    config_path = resolve_config_path(config)
    ctx.obj["config_path"] = config_path
    _print_header(config_path)

    if ctx.invoked_subcommand is not None:
        return

    from ksef.send import _load_pending
    cfg = load_config(config_path)
    sync_state = load_sync_state(cfg)
    invoices = load_all_metadata(cfg)
    pending_count = len(_load_pending(cfg))
    render_dashboard(cfg, sync_state, invoices, pending_count=pending_count)
    console.print()
    console.print("Commands:")
    _print_commands_hint()


@app.command(hidden=True)
def help(ctx: typer.Context) -> None:
    """Show help."""
    # Re-invoke with --help so typer prints the full help text
    click.echo(ctx.parent.get_help())


@app.command()
def init(
    ctx: typer.Context,
) -> None:
    """Write a template config file to ./ksef.config.toml.template."""
    output = Path.cwd() / (LOCAL_CONFIG_NAME + ".template")
    if output.exists():
        err_console.print(f"[yellow]Already exists:[/yellow] {output}")
        raise typer.Exit(1)
    output.write_text(CONFIG_TEMPLATE)
    console.print(f"[green]Template written to:[/green] {output}")
    console.print(f"Edit it, then rename to [bold]{LOCAL_CONFIG_NAME}[/bold] or pass with [bold]-c[/bold].")


@app.command()
def config(
    ctx: typer.Context,
) -> None:
    """Show resolved config and validate it."""
    config_path: Path = ctx.obj["config_path"]
    cfg = load_config(config_path)
    console.print(f"[bold]Config file:[/bold] {config_path}")
    console.print(f"  [dim]Override with -c, KSEF_CONFIG env var, or ./ksef.config.toml[/dim]")
    console.print()
    console.print(f"  NIP:         {cfg.nip}")
    console.print(f"  Environment: {cfg.environment}")
    console.print(f"  Token:       {cfg.token_path}")
    console.print(f"  Data dir:    {cfg.data_dir}")
    console.print(f"  Sync from:   {cfg.sync.date_from}")
    console.print(f"  Max per sync:{cfg.sync.max_per_sync}")
    console.print(f"  Allow send:  {'[green]yes[/green]' if cfg.allow_send else '[dim]no[/dim]'}")


@app.command()
def validate(
    ctx: typer.Context,
    xml_file: Path = typer.Argument(..., help="Path to the invoice XML file", exists=True, dir_okay=False),
) -> None:
    """Validate an invoice XML against the FA(3) schema."""
    xml_content = xml_file.read_text(encoding="utf-8")
    errors = validate_invoice_xml(xml_content)
    if errors:
        for e in errors:
            err_console.print(f"[red]✗[/red] {e}")
        raise typer.Exit(1)
    try:
        invoice = parse_invoice(xml_content)
    except Exception as e:
        err_console.print(f"[red]Invalid invoice XML:[/red] {e}")
        raise typer.Exit(1)
    render_invoice_detail(invoice)
    console.print(f"[green]✓[/green] {escape(xml_file.name)} is valid.")


@app.command()
def send(
    ctx: typer.Context,
    xml_file: Path = typer.Argument(..., help="Path to the invoice XML file", exists=True, dir_okay=False),
    upo: Optional[Path] = typer.Option(None, "--upo", help="Where to save the UPO (default: <xml_file>.upo.xml)"),
) -> None:
    """Send an invoice XML to KSeF and save the UPO receipt."""
    cfg = load_config(ctx.obj["config_path"])

    if not cfg.allow_send:
        err_console.print("[red]Sending is disabled.[/red] Set [bold]allow_send = true[/bold] in your config to enable it.")
        raise typer.Exit(1)

    if upo is None:
        upo = xml_file.with_suffix(".upo.xml")

    xml_bytes = xml_file.read_bytes()

    try:
        invoice = parse_invoice(xml_bytes.decode("utf-8"))
    except Exception as e:
        err_console.print(f"[red]Invalid invoice XML:[/red] {e}")
        raise typer.Exit(1)

    render_invoice_detail(invoice)

    console.print()
    confirmation = typer.prompt("Upload this invoice to KSeF? Enter 'yes' to confirm, or press Enter to abort", default="", show_default=False)
    if confirmation.strip().lower() != "yes":
        console.print("[yellow]Aborted.[/yellow]")
        raise typer.Exit(0)

    try:
        run_send(cfg, xml_file, xml_bytes, upo_path=upo)
    except requests.exceptions.ConnectionError as e:
        reason = e
        while reason.__cause__:
            reason = reason.__cause__
        err_console.print(f"[red]Connection error:[/red] {reason}")
        raise typer.Exit(1)
    except requests.exceptions.Timeout as e:
        err_console.print(f"[red]Timeout:[/red] {e}")
        raise typer.Exit(1)
    except RuntimeError as e:
        _print_error(e)
        raise typer.Exit(1)


@app.command()
def session(
    ctx: typer.Context,
    session_ref: str = typer.Argument(..., help="Session reference number"),
) -> None:
    """Check session status and download UPO if ready."""
    cfg = load_config(ctx.obj["config_path"])
    try:
        run_check_session(cfg, session_ref)
    except requests.exceptions.ConnectionError as e:
        reason = e
        while reason.__cause__:
            reason = reason.__cause__
        err_console.print(f"[red]Connection error:[/red] {reason}")
        raise typer.Exit(1)
    except RuntimeError as e:
        _print_error(e)
        raise typer.Exit(1)


@app.command()
def sync(
    ctx: typer.Context,
    date_from: Optional[str] = typer.Option(None, "--from", help="Start date (YYYY-MM-DD)"),
    date_to: Optional[str] = typer.Option(None, "--to", help="End date (YYYY-MM-DD)"),
    max_invoices: Optional[int] = typer.Option(None, "--max", "-n", help="Max invoices to fetch"),
    force: bool = typer.Option(False, "--force", "-f", help="Force sync last 30 days"),
) -> None:
    """Sync invoices from KSeF (incremental by default)."""
    cfg = load_config(ctx.obj["config_path"])

    if force:
        date_from = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%d")

    try:
        run_sync(cfg, date_from=date_from, date_to=date_to, max_invoices=max_invoices)
    except requests.exceptions.ConnectionError as e:
        reason = e
        while reason.__cause__:
            reason = reason.__cause__
        err_console.print(f"[red]Connection error:[/red] {reason}")
        raise typer.Exit(1)
    except requests.exceptions.Timeout as e:
        err_console.print(f"[red]Timeout:[/red] {e}")
        raise typer.Exit(1)
    except RuntimeError as e:
        _print_error(e)
        raise typer.Exit(1)


@app.command(name="list")
def list_invoices(
    ctx: typer.Context,
    limit: int = typer.Option(20, "--limit", "-n", help="Number of invoices to show"),
    seller: Optional[str] = typer.Option(None, "--seller", "-s", help="Filter by seller name or NIP"),
) -> None:
    """List invoices."""
    cfg = load_config(ctx.obj["config_path"])

    if seller:
        invoices = search_invoices(cfg, seller)
    else:
        invoices = load_all_metadata(cfg)

    render_invoice_list(invoices, limit=limit)


class _ResolvedInvoice(NamedTuple):
    invoice: object  # ksef.models.Invoice
    xml_bytes: bytes
    xml_path: Optional[Path]
    qr_base_url: str
    from_store: bool


def _resolve_invoice(ctx: typer.Context, query: str) -> _ResolvedInvoice:
    """Resolve a query (XML file path or store query) to a parsed invoice + bytes.

    For file-path mode, qr_base_url defaults to '' (config not loaded).
    """
    xml_path = Path(query)
    if xml_path.suffix.lower() == ".xml" and xml_path.exists():
        xml_bytes = xml_path.read_bytes()
        try:
            invoice = parse_invoice(xml_bytes.decode("utf-8"))
        except Exception as e:
            err_console.print(f"[red]Invalid invoice XML:[/red] {e}")
            raise typer.Exit(1)
        return _ResolvedInvoice(invoice, xml_bytes, xml_path, "", from_store=False)

    cfg = load_config(ctx.obj["config_path"])
    all_invoices = load_all_metadata(cfg)

    stripped = query.lstrip("#")
    if stripped.isdigit():
        idx = int(stripped) - 1
        if 0 <= idx < len(all_invoices):
            matches = [all_invoices[idx]]
        else:
            err_console.print(f"[red]Invoice #{int(stripped)} not found.[/red] You have {len(all_invoices)} invoice(s).")
            raise typer.Exit(1)
    else:
        matches = resolve_invoice_id(cfg, query)

    if not matches:
        err_console.print(f"[red]No invoice found matching:[/red] {query}")
        raise typer.Exit(1)

    if len(matches) > 1:
        console.print(f"[yellow]Multiple matches for '{query}':[/yellow]")
        for m in matches[:10]:
            console.print(f"  {m['ksef_number']}  {m.get('invoice_number', '')}  {m.get('seller_name', '')}")
        if len(matches) > 10:
            console.print(f"  [dim]...and {len(matches) - 10} more[/dim]")
        console.print("\n[dim]Use a more specific identifier.[/dim]")
        raise typer.Exit(1)

    meta = matches[0]
    ksef_number = meta["ksef_number"]
    stored_xml_path = get_invoice_xml_path(cfg, ksef_number)
    if not stored_xml_path or not stored_xml_path.exists():
        err_console.print(f"[red]XML file not found for:[/red] {ksef_number}")
        raise typer.Exit(1)

    xml_bytes = stored_xml_path.read_bytes()
    invoice = parse_invoice(xml_bytes.decode("utf-8"), ksef_number=ksef_number)
    invoice.synced_at = meta.get("synced_at", "")
    qr_base_url = KSEF_QR_BASE_URLS.get(cfg.environment, KSEF_QR_BASE_URLS["prod"])
    return _ResolvedInvoice(invoice, xml_bytes, stored_xml_path, qr_base_url, from_store=True)


@app.command()
def show(
    ctx: typer.Context,
    query: Optional[str] = typer.Argument(None, help="List number (#1, #2), invoice number, seller name, or KSeF number"),
) -> None:
    """Show invoice details including line items."""
    if query is None:
        console.print("Usage: ksef show <query|file.xml>")
        console.print()
        console.print("Examples:")
        console.print("  ksef show 1            [dim]show invoice #1 from the list[/dim]")
        console.print("  ksef show FV/1/01      [dim]match by invoice number[/dim]")
        console.print("  ksef show Januszex     [dim]match by seller name[/dim]")
        console.print("  ksef show invoice.xml  [dim]show invoice from a local XML file[/dim]")
        raise typer.Exit(0)

    resolved = _resolve_invoice(ctx, query)
    render_invoice_detail(
        resolved.invoice,
        xml_path=str(resolved.xml_path) if resolved.xml_path else None,
        qr_base_url=resolved.qr_base_url,
    )


@app.command()
def export(
    ctx: typer.Context,
    query: str = typer.Argument(..., help="List number (#1, #2), invoice number, seller name, KSeF number, or path to XML file"),
    output: Optional[Path] = typer.Option(None, "-o", "--output", help="Output PDF path (default: <invoice_number>.pdf in cwd)"),
    lang: str = typer.Option("pl", "--lang", help="Output language: pl, en, pl/en, en/pl, dual (=pl/en)"),
) -> None:
    """Export an invoice to PDF (matching the official KSeF layout)."""
    from ksef.pdf import LANGUAGES, render_invoice_pdf
    if lang not in LANGUAGES:
        err_console.print(f"[red]Invalid --lang:[/red] {lang}. Must be one of: {', '.join(LANGUAGES)}")
        raise typer.Exit(1)

    resolved = _resolve_invoice(ctx, query)
    qr_base_url = resolved.qr_base_url
    # File-path mode with a submitted invoice: load config to enable QR
    if not qr_base_url and resolved.invoice.ksef_number:
        cfg = load_config(ctx.obj["config_path"])
        qr_base_url = KSEF_QR_BASE_URLS.get(cfg.environment, KSEF_QR_BASE_URLS["prod"])

    if output is None:
        if resolved.from_store:
            output = Path.cwd() / f"{resolved.invoice.ksef_number}.pdf"
        else:
            output = resolved.xml_path.with_suffix(".pdf")

    pdf_bytes = render_invoice_pdf(
        resolved.invoice, xml_bytes=resolved.xml_bytes, qr_base_url=qr_base_url, lang=lang
    )
    output.write_bytes(pdf_bytes)
    console.print(f"[green]✓[/green] {output}", highlight=False)


# ---------------------------------------------------------------------------
# profile sub-commands
# ---------------------------------------------------------------------------

profile_app = typer.Typer(name="profile", help="Manage invoice generation profiles.", no_args_is_help=True)
app.add_typer(profile_app)


@profile_app.command("vars")
def profile_vars(ctx: typer.Context) -> None:
    """List all Jinja2 variables available in invoice templates."""
    rows = [
        ("{{ invoice_number }}",       "Invoice number passed to ksef gen"),
        ("{{ issue_date }}",           "Issue date (YYYY-MM-DD) — end of billing month by default"),
        ("{{ period_from }}",          "First day of the billing month"),
        ("{{ period_to }}",            "Last day of the billing month (same as issue_date)"),
        ("{{ due_date }}",             "Payment due date — issue_date + payment_days from profile"),
        ("{{ submission_date }}",      "Today's date (YYYY-MM-DD) — date the XML is generated"),
        ("{{ net_amount }}",           "Net amount passed to ksef gen (e.g. 12300.00)"),
        ("{{ vat_amount }}",           "VAT amount — net × vat_rate% from profile"),
        ("{{ gross_amount }}",         "Gross amount — net + vat"),
        ("{{ generation_timestamp }}", "UTC timestamp of XML generation (ISO 8601)"),
    ]
    console.print("[bold]Template variables:[/bold]")
    for var, desc in rows:
        console.print(f"  [bold cyan]{var}[/bold cyan]")
        console.print(f"    {desc}")
    console.print()
    console.print(r"[dim]Any key under [bold]\[defaults][/bold] in the profile toml is also available as a variable.[/dim]")
    console.print(r"[dim]Computed variables above always take priority over \[defaults].[/dim]")


@profile_app.command("new")
def profile_new(
    ctx: typer.Context,
    name: str = typer.Argument(..., help="Profile name"),
    template: Path = typer.Argument(..., help="Path to the Jinja2 invoice XML template", exists=True, dir_okay=False),
) -> None:
    """Create a new profile from a Jinja2 invoice XML template."""
    from ksef.profiles import create_profile, profile_exists
    cfg = load_config(ctx.obj["config_path"])
    if profile_exists(name, cfg.profiles_dir):
        err_console.print(f"[red]Profile '{name}' already exists.[/red] Use a different name or delete it first.")
        raise typer.Exit(1)
    profile = create_profile(name, template, cfg.profiles_dir)
    console.print(f"[green]Profile '{name}' created.[/green]")
    console.print(f"  Template: {profile.template_path}")
    console.print(f"  Config:   {profile.template_path.with_suffix('.toml')}")
    console.print(r"  [dim]Add default template variable values under \[defaults] in the config.[/dim]")
    console.print(f"  [dim]Run [bold]ksef profile vars[/bold] to see available template variables.[/dim]")


@profile_app.command("list")
def profile_list(ctx: typer.Context) -> None:
    """List all profiles."""
    from ksef.profiles import list_profiles
    cfg = load_config(ctx.obj["config_path"])
    profiles = list_profiles(cfg.profiles_dir)
    if not profiles:
        console.print("[dim]No profiles found. Create one with: ksef profile new <name> <template.xml>[/dim]")
        return
    for p in profiles:
        console.print(f"  [bold]{p.name}[/bold]  [dim]VAT {p.vat_rate}%  ·  {p.payment_days} days  ·  {p.output_prefix!r}[/dim]")
        console.print(f"    [dim]{p.template_path}[/dim]", highlight=False)


@profile_app.command("show")
def profile_show(
    ctx: typer.Context,
    name: str = typer.Argument(..., help="Profile name"),
) -> None:
    """Show profile configuration and file paths."""
    from ksef.profiles import load_profile
    cfg = load_config(ctx.obj["config_path"])
    try:
        profile = load_profile(name, cfg.profiles_dir)
    except FileNotFoundError as e:
        err_console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)
    console.print(f"[bold]{profile.name}[/bold]")
    console.print(f"  VAT rate:      {profile.vat_rate}%")
    console.print(f"  Payment days:  {profile.payment_days}")
    console.print(f"  Output prefix: {profile.output_prefix!r}")
    if profile.defaults:
        console.print("  Defaults:")
        for k, v in profile.defaults.items():
            console.print(f"    {k} = {v!r}")
    console.print(f"  Template:      {profile.template_path}", highlight=False)
    console.print(f"  Config:        {profile.template_path.with_suffix('.toml')}", highlight=False)


@profile_app.command("delete")
def profile_delete(
    ctx: typer.Context,
    name: str = typer.Argument(..., help="Profile name"),
) -> None:
    """Delete a profile."""
    from ksef.profiles import delete_profile
    cfg = load_config(ctx.obj["config_path"])
    try:
        delete_profile(name, cfg.profiles_dir)
    except FileNotFoundError as e:
        err_console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)
    console.print(f"[green]Profile '{name}' deleted.[/green]")


# ---------------------------------------------------------------------------
# gen command
# ---------------------------------------------------------------------------

@app.command()
def gen(
    ctx: typer.Context,
    profile_name: str = typer.Argument(..., help="Profile name"),
    invoice_number: str = typer.Argument(..., help="Invoice number (e.g. FV/1/0626)"),
    amount: Optional[str] = typer.Argument(None, help="Net amount in PLN (e.g. 12300.00); falls back to profile default"),
    output: Optional[Path] = typer.Option(None, "-o", "--output", help="Output file path (default: auto-named in cwd)"),
    issue_today: bool = typer.Option(False, "--issue-today", help="Use today as the issue date instead of end of billing month"),
) -> None:
    """Generate an invoice XML from a profile template."""
    from ksef.generate import output_filename, render_invoice, resolve_issue_date
    from ksef.profiles import load_profile

    cfg = load_config(ctx.obj["config_path"])

    try:
        profile = load_profile(profile_name, cfg.profiles_dir)
    except FileNotFoundError as e:
        err_console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)

    if not invoice_number.strip():
        err_console.print("[red]Invoice number cannot be empty.[/red]")
        raise typer.Exit(1)

    issue_date = date.today() if issue_today else resolve_issue_date()

    try:
        xml_content, context_log = render_invoice(profile, invoice_number, amount, issue_date)
    except Exception as e:
        err_console.print(f"[red]Template rendering failed:[/red] {e}")
        raise typer.Exit(1)

    console.print("[dim]Variables:[/dim]")
    for var, value, source in context_log:
        console.print(f"  [dim]{var:<24} {value:<20} {source}[/dim]", highlight=False)
    console.print()

    errors = validate_invoice_xml(xml_content)
    if errors:
        err_console.print("[red]Generated XML failed schema validation:[/red]")
        for e in errors:
            err_console.print(f"  [red]•[/red] {e}")
        raise typer.Exit(1)

    out_path = output or Path.cwd() / output_filename(profile, invoice_number)
    out_path.write_text(xml_content, encoding="utf-8")

    invoice = parse_invoice(xml_content)
    render_invoice_detail(invoice, xml_path=str(out_path))
    console.print(f"[green]✓[/green] {out_path}", highlight=False)

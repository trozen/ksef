from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

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
    get_invoice_xml,
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


@app.command()
def show(
    ctx: typer.Context,
    query: Optional[str] = typer.Argument(None, help="List number (#1, #2), invoice number, seller name, or KSeF number"),
) -> None:
    """Show invoice details including line items."""
    if query is None:
        console.print("Usage: ksef show <query>")
        console.print()
        console.print("Examples:")
        console.print("  ksef show 1          [dim]show invoice #1 from the list[/dim]")
        console.print("  ksef show FV/1/01    [dim]match by invoice number[/dim]")
        console.print("  ksef show Januszex       [dim]match by seller name[/dim]")
        raise typer.Exit(0)

    cfg = load_config(ctx.obj["config_path"])
    all_invoices = load_all_metadata(cfg)

    # Resolve #N references to list position
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

    xml_content = get_invoice_xml(cfg, ksef_number)
    if not xml_content:
        err_console.print(f"[red]XML file not found for:[/red] {ksef_number}")
        raise typer.Exit(1)

    invoice = parse_invoice(xml_content, ksef_number=ksef_number)
    invoice.synced_at = meta.get("synced_at", "")

    xml_path = get_invoice_xml_path(cfg, ksef_number)
    qr_base_url = KSEF_QR_BASE_URLS.get(cfg.environment, KSEF_QR_BASE_URLS["prod"])
    render_invoice_detail(invoice, xml_path=str(xml_path) if xml_path else None, qr_base_url=qr_base_url)

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

import click
import requests
import typer

from ksef import __version__

from ksef.config import load_config
from ksef.display import (
    console,
    err_console,
    render_dashboard,
    render_invoice_detail,
    render_invoice_list,
    render_sync_summary,
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
from ksef.sync import run_sync

app = typer.Typer(
    name="ksef",
    help="Browse and manage Polish e-invoices from KSeF.",
    invoke_without_command=True,
    no_args_is_help=False,
    context_settings={"help_option_names": ["-h", "--help"]},
)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"ksef {__version__}")
        raise typer.Exit()


def _print_commands_hint() -> None:
    commands = [
        ("ksef sync", "Fetch new invoices from KSeF"),
        ("ksef list", "List all invoices"),
        ("ksef show", "Show invoice details"),
        ("ksef -h", "Full help"),
    ]
    for cmd, desc in commands:
        console.print(f"  [bold]{cmd}[/bold]  [dim]{desc}[/dim]")


@app.callback(invoke_without_command=True)
def dashboard(
    ctx: typer.Context,
    version: Optional[bool] = typer.Option(None, "--version", "-V", callback=_version_callback, is_eager=True, help="Show version and exit"),
) -> None:
    """Show dashboard with config summary and recent invoices."""
    if ctx.invoked_subcommand is not None:
        return
    typer.echo(f"ksef {__version__}")
    cfg = load_config()
    sync_state = load_sync_state(cfg)
    invoices = load_all_metadata(cfg)
    render_dashboard(cfg, sync_state, invoices)
    console.print()
    console.print("Commands:")
    _print_commands_hint()


@app.command(hidden=True)
def help(ctx: typer.Context) -> None:
    """Show help."""
    # Re-invoke with --help so typer prints the full help text
    click.echo(ctx.parent.get_help())


@app.command()
def sync(
    date_from: Optional[str] = typer.Option(None, "--from", help="Start date (YYYY-MM-DD)"),
    date_to: Optional[str] = typer.Option(None, "--to", help="End date (YYYY-MM-DD)"),
    max_invoices: Optional[int] = typer.Option(None, "--max", "-n", help="Max invoices to fetch"),
    force: bool = typer.Option(False, "--force", "-f", help="Force sync last 30 days"),
) -> None:
    """Sync invoices from KSeF (incremental by default)."""
    cfg = load_config()

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
        err_console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)


@app.command(name="list")
def list_invoices(
    limit: int = typer.Option(20, "--limit", "-n", help="Number of invoices to show"),
    seller: Optional[str] = typer.Option(None, "--seller", "-s", help="Filter by seller name or NIP"),
) -> None:
    """List invoices."""
    cfg = load_config()

    if seller:
        invoices = search_invoices(cfg, seller)
    else:
        invoices = load_all_metadata(cfg)

    render_invoice_list(invoices, limit=limit)


@app.command()
def show(
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

    cfg = load_config()
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
    render_invoice_detail(invoice, xml_path=str(xml_path) if xml_path else None)

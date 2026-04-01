from __future__ import annotations

import rich.box
from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.table import Table

from ksef.models import Invoice

console = Console()
err_console = Console(stderr=True)


def format_nip(nip: str) -> str:
    """Format NIP: 1234567890 → 123-456-78-90."""
    nip = nip.replace("-", "").replace(" ", "")
    if len(nip) == 10:
        return f"{nip[:3]}-{nip[3:6]}-{nip[6:8]}-{nip[8:]}"
    return nip


def format_amount(amount_str: str, currency: str = "PLN") -> str:
    """Polish amount formatting: 1 234,56 PLN."""
    if not amount_str:
        return ""
    try:
        value = float(amount_str)
    except ValueError:
        return amount_str

    # Format with 2 decimal places, comma separator, space thousands
    integer_part = int(abs(value))
    decimal_part = f"{abs(value) - integer_part:.2f}"[2:]

    # Add thousand separators
    int_str = f"{integer_part:,}".replace(",", "\u00a0")  # non-breaking space

    sign = "-" if value < 0 else ""
    formatted = f"{sign}{int_str},{decimal_part}"
    if currency:
        formatted += f" {currency}"
    return formatted


def render_dashboard(cfg, sync_state: dict | None, invoices: list[dict]) -> None:
    # Header panel
    header_lines = [
        f"NIP: [bold]{format_nip(cfg.nip)}[/bold]    Environment: [bold]{cfg.environment}[/bold]",
    ]
    if sync_state:
        last_sync = sync_state.get("last_sync_at", "never")
        fetched = sync_state.get("last_sync_invoices_fetched", 0)
        header_lines.append(f"Last sync: [dim]{last_sync}[/dim]  ({fetched} invoices)")
    else:
        header_lines.append("Last sync: [dim]never[/dim]")
    header_lines.append(f"Invoices stored: [bold]{len(invoices)}[/bold]")

    console.print(Panel("\n".join(header_lines), title="KSeF", border_style="blue"))

    if not invoices:
        console.print("[dim]No invoices yet. Run [bold]ksef sync[/bold] to fetch invoices.[/dim]")
        return

    _render_invoice_lines(invoices[:10])


def render_invoice_list(invoices: list[dict], limit: int = 20) -> None:
    if not invoices:
        console.print("[dim]No invoices found.[/dim]")
        return

    _render_invoice_lines(invoices[:limit], detailed=True, spaced=True)

    if len(invoices) > limit:
        console.print(f"[dim]Showing {limit} of {len(invoices)} invoices. Use -n to show more.[/dim]")


def _render_invoice_lines(invoices: list[dict], detailed: bool = False, spaced: bool = False) -> None:
    for i, inv in enumerate(invoices, 1):
        currency = inv.get("currency", "PLN")
        date = inv.get("issue_date", "")
        number = escape(inv.get("invoice_number", ""))
        seller = escape(inv.get("seller_name", ""))
        gross = format_amount(inv.get("gross_amount", ""), currency)
        due = inv.get("due_date", "")

        line1 = f"[dim]#{i:<3}[/dim] [cyan]{date}[/cyan]  [bold]{number:<20}[/bold] [green]{gross:>14}[/green]"
        if due:
            line1 += f"  [dim]due {due}[/dim]"

        line2 = f"     {seller}"
        if detailed:
            nip = format_nip(inv.get("seller_nip", ""))
            net = format_amount(inv.get("net_amount", ""), "")
            vat = format_amount(inv.get("vat_amount", ""), "")
            line2 += f"  [dim]NIP {nip}  net {net}  VAT {vat}[/dim]"

        if spaced and i > 1:
            console.print()
        console.print(line1, highlight=False)
        console.print(line2, highlight=False)
    if spaced:
        console.print()


def render_invoice_detail(invoice: Invoice, xml_path: str | None = None) -> None:
    currency = invoice.currency

    # Header in a rounded panel
    header = []
    header.append(f"  [bold]Invoice:[/bold]   {escape(invoice.invoice_number)}  [dim]({invoice.invoice_type})[/dim]")
    header.append(f"  [bold]KSeF:[/bold]      {invoice.ksef_number}")
    header.append(f"  [bold]Seller:[/bold]    {escape(invoice.seller.name)}")
    header.append(f"             [dim]NIP {format_nip(invoice.seller.nip)}[/dim]")
    header.append(f"  [bold]Buyer:[/bold]     {escape(invoice.buyer.name)}")
    header.append(f"             [dim]NIP {format_nip(invoice.buyer.nip)}[/dim]")
    header.append("")
    header.append(f"  Issue date:  [cyan]{invoice.issue_date}[/cyan]    Currency: {currency}")
    header.append(f"  Net:         {format_amount(invoice.net_amount, currency)}")
    header.append(f"  VAT:         {format_amount(invoice.vat_amount, currency)}")
    header.append(f"  [bold]Gross:       {format_amount(invoice.gross_amount, currency)}[/bold]")

    console.print(Panel(
        "\n".join(header),
        border_style="dim",
        box=rich.box.ROUNDED,
    ))

    # Line items
    if invoice.line_items:
        items_table = Table(
            show_header=True, header_style="bold dim",
            padding=(0, 1), box=rich.box.SIMPLE_HEAVY, show_edge=False,
        )
        items_table.add_column("#", justify="right", style="dim")
        items_table.add_column("Description")
        items_table.add_column("Qty", justify="right")
        items_table.add_column("Unit")
        items_table.add_column("Unit Price", justify="right")
        items_table.add_column("Net", justify="right")
        items_table.add_column("VAT %", justify="right", style="dim")
        items_table.add_column("Gross", justify="right")

        for item in invoice.line_items:
            gross = _line_gross(item.net_amount, item.vat_rate)
            items_table.add_row(
                str(item.line_number),
                _truncate(item.description, 50),
                item.quantity,
                item.unit,
                format_amount(item.unit_price, ""),
                format_amount(item.net_amount, ""),
                f"{item.vat_rate}%",
                format_amount(gross, ""),
            )
        items_table.add_section()
        items_table.add_row(
            "", "", "", "", "", "", "",
            f"[bold]{format_amount(invoice.gross_amount, currency)}[/bold]",
        )
        console.print(items_table)

    # Payment
    pay = invoice.payment
    if pay.due_date or pay.bank_account:
        console.print("  [bold]Payment[/bold]")
        if pay.due_date:
            console.print(f"  Due date:    [cyan]{pay.due_date}[/cyan]")
        if pay.payment_form:
            console.print(f"  Method:      {pay.payment_form}")
        if pay.bank_account:
            console.print(f"  Account:     {pay.bank_account}")
        if pay.bank_name:
            console.print(f"  Bank:        {pay.bank_name}")
        if pay.swift:
            console.print(f"  SWIFT:       {pay.swift}")
        console.print()

    # Extra fields (DodatkowyOpis)
    if invoice.extras:
        for key, val in invoice.extras.items():
            console.print(f"  [dim]{escape(key)}:[/dim]  {escape(val)}")
        console.print()

    if xml_path:
        console.print(f"  [dim]XML: {xml_path}[/dim]")
        console.print()


def render_sync_summary(new_count: int, total_count: int) -> None:
    if new_count == 0:
        console.print("[dim]No new invoices.[/dim]")
    else:
        console.print(f"[green]Synced {new_count} new invoice(s).[/green] Total stored: {total_count}.")


def _line_gross(net_str: str, vat_rate_str: str) -> str:
    try:
        net = float(net_str)
        rate = float(vat_rate_str)
        return f"{net * (1 + rate / 100):.2f}"
    except (ValueError, TypeError):
        return ""


def _truncate(text: str, max_len: int) -> str:
    if len(text) <= max_len:
        return text
    return text[: max_len - 1] + "…"

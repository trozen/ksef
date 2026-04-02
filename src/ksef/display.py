from __future__ import annotations

import base64
import hashlib
import io
from pathlib import Path

import qrcode
import rich.box
from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.table import Table

from ksef.models import Invoice

console = Console(highlight=False)
err_console = Console(stderr=True, highlight=False)


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


def render_dashboard(cfg, sync_state: dict | None, invoices: list[dict], pending_count: int = 0) -> None:
    # Header panel
    header_lines = [
        f"NIP: [bold]{format_nip(cfg.nip)}[/bold]    Environment: [bold]{cfg.environment}[/bold]",
    ]
    if sync_state:
        buyer_state = sync_state.get("buyer", {})
        seller_state = sync_state.get("seller", {})
        last_syncs = [s["last_sync_at"] for s in (buyer_state, seller_state) if s.get("last_sync_at")]
        last_sync = max(last_syncs) if last_syncs else "never"
        fetched_buyer = buyer_state.get("last_sync_invoices_fetched", 0)
        fetched_seller = seller_state.get("last_sync_invoices_fetched", 0)
        header_lines.append(f"Last sync: [dim]{last_sync}[/dim]  ([cyan]↓{fetched_buyer}[/cyan] in, [yellow]↑{fetched_seller}[/yellow] out)")
    else:
        header_lines.append("Last sync: [dim]never[/dim]")
    header_lines.append(f"Invoices stored: [bold]{len(invoices)}[/bold]")

    console.print(Panel("\n".join(header_lines), title="KSeF", border_style="blue"))

    if pending_count:
        console.print(f"[yellow]⚠ {pending_count} pending upload session(s) awaiting UPO. Run [bold]ksef sync[/bold] to resolve.[/yellow]")

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
        is_seller = inv.get("direction") == "seller"

        direction_tag = "[yellow]↑[/yellow]" if is_seller else "[cyan]↓[/cyan]"
        amount_style = "yellow" if is_seller else "green"

        line1 = f"[dim]#{i:<3}[/dim] {direction_tag} [cyan]{date}[/cyan]  [bold]{number:<20}[/bold] [{amount_style}]{gross:>14}[/{amount_style}]"
        if due:
            line1 += f"  [dim]due {due}[/dim]"

        line2 = f"      "
        if is_seller:
            line2 += f"[yellow]{seller}[/yellow]"
        else:
            line2 += seller
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


def render_invoice_detail(invoice: Invoice, xml_path: str | None = None, qr_base_url: str = "") -> None:
    currency = invoice.currency

    # Header in a rounded panel
    header = []
    header.append(f"  [bold]Invoice:[/bold]   {escape(invoice.invoice_number)}  [dim]({invoice.invoice_type})[/dim]")
    ksef_str = invoice.ksef_number if invoice.ksef_number else "[dim]not submitted[/dim]"
    header.append(f"  [bold]KSeF:[/bold]      {ksef_str}")
    header.append(f"  [bold]Seller:[/bold]    {escape(invoice.seller.name)}")
    header.append(f"             [dim]NIP {format_nip(invoice.seller.nip)}[/dim]")
    if invoice.seller.address:
        header.append(f"             [dim]{escape(invoice.seller.address)}[/dim]")
    if invoice.seller.phone:
        header.append(f"             [dim]{escape(invoice.seller.phone)}[/dim]")
    if invoice.seller.email:
        header.append(f"             [dim]{escape(invoice.seller.email)}[/dim]")
    header.append(f"  [bold]Buyer:[/bold]     {escape(invoice.buyer.name)}")
    if invoice.buyer.nip:
        header.append(f"             [dim]NIP {format_nip(invoice.buyer.nip)}[/dim]")
    if invoice.buyer.address:
        header.append(f"             [dim]{escape(invoice.buyer.address)}[/dim]")
    if invoice.buyer.phone:
        header.append(f"             [dim]{escape(invoice.buyer.phone)}[/dim]")
    if invoice.buyer.email:
        header.append(f"             [dim]{escape(invoice.buyer.email)}[/dim]")
    header.append("")
    header.append(f"  Issue date:  [cyan]{invoice.issue_date}[/cyan]    Currency: {currency}")
    if invoice.period_from or invoice.period_to:
        header.append(f"  Period:      [cyan]{invoice.period_from}[/cyan] – [cyan]{invoice.period_to}[/cyan]")
    header.append(f"  Net:         {format_amount(invoice.net_amount, currency)}")
    header.append(f"  VAT:         {format_amount(invoice.vat_amount, currency)}")
    header.append(f"  [bold]Gross:       {format_amount(invoice.gross_amount, currency)}[/bold]")
    for note in invoice.annotations:
        header.append(f"  [yellow]{escape(note)}[/yellow]")

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
        items_table.add_column("Description", max_width=40)
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
                _truncate(item.description, 40 * 3),
                item.quantity,
                item.unit,
                format_amount(item.unit_price, ""),
                format_amount(item.net_amount, ""),
                format_vat_rate(item.vat_rate),
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

    # Contract numbers
    if invoice.contract_numbers:
        console.print(f"  [bold]Contract(s):[/bold] {', '.join(escape(c) for c in invoice.contract_numbers)}")
        console.print()

    # Footer / company registration info
    if invoice.footer or invoice.krs or invoice.regon:
        for line in invoice.footer:
            console.print(f"  [dim]{escape(line)}[/dim]")
        parts = []
        if invoice.krs:
            parts.append(f"KRS {invoice.krs}")
        if invoice.regon:
            parts.append(f"REGON {invoice.regon}")
        if parts:
            console.print(f"  [dim]{', '.join(parts)}[/dim]")
        console.print()

    if xml_path:
        console.print(f"  [dim]XML: {xml_path}[/dim]")

    if invoice.ksef_number and xml_path and qr_base_url:
        try:
            xml_bytes = Path(xml_path).read_bytes()
            url = _verification_url(invoice.seller.nip, invoice.issue_date, xml_bytes, qr_base_url)
            console.print(f"  [dim]Verify: {url}[/dim]")
            console.print()
            _print_qr(url, label=invoice.ksef_number)
        except OSError:
            pass
    else:
        console.print()


def _verification_url(nip: str, issue_date: str, xml_bytes: bytes, base_url: str) -> str:
    digest = hashlib.sha256(xml_bytes).digest()
    hash_b64 = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    y, m, d = issue_date.split("-")
    date_str = f"{d}-{m}-{y}"
    return f"{base_url}/invoice/{nip}/{date_str}/{hash_b64}"


def _print_qr(url: str, label: str = "") -> None:
    qr = qrcode.QRCode(
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=1,
        border=1,
    )
    qr.add_data(url)
    qr.make(fit=True)
    buf = io.StringIO()
    qr.print_ascii(out=buf, invert=True)
    console.print(buf.getvalue(), end="")
    if label:
        console.print(f"  [dim]{escape(label)}[/dim]", highlight=False)
    console.print()


def render_sync_summary(new_buyer: int, new_seller: int, total_count: int) -> None:
    total_new = new_buyer + new_seller
    if total_new == 0:
        console.print("[dim]No new invoices.[/dim]")
    else:
        parts = []
        if new_buyer:
            parts.append(f"[cyan]↓{new_buyer} in[/cyan]")
        if new_seller:
            parts.append(f"[yellow]↑{new_seller} out[/yellow]")
        console.print(f"[green]Synced {total_new} new invoice(s)[/green] ({', '.join(parts)}). Total stored: {total_count}.")


def format_vat_rate(rate: str) -> str:
    """Normalize FA(3) VAT rate codes to display form."""
    if not rate:
        return ""
    if rate.startswith("np"):
        return "np."
    if rate == "zw":
        return "zw."
    if rate == "oo":
        return "oo"
    # numeric rate — add %
    try:
        float(rate)
        return f"{rate}%"
    except ValueError:
        return rate


def _line_gross(net_str: str, vat_rate_str: str) -> str:
    try:
        net = float(net_str)
        rate = float(vat_rate_str)
        return f"{net * (1 + rate / 100):.2f}"
    except (ValueError, TypeError):
        # np./zw./oo — no VAT, gross = net
        if net_str:
            try:
                return f"{float(net_str):.2f}"
            except ValueError:
                pass
        return ""


def _truncate(text: str, max_len: int) -> str:
    if len(text) <= max_len:
        return text
    return text[: max_len - 1] + "…"

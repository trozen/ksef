from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

from ksef.client import KSeFClient, KSeFError
from ksef.config import Config
from ksef.display import console, err_console
from ksef.parser import parse_invoice
from ksef.store import SENT, add_invoice, add_invoice_upo, has_invoice
from ksef.sync import _authenticate
from ksef.validate import validate_invoice_xml

_STATUS_OK = 200
_STATUS_DUPLICATE = 440
_STATUS_VALIDATION_ERROR = 450


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_pending(cfg: Config) -> dict:
    if cfg.pending_sessions_path.exists():
        try:
            return json.loads(cfg.pending_sessions_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def _save_pending_session(cfg: Config, session_ref: str, data: dict) -> None:
    pending = _load_pending(cfg)
    pending[session_ref] = data
    cfg.data_path.mkdir(parents=True, exist_ok=True)
    cfg.pending_sessions_path.write_text(
        json.dumps(pending, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _remove_pending_session(cfg: Config, session_ref: str) -> None:
    pending = _load_pending(cfg)
    if session_ref in pending:
        del pending[session_ref]
        cfg.pending_sessions_path.write_text(
            json.dumps(pending, ensure_ascii=False, indent=2), encoding="utf-8"
        )


def _store_sent_invoice(cfg: Config, xml_str: str, ksef_number: str) -> str:
    """Parse, store XML+metadata in sent/ reference dir. Returns issue_date."""
    invoice = parse_invoice(xml_str, ksef_number=ksef_number)
    invoice.synced_at = _iso_now()
    if not has_invoice(cfg, ksef_number, SENT):
        add_invoice(cfg, ksef_number, invoice.issue_date, invoice.to_metadata(), xml_str, SENT)
    return invoice.issue_date


def run_send(cfg: Config, xml_path: Path, xml_bytes: bytes, upo_path: Path | None = None) -> None:
    xml_str = xml_bytes.decode("utf-8")

    errors = validate_invoice_xml(xml_str)
    if errors:
        raise RuntimeError("Invoice XML failed schema validation:\n" + "\n".join(f"  {e}" for e in errors))

    client = KSeFClient(base_url=cfg.base_url)
    access_token = _authenticate(client, cfg)

    console.print("[dim]Opening session...[/dim]")
    session_ref, aes_key, iv = client.open_online_session(access_token)

    console.print(f"[dim]Sending {xml_path.name}...[/dim]")
    result = client.send_invoice(access_token, session_ref, xml_bytes, aes_key, iv)
    invoice_ref = result["referenceNumber"]

    _save_pending_session(cfg, session_ref, {
        "invoice_ref": invoice_ref,
        "submitted_at": _iso_now(),
        "user_upo_path": str(upo_path) if upo_path else None,
    })
    console.print(f"[dim]Submitted. Session: {session_ref}[/dim]")

    console.print("[dim]Waiting for processing...[/dim]")
    try:
        final_status = _poll_invoice_status(client, access_token, session_ref, invoice_ref)
    finally:
        console.print("[dim]Closing session...[/dim]")
        try:
            client.close_online_session(access_token, session_ref)
        except RuntimeError as e:
            err_console.print(f"[yellow]Warning:[/yellow] could not close session: {e}")
            err_console.print(f"[dim]Run [bold]ksef sync[/bold] or [bold]ksef session {session_ref}[/bold] to download UPO.[/dim]")

    ksef_number = final_status.get("ksefNumber") or ""

    # Store in seller dir now that we have the KSeF number
    issue_date = _store_sent_invoice(cfg, xml_str, ksef_number)

    # Update pending with ksef_number so check_pending_sessions can recover if needed
    _save_pending_session(cfg, session_ref, {
        "invoice_ref": invoice_ref,
        "submitted_at": _iso_now(),
        "ksef_number": ksef_number,
        "issue_date": issue_date,
        "user_upo_path": str(upo_path) if upo_path else None,
    })

    console.print("[dim]Downloading UPO...[/dim]")
    _download_and_store_upo(cfg, client, access_token, session_ref, invoice_ref,
                            final_status, ksef_number, issue_date, upo_path)

    console.print(f"[green]Invoice accepted.[/green]  KSeF number: [bold]{ksef_number}[/bold]")


def _download_and_store_upo(
    cfg: Config,
    client: KSeFClient,
    access_token: str,
    session_ref: str,
    invoice_ref: str,
    status: dict,
    ksef_number: str,
    issue_date: str,
    user_upo_path: Path | None,
) -> None:
    try:
        upo_url = status.get("upoDownloadUrl")
        if upo_url:
            upo_xml = client.download_upo_from_url(upo_url)
        else:
            upo_xml = client.download_upo(access_token, session_ref, invoice_ref)

        # Always store in seller dir alongside the invoice
        stored_path = add_invoice_upo(cfg, ksef_number, issue_date, upo_xml, SENT)
        console.print(f"UPO saved to: {stored_path}")

        # Also write to user-specified path if given
        if user_upo_path:
            user_upo_path.write_text(upo_xml, encoding="utf-8")
            console.print(f"UPO also saved to: {user_upo_path}")

        _remove_pending_session(cfg, session_ref)
    except RuntimeError as e:
        err_console.print(f"[yellow]Warning:[/yellow] could not download UPO: {e}")
        err_console.print(f"[dim]Run [bold]ksef sync[/bold] or [bold]ksef session {session_ref}[/bold] to download UPO later.[/dim]")


def check_pending_sessions(cfg: Config, client: KSeFClient, access_token: str) -> None:
    """Attempt to resolve any pending sessions — download UPO or mark failed ones."""
    pending = _load_pending(cfg)
    if not pending:
        return

    console.print(f"[dim]Checking {len(pending)} pending session(s)...[/dim]")

    for session_ref, info in list(pending.items()):
        invoice_ref = info.get("invoice_ref")
        try:
            invoices = client.list_session_invoices(access_token, session_ref).get("invoices") or []
        except RuntimeError as e:
            err_console.print(f"[yellow]Could not check session {session_ref}:[/yellow] {e}")
            continue

        for inv in invoices:
            if inv.get("referenceNumber") != invoice_ref:
                continue

            inv_st = inv.get("status", {})
            code = inv_st.get("code")
            desc = inv_st.get("description", "")

            if code == _STATUS_OK:
                ksef_number = inv.get("ksefNumber") or info.get("ksef_number") or ""
                issue_date = info.get("issue_date", "")
                upo_url = inv.get("upoDownloadUrl")
                user_upo_path = info.get("user_upo_path")

                # Re-download XML from KSeF if not stored yet
                if ksef_number and not has_invoice(cfg, ksef_number, SENT):
                    try:
                        xml_str = client.download_invoice_xml(access_token, ksef_number)
                        issue_date = _store_sent_invoice(cfg, xml_str, ksef_number)
                    except RuntimeError as e:
                        err_console.print(f"[yellow]Could not download invoice XML for {ksef_number}:[/yellow] {e}")

                if ksef_number and issue_date:
                    _download_and_store_upo(
                        cfg, client, access_token, session_ref, invoice_ref,
                        inv, ksef_number, issue_date,
                        Path(user_upo_path) if user_upo_path else None,
                    )
                    console.print(f"[green]Resolved pending session {session_ref}[/green]  KSeF: {ksef_number}")
                else:
                    err_console.print(f"[yellow]Session {session_ref}: accepted but missing KSeF number — run [bold]ksef session {session_ref}[/bold][/yellow]")

            elif code and code >= 400:
                err_console.print(f"[yellow]Session {session_ref}: invoice failed — {code} {desc}[/yellow]")
                _remove_pending_session(cfg, session_ref)
            else:
                console.print(f"[dim]Session {session_ref}: still processing ({code} {desc})[/dim]")


def run_check_session(cfg: Config, session_ref: str) -> None:
    client = KSeFClient(base_url=cfg.base_url)
    access_token = _authenticate(client, cfg)

    status = client.session_status(access_token, session_ref)
    st = status.get("status", {})
    code = st.get("code")
    desc = st.get("description", "")

    if code == 200:
        status_str = f"[green]{code} {desc}[/green]"
    elif code and code >= 400:
        status_str = f"[red]{code} {desc}[/red]"
    else:
        status_str = f"[dim]{code} {desc}[/dim]"

    console.print(f"Session [bold]{session_ref}[/bold]")
    console.print(f"  Status:  {status_str}")
    if status.get("dateCreated"):
        console.print(f"  Created: [dim]{status['dateCreated']}[/dim]")
    if status.get("validUntil"):
        console.print(f"  Valid until: [dim]{status['validUntil']}[/dim]")
    total = status.get("invoiceCount")
    if total is not None:
        ok = status.get("successfulInvoiceCount", 0)
        failed = status.get("failedInvoiceCount", 0)
        console.print(f"  Invoices: {ok}/{total} accepted, {failed} failed")
    for d in st.get("details") or []:
        console.print(f"  [dim]{d}[/dim]")

    invoices = client.list_session_invoices(access_token, session_ref).get("invoices") or []
    if not invoices:
        console.print("[dim]No invoices in this session.[/dim]")
        return

    pending = _load_pending(cfg)
    session_pending = pending.get(session_ref, {})

    console.print()
    for inv in invoices:
        invoice_ref = inv.get("referenceNumber")
        ksef_number = inv.get("ksefNumber") or ""
        invoice_number = inv.get("invoiceNumber") or ""
        inv_st = inv.get("status", {})
        inv_code = inv_st.get("code")
        inv_desc = inv_st.get("description", "")

        if inv_code == _STATUS_OK:
            inv_status_str = f"[green]{inv_code} {inv_desc}[/green]"
            if ksef_number:
                inv_status_str += f"  KSeF: [bold]{ksef_number}[/bold]"
        elif inv_code and inv_code >= 400:
            inv_status_str = f"[red]{inv_code} {inv_desc}[/red]"
        else:
            inv_status_str = f"[dim]{inv_code} {inv_desc}[/dim]"

        console.print(f"  Invoice [dim]{invoice_ref}[/dim]" + (f"  {invoice_number}" if invoice_number else ""))
        console.print(f"    Status: {inv_status_str}", highlight=False)
        for d in inv_st.get("details") or []:
            console.print(f"    [dim]{d}[/dim]")
        for k, v in (inv_st.get("extensions") or {}).items():
            console.print(f"    [dim]{k}: {v}[/dim]")

        if inv_code == _STATUS_OK:
            issue_date = session_pending.get("issue_date", "")
            upo_url = inv.get("upoDownloadUrl")
            user_upo_path = session_pending.get("user_upo_path")

            if not issue_date and ksef_number:
                # Try to get issue_date from local store or re-download XML
                try:
                    xml_str = client.download_invoice_xml(access_token, ksef_number)
                    issue_date = _store_sent_invoice(cfg, xml_str, ksef_number)
                except RuntimeError:
                    pass

            if issue_date and ksef_number:
                _download_and_store_upo(
                    cfg, client, access_token, session_ref, invoice_ref,
                    inv, ksef_number, issue_date,
                    Path(user_upo_path) if user_upo_path else None,
                )
            elif not upo_url:
                console.print(f"    [dim]UPO not yet available.[/dim]")


def _poll_invoice_status(
    client: KSeFClient,
    access_token: str,
    session_ref: str,
    invoice_ref: str,
    attempts: int = 60,
    interval_s: int = 2,
) -> dict:
    """Poll until the invoice is processed. Returns the final status dict."""
    for _ in range(attempts):
        st = client.invoice_status(access_token, session_ref, invoice_ref)
        status = st.get("status", {})
        code = status.get("code")
        desc = status.get("description", "")
        details = status.get("details") or []

        if code == _STATUS_OK:
            return st
        if code == _STATUS_DUPLICATE:
            ext = status.get("extensions") or {}
            original = ext.get("originalKsefNumber", "unknown")
            raise KSeFError(f"Invoice rejected: duplicate (original KSeF: {original})", raw=st)
        if code and code >= 400:
            detail_str = "; ".join(details) if details else desc
            raise KSeFError(f"Invoice rejected: {code} {desc}" + (f" — {detail_str}" if detail_str != desc else ""), raw=st)

        time.sleep(interval_s)

    raise RuntimeError("Timed out waiting for invoice processing")

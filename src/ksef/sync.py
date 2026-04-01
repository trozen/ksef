from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

from ksef.client import KSeFClient
from ksef.config import Config
from ksef.display import console, err_console, render_sync_summary
from ksef.parser import parse_invoice
from ksef.store import add_invoice, has_invoice, load_all_metadata, load_sync_state, save_sync_state


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_session_cache(cfg: Config) -> dict | None:
    if cfg.session_cache_path.exists():
        try:
            return json.loads(cfg.session_cache_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None
    return None


def _save_session_cache(cfg: Config, data: dict) -> None:
    cfg.data_path.mkdir(parents=True, exist_ok=True)
    cfg.session_cache_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _authenticate(client: KSeFClient, cfg: Config) -> str:
    """Returns an access token, reusing cached session if possible."""
    cached = _load_session_cache(cfg)

    if cached:
        access_token = cached.get("access_token")
        refresh_token = cached.get("refresh_token")

        if access_token:
            # Try using the cached access token — it may be expired
            try:
                client.query_invoice_metadata(access_token, {
                    "subjectType": "Subject2",
                    "dateRange": {"dateType": "PermanentStorage", "from": "2099-01-01T00:00:00+00:00", "to": "2099-01-01T00:00:01+00:00"},
                })
                return access_token
            except RuntimeError:
                pass

        if refresh_token:
            try:
                refreshed = client.refresh_access_token(refresh_token)
                new_access = refreshed["accessToken"]["token"]
                cached["access_token"] = new_access
                cached["refreshed_at"] = _iso_now()
                _save_session_cache(cfg, cached)
                return new_access
            except RuntimeError:
                pass

    # Full auth flow
    ksef_token = Path(cfg.token_path).read_text(encoding="utf-8").strip()

    console.print("[dim]Authenticating with KSeF...[/dim]")
    chall = client.auth_challenge()
    challenge = chall["challenge"]
    timestamp_ms = int(chall["timestampMs"])

    init = client.start_auth_with_ksef_token(
        ksef_token=ksef_token,
        nip=cfg.nip,
        challenge=challenge,
        timestamp_ms=timestamp_ms,
    )
    auth_ref = init["referenceNumber"]
    auth_jwt = init["authenticationToken"]["token"]

    # Poll until ready
    for _ in range(60):
        st = client.auth_status(auth_ref, auth_jwt)
        code = st.get("status", {}).get("code")
        if code == 200:
            break
        if code and code >= 400:
            raise RuntimeError(f"Authentication failed: {st}")
        time.sleep(2)
    else:
        raise RuntimeError("Authentication polling timed out")

    tokens = client.redeem_tokens(auth_jwt)

    _save_session_cache(cfg, {
        "access_token": tokens.access_token,
        "refresh_token": tokens.refresh_token,
        "access_valid_until": tokens.access_valid_until,
        "refresh_valid_until": tokens.refresh_valid_until,
        "created_at": _iso_now(),
        "environment": cfg.environment,
        "nip": cfg.nip,
    })

    console.print("[green]Authenticated.[/green]")
    return tokens.access_token


def _determine_date_range(cfg: Config, date_from: str | None, date_to: str | None) -> tuple[str, str]:
    """Determine query date range, using sync state for incremental sync."""
    if date_to:
        to_dt = date_to if "T" in date_to else f"{date_to}T23:59:59+00:00"
    else:
        to_dt = _iso_now()

    if date_from:
        from_dt = date_from if "T" in date_from else f"{date_from}T00:00:00+00:00"
    else:
        sync_state = load_sync_state(cfg)
        if sync_state and sync_state.get("last_sync_date_to"):
            from_dt = sync_state["last_sync_date_to"]
        else:
            from_dt = f"{cfg.sync.date_from}T00:00:00+00:00"

    return from_dt, to_dt


def run_sync(
    cfg: Config,
    date_from: str | None = None,
    date_to: str | None = None,
    max_invoices: int | None = None,
) -> None:
    max_count = max_invoices or cfg.sync.max_per_sync
    from_dt, to_dt = _determine_date_range(cfg, date_from, date_to)

    console.print(f"[dim]Syncing invoices from {from_dt} to {to_dt}[/dim]")

    client = KSeFClient(base_url=cfg.base_url)
    access_token = _authenticate(client, cfg)

    filters = {
        "subjectType": "Subject2",
        "dateRange": {
            "dateType": "PermanentStorage",
            "from": from_dt,
            "to": to_dt,
        },
    }

    meta_response = client.query_invoice_metadata(access_token, filters)
    invoices_meta = meta_response.get("invoices") or []

    if not invoices_meta:
        console.print("[dim]No invoices found in date range.[/dim]")
        save_sync_state(cfg, {
            "last_sync_at": _iso_now(),
            "last_sync_date_to": to_dt,
            "last_sync_invoices_fetched": 0,
        })
        return

    new_count = 0
    for inv_meta in invoices_meta:
        if new_count >= max_count:
            break

        ksef_number = inv_meta.get("ksefNumber")
        if not ksef_number:
            continue

        if has_invoice(cfg, ksef_number):
            continue

        console.print(f"  [dim]Downloading {ksef_number}...[/dim]")
        xml_content = client.download_invoice_xml(access_token, ksef_number)

        invoice = parse_invoice(xml_content, ksef_number=ksef_number)
        invoice.synced_at = _iso_now()
        metadata = invoice.to_metadata()

        add_invoice(cfg, ksef_number, invoice.issue_date, metadata, xml_content)
        new_count += 1

    save_sync_state(cfg, {
        "last_sync_at": _iso_now(),
        "last_sync_date_to": to_dt,
        "last_sync_invoices_fetched": new_count,
    })

    total = len(load_all_metadata(cfg))
    render_sync_summary(new_count, total)

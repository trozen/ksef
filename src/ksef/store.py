from __future__ import annotations

import json
from pathlib import Path

from ksef.config import Config

BUYER = "buyer"
SELLER = "seller"
SENT = "sent"
DIRECTIONS = (BUYER, SELLER)  # directions synced from KSeF; SENT is separate


def _invoices_dir(cfg: Config, direction: str) -> Path:
    return cfg.invoices_dir / direction


def _month_dir(cfg: Config, issue_date: str, direction: str) -> Path:
    yyyymm = issue_date[:7].replace("-", "")
    return _invoices_dir(cfg, direction) / yyyymm


def _find_invoice_path(cfg: Config, ksef_number: str, ext: str) -> Path | None:
    """Scan both buyer and seller month dirs to find a file for the given ksef_number."""
    if not cfg.invoices_dir.exists():
        return None
    for direction in DIRECTIONS:
        dir_ = _invoices_dir(cfg, direction)
        if not dir_.exists():
            continue
        for month_dir in sorted(dir_.iterdir(), reverse=True):
            if not month_dir.is_dir():
                continue
            path = month_dir / f"{ksef_number}{ext}"
            if path.exists():
                return path
    return None


def add_invoice(cfg: Config, ksef_number: str, issue_date: str, meta: dict, xml_content: str, direction: str = BUYER) -> None:
    month = _month_dir(cfg, issue_date, direction)
    month.mkdir(parents=True, exist_ok=True)

    (month / f"{ksef_number}.xml").write_text(xml_content, encoding="utf-8")
    (month / f"{ksef_number}.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")


def add_invoice_upo(cfg: Config, ksef_number: str, issue_date: str, upo_xml: str, direction: str) -> Path:
    """Save UPO alongside the invoice files. Returns the path it was saved to."""
    month = _month_dir(cfg, issue_date, direction)
    month.mkdir(parents=True, exist_ok=True)
    path = month / f"{ksef_number}.upo.xml"
    path.write_text(upo_xml, encoding="utf-8")
    return path


def get_invoice_xml(cfg: Config, ksef_number: str) -> str | None:
    path = _find_invoice_path(cfg, ksef_number, ".xml")
    return path.read_text(encoding="utf-8") if path else None


def get_invoice_xml_path(cfg: Config, ksef_number: str) -> Path | None:
    return _find_invoice_path(cfg, ksef_number, ".xml")


def has_invoice(cfg: Config, ksef_number: str, direction: str) -> bool:
    dir_ = _invoices_dir(cfg, direction)
    if not dir_.exists():
        return False
    for month_dir in dir_.iterdir():
        if not month_dir.is_dir():
            continue
        if (month_dir / f"{ksef_number}.json").exists():
            return True
    return False


def load_all_metadata(cfg: Config) -> list[dict]:
    results = []
    for direction in DIRECTIONS:
        dir_ = _invoices_dir(cfg, direction)
        if not dir_.exists():
            continue
        for month_dir in dir_.iterdir():
            if not month_dir.is_dir():
                continue
            for json_file in month_dir.glob("*.json"):
                try:
                    meta = json.loads(json_file.read_text(encoding="utf-8"))
                    meta["direction"] = direction
                    results.append(meta)
                except (json.JSONDecodeError, OSError):
                    continue
    results.sort(key=lambda m: m.get("issue_date", ""), reverse=True)
    return results


def search_invoices(cfg: Config, query: str) -> list[dict]:
    query_lower = query.lower()
    return [
        meta for meta in load_all_metadata(cfg)
        if query_lower in " ".join([
            meta.get("ksef_number", ""),
            meta.get("invoice_number", ""),
            meta.get("seller_name", ""),
            meta.get("seller_nip", ""),
        ]).lower()
    ]


def resolve_invoice_id(cfg: Config, query: str) -> list[dict]:
    """Fuzzy ID resolution: exact ksef_number → exact invoice_number → partial match."""
    all_meta = load_all_metadata(cfg)

    for meta in all_meta:
        if meta.get("ksef_number") == query:
            return [meta]

    for meta in all_meta:
        if meta.get("invoice_number") == query:
            return [meta]

    query_lower = query.lower()
    return [
        meta for meta in all_meta
        if query_lower in " ".join([
            meta.get("ksef_number", ""),
            meta.get("invoice_number", ""),
            meta.get("seller_name", ""),
            meta.get("seller_nip", ""),
        ]).lower()
    ]


def load_sync_state(cfg: Config) -> dict:
    """Returns sync state with 'buyer' and 'seller' keys. Migrates old flat format on read."""
    if not cfg.sync_state_path.exists():
        return {}
    try:
        raw = json.loads(cfg.sync_state_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    # Migrate old flat format (had last_sync_at at top level)
    if "last_sync_at" in raw:
        return {BUYER: raw}
    return raw


def save_sync_state(cfg: Config, direction: str, state: dict) -> None:
    current = load_sync_state(cfg)
    current[direction] = state
    cfg.data_path.mkdir(parents=True, exist_ok=True)
    cfg.sync_state_path.write_text(
        json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8"
    )



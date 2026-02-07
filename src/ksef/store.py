from __future__ import annotations

import json
from pathlib import Path

from ksef.config import Config


def _month_dir(cfg: Config, issue_date: str) -> Path:
    yyyymm = issue_date[:7].replace("-", "")
    return cfg.invoices_dir / yyyymm


def _find_invoice_path(cfg: Config, ksef_number: str, ext: str) -> Path | None:
    """Scan month dirs to find a file for the given ksef_number."""
    if not cfg.invoices_dir.exists():
        return None
    for month_dir in sorted(cfg.invoices_dir.iterdir(), reverse=True):
        if not month_dir.is_dir():
            continue
        path = month_dir / f"{ksef_number}{ext}"
        if path.exists():
            return path
    return None


def add_invoice(cfg: Config, ksef_number: str, issue_date: str, meta: dict, xml_content: str) -> None:
    month = _month_dir(cfg, issue_date)
    month.mkdir(parents=True, exist_ok=True)

    xml_path = month / f"{ksef_number}.xml"
    xml_path.write_text(xml_content, encoding="utf-8")

    json_path = month / f"{ksef_number}.json"
    json_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")


def get_invoice_xml(cfg: Config, ksef_number: str) -> str | None:
    path = _find_invoice_path(cfg, ksef_number, ".xml")
    if path:
        return path.read_text(encoding="utf-8")
    return None


def get_invoice_xml_path(cfg: Config, ksef_number: str) -> Path | None:
    return _find_invoice_path(cfg, ksef_number, ".xml")


def has_invoice(cfg: Config, ksef_number: str) -> bool:
    return _find_invoice_path(cfg, ksef_number, ".json") is not None


def load_all_metadata(cfg: Config) -> list[dict]:
    results = []
    if not cfg.invoices_dir.exists():
        return results
    for month_dir in cfg.invoices_dir.iterdir():
        if not month_dir.is_dir():
            continue
        for json_file in month_dir.glob("*.json"):
            try:
                meta = json.loads(json_file.read_text(encoding="utf-8"))
                results.append(meta)
            except (json.JSONDecodeError, OSError):
                continue
    results.sort(key=lambda m: m.get("issue_date", ""), reverse=True)
    return results


def search_invoices(cfg: Config, query: str) -> list[dict]:
    query_lower = query.lower()
    results = []
    for meta in load_all_metadata(cfg):
        searchable = " ".join([
            meta.get("ksef_number", ""),
            meta.get("invoice_number", ""),
            meta.get("seller_name", ""),
            meta.get("seller_nip", ""),
        ]).lower()
        if query_lower in searchable:
            results.append(meta)
    return results


def resolve_invoice_id(cfg: Config, query: str) -> list[dict]:
    """Fuzzy ID resolution: exact ksef_number → exact invoice_number → partial match."""
    all_meta = load_all_metadata(cfg)

    # Exact ksef_number
    for meta in all_meta:
        if meta.get("ksef_number") == query:
            return [meta]

    # Exact invoice_number
    for meta in all_meta:
        if meta.get("invoice_number") == query:
            return [meta]

    # Partial match
    query_lower = query.lower()
    matches = []
    for meta in all_meta:
        searchable = " ".join([
            meta.get("ksef_number", ""),
            meta.get("invoice_number", ""),
            meta.get("seller_name", ""),
            meta.get("seller_nip", ""),
        ]).lower()
        if query_lower in searchable:
            matches.append(meta)
    return matches


def load_sync_state(cfg: Config) -> dict | None:
    if cfg.sync_state_path.exists():
        try:
            return json.loads(cfg.sync_state_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None
    return None


def save_sync_state(cfg: Config, state: dict) -> None:
    cfg.data_path.mkdir(parents=True, exist_ok=True)
    cfg.sync_state_path.write_text(
        json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
    )

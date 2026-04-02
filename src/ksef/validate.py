from __future__ import annotations

from pathlib import Path

from lxml import etree

_SCHEMA_PATH = Path(__file__).parent / "schemas" / "FA3.xsd"
_schema: etree.XMLSchema | None = None


def _get_schema() -> etree.XMLSchema:
    global _schema
    if _schema is None:
        doc = etree.parse(str(_SCHEMA_PATH))
        _schema = etree.XMLSchema(doc)
    return _schema


def validate_invoice_xml(xml_content: str) -> list[str]:
    """Validate invoice XML against FA(3) schema. Returns list of error messages (empty = valid)."""
    schema = _get_schema()
    try:
        doc = etree.fromstring(xml_content.encode("utf-8"))
    except etree.XMLSyntaxError as e:
        return [f"XML parse error: {e}"]

    schema.validate(doc)
    return [str(e) for e in schema.error_log]

from __future__ import annotations

import functools
import io
from collections import defaultdict
from decimal import ROUND_HALF_UP, Decimal
from importlib.resources import files

import qrcode
import qrcode.image.svg
from jinja2 import Environment
from markupsafe import Markup
from weasyprint import HTML

from ksef.display import COUNTRY_NAMES, _verification_url, format_amount, format_nip
from ksef.models import Invoice, Party

LANGUAGES = ("pl", "en", "pl/en", "en/pl", "dual")
LANG_ALIASES = {"dual": "pl/en"}

LABELS = {
    "pl": {
        "header_invoice_no": "Numer Faktury:",
        "header_ksef_no": "Numer KSEF:",
        "section_seller": "Sprzedawca",
        "section_buyer": "Nabywca",
        "no_identifier": "Brak identyfikatora",
        "field_nip": "NIP:",
        "field_name": "Nazwa:",
        "subtitle_address": "Adres",
        "field_phone": "Tel:",
        "field_email": "E-mail:",
        "field_regon": "REGON:",
        "field_krs": "KRS:",
        "section_details": "Szczegóły",
        "issue_date_long": "Data wystawienia, z zastrzeżeniem art. 106na ust. 1 ustawy:",
        "delivery_date_long": "Data dokonania lub zakończenia dostawy towarów lub wykonania usługi:",
        "billing_period": "Okres rozliczeniowy:",
        "contract_no": "Nr umowy:",
        "currency_code": "Kod waluty:",
        "place_of_issue": "Miejsce wystawienia:",
        "section_items": "Pozycje",
        "issued_in_currency": "Faktura wystawiona w walucie {currency}",
        "items_no": "Lp.",
        "items_name": "Nazwa towaru lub usługi",
        "items_unit_price": "Cena jedn. netto",
        "items_qty": "Ilość",
        "items_unit": "Miara",
        "items_net_value": "Wartość sprzedaży netto",
        "total_due": "Kwota należności ogółem:",
        "section_vat_summary": "Podsumowanie stawek podatku",
        "vat_rate": "Stawka podatku",
        "vat_net": "Kwota netto",
        "vat_tax": "Kwota podatku",
        "vat_gross": "Kwota brutto",
        "section_annotations": "Adnotacje",
        "section_payment": "Płatność",
        "payment_info_label": "Informacja o płatności:",
        "payment_status_paid": "Zapłata",
        "payment_status_unpaid": "Brak zapłaty",
        "payment_method": "Forma płatności:",
        "payment_due_date": "Termin płatności",
        "section_bank_account": "Numer rachunku bankowego",
        "bank_full_account": "Pełny numer rachunku",
        "bank_swift": "Kod SWIFT",
        "bank_name": "Nazwa banku",
        "qr_title": "Sprawdź, czy Twoja faktura znajduje się w KSeF!",
        "qr_text": "Nie możesz zeskanować kodu z obrazka? Kliknij w link weryfikacyjny i przejdź do weryfikacji faktury!",
        "jst_label": "Faktura dotyczy jednostki podrzędnej JST:",
        "gv_label": "Faktura dotyczy członka grupy GV:",
        "yes": "TAK",
        "no": "NIE",
    },
    "en": {
        "header_invoice_no": "Invoice number:",
        "header_ksef_no": "KSEF number:",
        "section_seller": "Seller",
        "section_buyer": "Buyer",
        "no_identifier": "No identifier",
        "field_nip": "NIP:",
        "field_name": "Name:",
        "subtitle_address": "Address",
        "field_phone": "Phone:",
        "field_email": "Email:",
        "field_regon": "REGON:",
        "field_krs": "KRS:",
        "section_details": "Details",
        "issue_date_long": "Issue date, subject to art. 106na sec. 1 of the VAT Act:",
        "delivery_date_long": "Date of delivery completion or service performance:",
        "billing_period": "Billing period:",
        "contract_no": "Contract no.:",
        "currency_code": "Currency code:",
        "place_of_issue": "Place of issue:",
        "section_items": "Line items",
        "issued_in_currency": "Invoice issued in {currency}",
        "items_no": "No.",
        "items_name": "Goods or service name",
        "items_unit_price": "Net unit price",
        "items_qty": "Qty",
        "items_unit": "Unit",
        "items_net_value": "Net sales value",
        "total_due": "Total amount due:",
        "section_vat_summary": "Tax rate summary",
        "vat_rate": "Tax rate",
        "vat_net": "Net amount",
        "vat_tax": "Tax amount",
        "vat_gross": "Gross amount",
        "section_annotations": "Annotations",
        "section_payment": "Payment",
        "payment_info_label": "Payment information:",
        "payment_status_paid": "Paid",
        "payment_status_unpaid": "Not paid",
        "payment_method": "Payment method:",
        "payment_due_date": "Payment due date",
        "section_bank_account": "Bank account number",
        "bank_full_account": "Full account number",
        "bank_swift": "SWIFT code",
        "bank_name": "Bank name",
        "qr_title": "Check if your invoice is in KSeF!",
        "qr_text": "Cannot scan the code from the image? Click the verification link to verify the invoice!",
        "jst_label": "Invoice concerns subordinate JST unit:",
        "gv_label": "Invoice concerns VAT group member:",
        "yes": "YES",
        "no": "NO",
    },
}

INVOICE_TYPE_LABELS = {
    "VAT":     {"pl": "Faktura podstawowa",              "en": "Standard invoice"},
    "KOR":     {"pl": "Faktura korygująca",              "en": "Correcting invoice"},
    "ZAL":     {"pl": "Faktura zaliczkowa",              "en": "Advance payment invoice"},
    "ROZ":     {"pl": "Faktura rozliczeniowa",           "en": "Settlement invoice"},
    "UPR":     {"pl": "Faktura uproszczona",             "en": "Simplified invoice"},
    "KOR_ZAL": {"pl": "Faktura korygująca zaliczkowa",   "en": "Correcting advance payment invoice"},
    "KOR_ROZ": {"pl": "Faktura korygująca rozliczeniową", "en": "Correcting settlement invoice"},
}

# Keyed by the English label produced by parser.ADNOTACJE
ANNOTATION_TRANSLATIONS = {
    "Cash method VAT":        {"pl": "Metoda kasowa",                    "en": "Cash method VAT"},
    "Self-invoicing":         {"pl": "Samofakturowanie",                 "en": "Self-invoicing"},
    "Reverse charge":         {"pl": "Odwrotne obciążenie",              "en": "Reverse charge"},
    "Split payment":          {"pl": "Mechanizm podzielonej płatności",  "en": "Split payment"},
    "Triangular transaction": {"pl": "Transakcja trójstronna",           "en": "Triangular transaction"},
}

# Keyed by the English label produced by parser.PAYMENT_FORMS
PAYMENT_FORM_TRANSLATIONS = {
    "cash":     {"pl": "Gotówka",          "en": "Cash"},
    "card":     {"pl": "Karta",            "en": "Card"},
    "voucher":  {"pl": "Bon",              "en": "Voucher"},
    "cheque":   {"pl": "Czek",             "en": "Cheque"},
    "credit":   {"pl": "Kredyt",           "en": "Credit"},
    "transfer": {"pl": "Przelew",          "en": "Transfer"},
    "mobile":   {"pl": "Płatność mobilna", "en": "Mobile payment"},
}

VAT_RATE_LABELS = {
    "oo": {"pl": "odwrotne obciążenie",                        "en": "reverse charge"},
    "zw": {"pl": "zwolnienie",                                 "en": "exempt"},
    "np": {"pl": "np z wyłączeniem art. 100 ust 1 pkt 4 ustawy", "en": "n/a, excluding art. 100 sec. 1 pt. 4 of the VAT Act"},
}


def _join_dual(primary: str, secondary: str) -> Markup:
    """Join 'primary / secondary' with the slash and secondary in muted color.

    Shared trailing punctuation (e.g. ':') is pulled outside the muted span so it
    stays in the primary color.
    """
    trailing = ""
    for punct in (":", ".", ","):
        if primary.endswith(punct) and secondary.endswith(punct):
            primary = primary[:-1]
            secondary = secondary[:-1]
            trailing = punct
            break
    return Markup('{}<span class="lang-secondary"> / {}</span>{}').format(
        primary, secondary, trailing
    )


def _translate(d: dict, key: str, lang: str):
    """Translate a value via a {key: {pl, en}} dict, supporting composite langs."""
    entry = d.get(key)
    if entry is None:
        return key
    if lang in ("pl", "en"):
        return entry.get(lang, key)
    primary, secondary = lang.split("/")
    return _join_dual(entry.get(primary, key), entry.get(secondary, key))


def _build_labels(lang: str) -> dict:
    if lang in ("pl", "en"):
        return dict(LABELS[lang])
    primary, secondary = lang.split("/")
    return {k: _join_dual(LABELS[primary][k], LABELS[secondary][k]) for k in LABELS["pl"]}


def _format_date_pl(date_str: str) -> str:
    if not date_str or len(date_str) < 10:
        return date_str
    try:
        y, m, d = date_str[:10].split("-")
        return f"{d}.{m}.{y}"
    except ValueError:
        return date_str


def _format_vat_rate(rate: str, lang: str) -> str:
    if not rate:
        return ""
    if rate == "oo":
        return _translate(VAT_RATE_LABELS, "oo", lang)
    if rate == "zw":
        return _translate(VAT_RATE_LABELS, "zw", lang)
    if rate.startswith("np"):
        return _translate(VAT_RATE_LABELS, "np", lang)
    try:
        float(rate)
        return f"{rate}%"
    except ValueError:
        return rate


def _vat_summary(invoice: Invoice, lang: str) -> list[dict]:
    buckets: dict[str, dict[str, Decimal]] = defaultdict(
        lambda: {"net": Decimal("0"), "vat": Decimal("0")}
    )
    for item in invoice.line_items:
        if not item.net_amount:
            continue
        net = Decimal(item.net_amount)
        rate_label = item.vat_rate or ""
        try:
            rate = Decimal(rate_label)
            vat = (net * rate / 100).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        except Exception:
            vat = Decimal("0")
        buckets[rate_label]["net"] += net
        buckets[rate_label]["vat"] += vat

    return [
        {
            "rate_label": _format_vat_rate(rate, lang),
            "net": format_amount(f"{d['net']:.2f}", ""),
            "vat": format_amount(f"{d['vat']:.2f}", ""),
            "gross": format_amount(f"{d['net'] + d['vat']:.2f}", ""),
        }
        for rate, d in sorted(buckets.items())
    ]


def _qr_svg(url: str) -> str:
    factory = qrcode.image.svg.SvgPathImage
    img = qrcode.make(url, image_factory=factory, box_size=4, border=2)
    buf = io.BytesIO()
    img.save(buf)
    svg = buf.getvalue().decode("utf-8")
    if svg.startswith("<?xml"):
        svg = svg[svg.index("<svg"):]
    return svg


def _yes_no(value: str, t: dict) -> str:
    return {"1": t["yes"], "2": t["no"]}.get(value, "")


def _address_lines(party: Party, lang: str) -> list:
    lines = [line for line in (party.address_l1, party.address_l2) if line]
    if party.country_code:
        lines.append(_translate(COUNTRY_NAMES, party.country_code.upper(), lang))
    return lines


def render_invoice_pdf(
    invoice: Invoice,
    xml_bytes: bytes | None = None,
    qr_base_url: str = "",
    lang: str = "pl",
) -> bytes:
    if lang not in LANGUAGES:
        raise ValueError(f"lang must be one of {LANGUAGES}, got {lang!r}")
    lang = LANG_ALIASES.get(lang, lang)

    currency = invoice.currency or "PLN"

    qr_svg = ""
    verify_url = ""
    if invoice.ksef_number and xml_bytes and qr_base_url:
        verify_url = _verification_url(
            invoice.seller.nip, invoice.issue_date, xml_bytes, qr_base_url
        )
        qr_svg = _qr_svg(verify_url)

    t = _build_labels(lang)
    invoice_type_label = _translate(INVOICE_TYPE_LABELS, invoice.invoice_type, lang)
    annotations = [_translate(ANNOTATION_TRANSLATIONS, a, lang) for a in invoice.annotations]
    payment_form_label = _translate(
        PAYMENT_FORM_TRANSLATIONS, (invoice.payment.payment_form or "").lower(), lang
    ) if invoice.payment.payment_form else ""

    def _yes_no_helper(value: str) -> str:
        return _yes_no(value, t)

    template = _load_template()
    html = template.render(
        inv=invoice,
        currency=currency,
        t=t,
        vat_summary=_vat_summary(invoice, lang),
        invoice_type_label=invoice_type_label,
        annotations=annotations,
        payment_form_label=payment_form_label,
        qr_svg=qr_svg,
        verify_url=verify_url,
        address_lines=lambda party: _address_lines(party, lang),
        yes_no_label=_yes_no_helper,
    )
    return HTML(string=html).write_pdf()


@functools.lru_cache(maxsize=1)
def _load_template():
    template_text = (files("ksef") / "templates" / "invoice.html").read_text("utf-8")
    env = Environment(autoescape=True)
    env.globals["format_amount"] = format_amount
    env.globals["format_nip"] = format_nip
    env.filters["dmy_date"] = _format_date_pl
    return env.from_string(template_text)

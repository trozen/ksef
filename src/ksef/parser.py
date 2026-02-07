from __future__ import annotations

import xml.etree.ElementTree as ET

from ksef.models import Invoice, LineItem, Party, PaymentInfo

NS = {"fa": "http://crd.gov.pl/wzor/2025/06/25/13775/"}

PAYMENT_FORMS = {
    "1": "gotówka",
    "2": "karta",
    "3": "bon",
    "4": "czek",
    "5": "kredyt",
    "6": "przelew",
    "7": "mobilna",
}


def _find_text(el: ET.Element, path: str, default: str = "") -> str:
    node = el.find(path, NS)
    return node.text.strip() if node is not None and node.text else default


def parse_invoice(xml_content: str, ksef_number: str = "") -> Invoice:
    root = ET.fromstring(xml_content)

    seller_el = root.find("fa:Podmiot1", NS)
    buyer_el = root.find("fa:Podmiot2", NS)
    fa_el = root.find("fa:Fa", NS)

    seller = Party()
    if seller_el is not None:
        seller.nip = _find_text(seller_el, "fa:DaneIdentyfikacyjne/fa:NIP")
        seller.name = _find_text(seller_el, "fa:DaneIdentyfikacyjne/fa:Nazwa")

    buyer = Party()
    if buyer_el is not None:
        buyer.nip = _find_text(buyer_el, "fa:DaneIdentyfikacyjne/fa:NIP")
        buyer.name = _find_text(buyer_el, "fa:DaneIdentyfikacyjne/fa:Nazwa")

    invoice = Invoice(
        ksef_number=ksef_number,
        seller=seller,
        buyer=buyer,
    )

    if fa_el is not None:
        invoice.currency = _find_text(fa_el, "fa:KodWaluty")
        invoice.issue_date = _find_text(fa_el, "fa:P_1")
        invoice.invoice_number = _find_text(fa_el, "fa:P_2")
        invoice.invoice_type = _find_text(fa_el, "fa:RodzajFaktury")
        invoice.net_amount = _find_text(fa_el, "fa:P_13_1")
        invoice.vat_amount = _find_text(fa_el, "fa:P_14_1")
        invoice.gross_amount = _find_text(fa_el, "fa:P_15")

        # Due date — either P_6 (single date) or OkresFa/P_6_Do (period end)
        invoice.due_date = _find_text(fa_el, "fa:P_6")
        if not invoice.due_date:
            invoice.due_date = _find_text(fa_el, "fa:OkresFa/fa:P_6_Do")

        # Extra descriptions (DodatkowyOpis) — deduplicated across all lines
        for opis in fa_el.findall("fa:DodatkowyOpis", NS):
            key = _find_text(opis, "fa:Klucz")
            val = _find_text(opis, "fa:Wartosc")
            if key and val:
                invoice.extras[key] = val

        # Line items
        for wiersz in fa_el.findall("fa:FaWiersz", NS):
            item = LineItem(
                line_number=int(_find_text(wiersz, "fa:NrWierszaFa", "0")),
                description=_find_text(wiersz, "fa:P_7"),
                unit=_find_text(wiersz, "fa:P_8A"),
                quantity=_find_text(wiersz, "fa:P_8B"),
                unit_price=_find_text(wiersz, "fa:P_9A"),
                net_amount=_find_text(wiersz, "fa:P_11"),
                vat_rate=_find_text(wiersz, "fa:P_12"),
            )
            invoice.line_items.append(item)

        # Payment info
        platnosc = fa_el.find("fa:Platnosc", NS)
        if platnosc is not None:
            payment = PaymentInfo()
            payment.due_date = _find_text(platnosc, "fa:TerminPlatnosci/fa:Termin")
            form_code = _find_text(platnosc, "fa:FormaPlatnosci")
            payment.payment_form = PAYMENT_FORMS.get(form_code, form_code)

            bank = platnosc.find("fa:RachunekBankowy", NS)
            if bank is not None:
                payment.bank_account = _find_text(bank, "fa:NrRB")
                payment.bank_name = _find_text(bank, "fa:NazwaBanku")
                payment.swift = _find_text(bank, "fa:SWIFT")

            invoice.payment = payment

            # Use payment due date if invoice due_date is empty
            if not invoice.due_date and payment.due_date:
                invoice.due_date = payment.due_date

    return invoice

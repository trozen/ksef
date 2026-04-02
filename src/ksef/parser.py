from __future__ import annotations

import xml.etree.ElementTree as ET

from ksef.models import Invoice, LineItem, Party, PaymentInfo

NS = {"fa": "http://crd.gov.pl/wzor/2025/06/25/13775/"}

PAYMENT_FORMS = {
    "1": "cash",
    "2": "card",
    "3": "voucher",
    "4": "cheque",
    "5": "credit",
    "6": "transfer",
    "7": "mobile",
}

# Adnotacje P_* flags: value "1" means the annotation applies
ADNOTACJE = {
    "P_16":  "Cash method VAT",
    "P_17":  "Self-invoicing",
    "P_18":  "Reverse charge",
    "P_18A": "Split payment",
    "P_23":  "Triangular transaction",
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
        addr1 = _find_text(seller_el, "fa:Adres/fa:AdresL1")
        addr2 = _find_text(seller_el, "fa:Adres/fa:AdresL2")
        seller.address = ", ".join(filter(None, [addr1, addr2]))
        seller.phone = _find_text(seller_el, "fa:DaneKontaktowe/fa:Telefon")
        seller.email = _find_text(seller_el, "fa:DaneKontaktowe/fa:Email")

    buyer = Party()
    if buyer_el is not None:
        buyer.nip = _find_text(buyer_el, "fa:DaneIdentyfikacyjne/fa:NIP")
        buyer.name = _find_text(buyer_el, "fa:DaneIdentyfikacyjne/fa:Nazwa")
        addr1 = _find_text(buyer_el, "fa:Adres/fa:AdresL1")
        addr2 = _find_text(buyer_el, "fa:Adres/fa:AdresL2")
        buyer.address = ", ".join(filter(None, [addr1, addr2]))
        buyer.phone = _find_text(buyer_el, "fa:DaneKontaktowe/fa:Telefon")
        buyer.email = _find_text(buyer_el, "fa:DaneKontaktowe/fa:Email")

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
        # Sum all VAT-rate buckets: P_13_1..P_13_11 + P_13_6_1..P_13_6_3
        net_buckets = [
            "fa:P_13_1", "fa:P_13_2", "fa:P_13_3", "fa:P_13_4", "fa:P_13_5",
            "fa:P_13_6_1", "fa:P_13_6_2", "fa:P_13_6_3",
            "fa:P_13_7", "fa:P_13_8", "fa:P_13_9", "fa:P_13_10", "fa:P_13_11",
        ]
        vat_buckets = [
            "fa:P_14_1", "fa:P_14_2", "fa:P_14_3", "fa:P_14_4", "fa:P_14_5",
        ]
        net_total = sum(float(v) for p in net_buckets if (v := _find_text(fa_el, p)))
        vat_total = sum(float(v) for p in vat_buckets if (v := _find_text(fa_el, p)))
        invoice.net_amount = f"{net_total:.2f}" if net_total else ""
        invoice.vat_amount = f"{vat_total:.2f}" if vat_total else ""
        invoice.gross_amount = _find_text(fa_el, "fa:P_15")

        # Due date — either P_6 (single date) or OkresFa/P_6_Do (period end)
        invoice.due_date = _find_text(fa_el, "fa:P_6")
        if not invoice.due_date:
            invoice.due_date = _find_text(fa_el, "fa:OkresFa/fa:P_6_Do")

        # Adnotacje flags
        adnotacje = fa_el.find("fa:Adnotacje", NS)
        if adnotacje is not None:
            for field, label in ADNOTACJE.items():
                if _find_text(adnotacje, f"fa:{field}") == "1":
                    invoice.annotations.append(label)

        # Service period
        okres = fa_el.find("fa:OkresFa", NS)
        if okres is not None:
            invoice.period_from = _find_text(okres, "fa:P_6_Od")
            invoice.period_to = _find_text(okres, "fa:P_6_Do")

        # Extra descriptions (DodatkowyOpis) — invoice-level only (no NrWiersza)
        for opis in fa_el.findall("fa:DodatkowyOpis", NS):
            if opis.find("fa:NrWiersza", NS) is not None:
                continue
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

        # Contract numbers from WarunkiTransakcji (deduplicated; also remove from extras)
        warunki = fa_el.find("fa:WarunkiTransakcji", NS)
        if warunki is not None:
            for umowa in warunki.findall("fa:Umowy", NS):
                nr = _find_text(umowa, "fa:NrUmowy")
                if nr and nr not in invoice.contract_numbers:
                    invoice.contract_numbers.append(nr)
        # Drop extras whose value exactly matches a contract number (avoids duplication)
        if invoice.contract_numbers:
            invoice.extras = {
                k: v for k, v in invoice.extras.items()
                if v not in invoice.contract_numbers
            }

    # Stopka (footer)
    stopka = root.find("fa:Stopka", NS)
    if stopka is not None:
        for info in stopka.findall("fa:Informacje", NS):
            line = _find_text(info, "fa:StopkaFaktury")
            if line:
                invoice.footer.append(line)
        rejestry = stopka.find("fa:Rejestry", NS)
        if rejestry is not None:
            invoice.krs = _find_text(rejestry, "fa:KRS")
            invoice.regon = _find_text(rejestry, "fa:REGON")

    return invoice

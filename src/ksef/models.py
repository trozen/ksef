from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Party:
    nip: str = ""
    name: str = ""
    address_l1: str = ""
    address_l2: str = ""
    country_code: str = ""
    phone: str = ""
    email: str = ""
    jst: str = ""  # "1" = TAK, "2" = NIE, "" = absent
    gv: str = ""   # "1" = TAK, "2" = NIE, "" = absent


@dataclass
class LineItem:
    line_number: int = 0
    description: str = ""
    unit: str = ""
    quantity: str = ""
    unit_price: str = ""
    net_amount: str = ""
    vat_rate: str = ""


@dataclass
class PaymentInfo:
    due_date: str = ""
    payment_form: str = ""
    bank_account: str = ""
    bank_name: str = ""
    swift: str = ""
    paid: str = ""  # "1" = paid, "" = unpaid / absent


@dataclass
class Invoice:
    ksef_number: str = ""
    invoice_number: str = ""
    invoice_type: str = ""
    currency: str = ""
    issue_date: str = ""
    due_date: str = ""
    place_of_issue: str = ""
    period_from: str = ""
    period_to: str = ""
    seller: Party = field(default_factory=Party)
    buyer: Party = field(default_factory=Party)
    net_amount: str = ""
    vat_amount: str = ""
    gross_amount: str = ""
    line_items: list[LineItem] = field(default_factory=list)
    payment: PaymentInfo = field(default_factory=PaymentInfo)
    extras: dict[str, str] = field(default_factory=dict)
    annotations: list[str] = field(default_factory=list)
    contract_numbers: list[str] = field(default_factory=list)
    footer: list[str] = field(default_factory=list)
    krs: str = ""
    regon: str = ""
    synced_at: str = ""

    def to_metadata(self) -> dict:
        return {
            "ksef_number": self.ksef_number,
            "invoice_number": self.invoice_number,
            "invoice_type": self.invoice_type,
            "currency": self.currency,
            "issue_date": self.issue_date,
            "due_date": self.due_date,
            "seller_nip": self.seller.nip,
            "seller_name": self.seller.name,
            "net_amount": self.net_amount,
            "vat_amount": self.vat_amount,
            "gross_amount": self.gross_amount,
            "synced_at": self.synced_at,
        }

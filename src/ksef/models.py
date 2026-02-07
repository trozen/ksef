from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Party:
    nip: str = ""
    name: str = ""


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


@dataclass
class Invoice:
    ksef_number: str = ""
    invoice_number: str = ""
    invoice_type: str = ""
    currency: str = ""
    issue_date: str = ""
    due_date: str = ""
    seller: Party = field(default_factory=Party)
    buyer: Party = field(default_factory=Party)
    net_amount: str = ""
    vat_amount: str = ""
    gross_amount: str = ""
    line_items: list[LineItem] = field(default_factory=list)
    payment: PaymentInfo = field(default_factory=PaymentInfo)
    extras: dict[str, str] = field(default_factory=dict)
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

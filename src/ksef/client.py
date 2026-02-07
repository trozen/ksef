from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import requests
from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding


@dataclass
class Tokens:
    access_token: str
    access_valid_until: str
    refresh_token: str
    refresh_valid_until: str


class KSeFClient:
    def __init__(self, base_url: str, timeout_s: int = 30) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_s = timeout_s
        self.session = requests.Session()
        self.session.headers.update({
            "Accept": "application/json",
            "User-Agent": "ksef-cli/0.1 (+python-requests)",
        })

    def _url(self, path: str) -> str:
        if not path.startswith("/"):
            path = "/" + path
        return f"{self.base_url}{path}"

    def _raise_for_status(self, r: requests.Response) -> None:
        if r.status_code >= 400:
            try:
                payload = r.json()
            except Exception:
                payload = r.text
            raise RuntimeError(f"HTTP {r.status_code} for {r.request.method} {r.url}\n{payload}")

    # --- Auth ---

    def auth_challenge(self) -> dict[str, Any]:
        r = self.session.post(self._url("/auth/challenge"), timeout=self.timeout_s)
        self._raise_for_status(r)
        return r.json()

    def public_key_certificates(self) -> list[dict[str, Any]]:
        r = self.session.get(self._url("/security/public-key-certificates"), timeout=self.timeout_s)
        self._raise_for_status(r)
        return r.json()

    def _select_cert_for_usage(self, certs: list[dict[str, Any]], usage: str) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        for c in certs:
            usages = c.get("usage") or []
            if usage not in usages:
                continue
            try:
                vf = datetime.fromisoformat(c["validFrom"].replace("Z", "+00:00"))
                vt = datetime.fromisoformat(c["validTo"].replace("Z", "+00:00"))
            except Exception:
                return c
            if vf <= now <= vt:
                return c
        raise RuntimeError(f"No currently valid public key certificate found for usage={usage}")

    def start_auth_with_ksef_token(
        self,
        ksef_token: str,
        nip: str,
        challenge: str,
        timestamp_ms: int,
    ) -> dict[str, Any]:
        certs = self.public_key_certificates()
        cert = self._select_cert_for_usage(certs, "KsefTokenEncryption")
        cert_der = base64.b64decode(cert["certificate"])
        pub = x509.load_der_x509_certificate(cert_der).public_key()

        plaintext = f"{ksef_token}|{timestamp_ms}".encode("utf-8")
        ciphertext = pub.encrypt(
            plaintext,
            padding.OAEP(
                mgf=padding.MGF1(algorithm=hashes.SHA256()),
                algorithm=hashes.SHA256(),
                label=None,
            ),
        )

        body = {
            "challenge": challenge,
            "contextIdentifier": {"type": "Nip", "value": nip},
            "encryptedToken": base64.b64encode(ciphertext).decode("ascii"),
        }

        r = self.session.post(self._url("/auth/ksef-token"), json=body, timeout=self.timeout_s)
        self._raise_for_status(r)
        return r.json()

    def auth_status(self, reference_number: str, authentication_token_jwt: str) -> dict[str, Any]:
        r = self.session.get(
            self._url(f"/auth/{reference_number}"),
            headers={"Authorization": f"Bearer {authentication_token_jwt}"},
            timeout=self.timeout_s,
        )
        self._raise_for_status(r)
        return r.json()

    def redeem_tokens(self, authentication_token_jwt: str) -> Tokens:
        r = self.session.post(
            self._url("/auth/token/redeem"),
            headers={"Authorization": f"Bearer {authentication_token_jwt}"},
            timeout=self.timeout_s,
        )
        self._raise_for_status(r)
        data = r.json()
        return Tokens(
            access_token=data["accessToken"]["token"],
            access_valid_until=data["accessToken"]["validUntil"],
            refresh_token=data["refreshToken"]["token"],
            refresh_valid_until=data["refreshToken"]["validUntil"],
        )

    def refresh_access_token(self, refresh_token_jwt: str) -> dict[str, Any]:
        r = self.session.post(
            self._url("/auth/token/refresh"),
            headers={"Authorization": f"Bearer {refresh_token_jwt}"},
            timeout=self.timeout_s,
        )
        self._raise_for_status(r)
        return r.json()

    # --- Invoices ---

    def query_invoice_metadata(self, access_token_jwt: str, filters: dict[str, Any]) -> dict[str, Any]:
        r = self.session.post(
            self._url("/invoices/query/metadata"),
            headers={"Authorization": f"Bearer {access_token_jwt}", "Accept": "application/json"},
            json=filters,
            timeout=self.timeout_s,
        )
        self._raise_for_status(r)
        return r.json()

    def download_invoice_xml(self, access_token_jwt: str, ksef_number: str) -> str:
        r = self.session.get(
            self._url(f"/invoices/ksef/{ksef_number}"),
            headers={"Authorization": f"Bearer {access_token_jwt}", "Accept": "application/xml"},
            timeout=self.timeout_s,
        )
        self._raise_for_status(r)
        return r.text

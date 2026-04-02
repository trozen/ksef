# KSeF API v2 — Reference

Source: [CIRFMF/ksef-docs](https://github.com/CIRFMF/ksef-docs) (`open-api.json`)

Base URLs:
- Test: `https://api-test.ksef.mf.gov.pl/v2`
- Demo: `https://api-demo.ksef.mf.gov.pl/v2`
- Prod: `https://api.ksef.mf.gov.pl/v2`

All endpoints require `Authorization: Bearer <access_token>` unless noted otherwise.

---

## Authentication

| Method | Path | Description |
|--------|------|-------------|
| POST | `/auth/challenge` | Start auth — returns challenge (no auth required) |
| POST | `/auth/ksef-token` | Authenticate with encrypted KSeF token |
| POST | `/auth/xades-signature` | Authenticate with XAdES-signed XML |
| GET | `/auth/{referenceNumber}` | Poll authentication status |
| POST | `/auth/token/redeem` | Exchange authentication token for access + refresh tokens |
| POST | `/auth/token/refresh` | Refresh access token |
| GET | `/auth/sessions` | List active auth sessions |
| DELETE | `/auth/sessions/current` | Invalidate current session (logout) |
| DELETE | `/auth/sessions/{referenceNumber}` | Invalidate a specific session |

### KSeF token auth flow

1. `POST /auth/challenge` → get `challenge` and `timestamp`
2. `GET /security/public-key-certificates` → get RSA public key (usage: `KsefTokenEncryption`)
3. Encrypt `{token}|{timestamp_ms}` with RSA-OAEP/SHA-256
4. `POST /auth/ksef-token` with `challenge`, `contextIdentifier` (NIP), `encryptedToken`
5. Poll `GET /auth/{referenceNumber}` until `processingCode == 200`
6. `POST /auth/token/redeem` → get `accessToken` + `refreshToken` (both JWTs)

---

## Security

| Method | Path | Description |
|--------|------|-------------|
| GET | `/security/public-key-certificates` | Fetch public key certificates (no auth required) |

Certificates have a `usage` field — relevant values:
- `KsefTokenEncryption` — RSA key for encrypting the auth token in `/auth/ksef-token`
- `SymmetricKeyEncryption` — RSA key for encrypting the AES session key in `POST /sessions/online`

---

## Invoice retrieval

| Method | Path | Description |
|--------|------|-------------|
| POST | `/invoices/query/metadata` | Query invoice list with filters (date range, subject type, etc.) |
| GET | `/invoices/ksef/{ksefNumber}` | Download invoice XML by KSeF number |
| POST | `/invoices/exports` | Request a bulk export package |
| GET | `/invoices/exports/{referenceNumber}` | Poll export package status |

---

## Invoice sending (online session)

Invoices must be **encrypted** before sending:
1. Generate random AES-256 key + 128-bit IV
2. Encrypt invoice XML with AES-256-CBC/PKCS7, prepend IV to ciphertext
3. Encrypt AES key with RSA-OAEP/SHA-256 using the MF public key
4. Compute SHA-256 of original XML and of encrypted payload

### Session flow

| Method | Path | Description |
|--------|------|-------------|
| POST | `/sessions/online` | Open interactive session → returns `referenceNumber` (valid 12h) |
| POST | `/sessions/online/{referenceNumber}/invoices` | Send encrypted invoice → returns invoice `referenceNumber` |
| POST | `/sessions/online/{referenceNumber}/close` | Close session, triggers async UPO generation |
| GET | `/sessions/{referenceNumber}` | Get session status |
| GET | `/sessions/{referenceNumber}/invoices` | List invoices in session |
| GET | `/sessions/{referenceNumber}/invoices/{invoiceReferenceNumber}` | Get individual invoice status |
| GET | `/sessions/{referenceNumber}/invoices/failed` | List failed invoices in session |
| GET | `/sessions/{referenceNumber}/invoices/{invoiceReferenceNumber}/upo` | Download UPO by invoice reference number |
| GET | `/sessions/{referenceNumber}/invoices/ksef/{ksefNumber}/upo` | Download UPO by KSeF number |
| GET | `/sessions/{referenceNumber}/upo/{upoReferenceNumber}` | Download session-level UPO |

UPO endpoints return `application/xml` or `application/json` depending on `Accept` header.

### Send invoice request body

```json
{
  "invoiceHash": {
    "hashSHA": { "algorithm": "SHA-256", "encoding": "Base64", "value": "<hash of original XML>" },
    "fileSize": 1234
  },
  "invoicePayload": {
    "type": "encrypted",
    "encryptedInvoiceHash": {
      "hashSHA": { "algorithm": "SHA-256", "encoding": "Base64", "value": "<hash of encrypted payload>" },
      "fileSize": 1300
    },
    "encryptedInvoiceBody": "<Base64(IV + AES-encrypted XML)>",
    "encryptedSymmetricKey": "<Base64(RSA-OAEP encrypted AES key)>"
  }
}
```

---

## Batch session (multiple invoices)

| Method | Path | Description |
|--------|------|-------------|
| POST | `/sessions/batch` | Open batch session |
| POST | `/sessions/batch/{referenceNumber}/close` | Close batch session |

Same `/sessions/{referenceNumber}/...` status/UPO endpoints apply.

---

## Sessions (general)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/sessions` | List all sessions (upload history) |

---

## Tokens (API key management)

| Method | Path | Description |
|--------|------|-------------|
| POST | `/tokens` | Generate a new API token |
| GET | `/tokens` | List generated tokens |
| GET | `/tokens/{referenceNumber}` | Get token status |
| DELETE | `/tokens/{referenceNumber}` | Revoke a token |

---

## Rate limits

| Method | Path | Description |
|--------|------|-------------|
| GET | `/rate-limits` | Current API rate limits |
| GET | `/limits/context` | Limits for current session context |
| GET | `/limits/subject` | Limits for current subject (NIP) |

Default limits: 100 req/s, 300 req/min, 1200 req/h. Public key endpoint: 60 req/s.

---

## Permissions

Grant and query access for persons, entities, and subunits.

| Method | Path | Description |
|--------|------|-------------|
| POST | `/permissions/persons/grants` | Grant access to a natural person |
| POST | `/permissions/entities/grants` | Grant access to an entity |
| POST | `/permissions/authorizations/grants` | Grant authorization-level permissions |
| POST | `/permissions/indirect/grants` | Grant permissions indirectly |
| POST | `/permissions/subunits/grants` | Grant subunit admin permissions |
| POST | `/permissions/eu-entities/grants` | Grant EU entity representative permissions |
| POST | `/permissions/eu-entities/administration/grants` | Grant EU entity admin permissions |
| DELETE | `/permissions/authorizations/grants/{permissionId}` | Revoke authorization permissions |
| DELETE | `/permissions/common/grants/{permissionId}` | Revoke common permissions |
| POST | `/permissions/query/personal/grants` | List own permissions |
| POST | `/permissions/query/persons/grants` | List permissions granted to persons/entities |
| POST | `/permissions/query/entities/grants` | List entity permissions in current context |
| POST | `/permissions/query/authorizations/grants` | List authorization grants |
| POST | `/permissions/query/eu-entities/grants` | List EU entity permissions |
| POST | `/permissions/query/subunits/grants` | List subunit admin permissions |
| POST | `/permissions/query/subordinate-entities/roles` | List subordinate entity roles |
| GET | `/permissions/query/entities/roles` | List roles for current entity |
| GET | `/permissions/operations/{referenceNumber}` | Poll permission operation status |
| GET | `/permissions/attachments/status` | Check if sending invoices with attachments is allowed |

---

## Certificates (XAdES auth)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/certificates/enrollments/data` | Get data required for PKCS#10 certificate request |
| POST | `/certificates/enrollments` | Submit certificate enrollment request |
| GET | `/certificates/enrollments/{referenceNumber}` | Poll enrollment status |
| POST | `/certificates/query` | Search certificate metadata |
| POST | `/certificates/retrieve` | Fetch certificates by serial numbers (DER format) |
| POST | `/certificates/{certificateSerialNumber}/revoke` | Revoke a certificate |
| GET | `/certificates/limits` | Certificate enrollment limits |

---

## PEPPOL

| Method | Path | Description |
|--------|------|-------------|
| GET | `/peppol/query` | List PEPPOL service providers |

---

## Test environment helpers (`/testdata/...`)

Only available in the test environment. Used for setting up test scenarios.

| Method | Path | Description |
|--------|------|-------------|
| POST | `/testdata/subject` | Create a test subject (NIP) |
| POST | `/testdata/subject/remove` | Remove a test subject |
| POST | `/testdata/person` | Create a test natural person |
| POST | `/testdata/person/remove` | Remove a test person |
| POST | `/testdata/permissions` | Grant permissions to test subject/person |
| POST | `/testdata/permissions/revoke` | Revoke test permissions |
| POST | `/testdata/attachment` | Enable invoice-with-attachment sending |
| POST | `/testdata/attachment/revoke` | Disable invoice-with-attachment sending |
| POST | `/testdata/context/block` | Block a context |
| POST | `/testdata/context/unblock` | Unblock a context |
| POST | `/testdata/rate-limits` | Override API rate limits |
| DELETE | `/testdata/rate-limits` | Restore default API rate limits |
| POST | `/testdata/rate-limits/production` | Set rate limits to production values |
| POST | `/testdata/limits/context/session` | Override session limits for current context |
| DELETE | `/testdata/limits/context/session` | Restore default session limits |
| POST | `/testdata/limits/subject/certificate` | Override certificate limits for current subject |
| DELETE | `/testdata/limits/subject/certificate` | Restore default certificate limits |

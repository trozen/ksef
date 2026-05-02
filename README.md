# ksef

CLI tool for managing Polish e-invoices via [KSeF](https://www.podatki.gov.pl/ksef/) (Krajowy System e-Faktur). Syncs received and issued invoices from the KSeF API, stores them locally for offline browsing and search, generates new invoices from Jinja2 templates, exports them as PDF (matching the official KSeF layout), and supports sending invoice XML files directly to KSeF.

## Installation

Requires [uv](https://docs.astral.sh/uv/getting-started/installation/) and Python 3.12+.

**Run directly from the repo** (no install needed):

```
uv run ksef
```

**Or install globally** and run as `ksef`:

```
uv tool install .
```

## Configuration

Create `~/.config/trozen/ksef/config.toml` (or run `ksef init` to generate a template):

```toml
[ksef]
nip = "YOUR_NIP"
environment = "prod"          # test / demo / prod
token_path = "/path/to/your/ksef.token"
data_dir = "/path/to/safe/storage/ksef"  # where invoices will be stored
# allow_send = true           # uncomment to enable ksef send

[ksef.sync]
date_from = "2026-01-01"      # earliest date to sync from
max_per_sync = 100
```

Run `ksef config` to verify the resolved configuration.

## Getting a KSeF Token

Log into https://ap.ksef.mf.gov.pl, authenticate with Profil Zaufany or a qualified electronic signature, and generate a token with at least invoice-reading permissions. Save the token value to the file referenced by `token_path` in the config (e.g. `~/.config/trozen/ksef/ksef.token`).

Treat the token as a password — keep it out of version control and restrict file permissions (`chmod 600`).

Official documentation: https://ksef.podatki.gov.pl

## Usage

Running `ksef` with no arguments shows a dashboard with config summary and recent invoices.

```
ksef                       # dashboard
ksef sync                  # fetch new invoices (incremental)
ksef sync -f               # force re-sync last 30 days
ksef list                  # list all invoices (received and issued)
ksef list -s Januszex      # filter by seller
ksef show 1                # show invoice #1 from the list
ksef show FV/1/01          # match by invoice number
ksef show Januszex         # match by seller name
```

**Sending invoices** (requires `allow_send = true` in config):

```
ksef validate invoice.xml  # validate against FA(3) schema
ksef send invoice.xml      # send to KSeF, save UPO as invoice.upo.xml
ksef send invoice.xml --upo /path/to/upo.xml
ksef session <ref>         # check session status / retrieve UPO manually
```

## Generating invoices

`ksef gen` produces invoice XML from a named profile. A profile typically corresponds to a single counterparty (e.g. a recurring client) — it bundles their fixed details (NIP, address, line item description, VAT rate) so that each new invoice only needs the invoice number and amount. A profile is a Jinja2-templated XML file plus a small TOML metadata file, both stored in `<data_dir>/profiles/`.

**Workflow:**

1. Open https://ap.ksef.mf.gov.pl, draft an invoice with the visual editor, and download the XML.
2. Edit the XML and replace the parts that should change per invoice with Jinja2 placeholders (e.g. `{{ invoice_number }}`, `{{ net_amount }}`, `{{ issue_date }}`).
3. Register the template as a profile, then optionally fill in defaults in the profile's TOML file.
4. Run `ksef gen <profile> <invoice_no> <net_amount>` to render a ready-to-send XML.

```
ksef profile new sebex template.xml   # register profile
ksef profile vars                         # list all available template variables
ksef profile list                         # show registered profiles
ksef profile show sebex               # show profile details + file paths
ksef profile delete sebex             # remove profile

ksef gen sebex FV/1/0426 6999.99      # generate invoice for 6 999,99 PLN
ksef gen sebex FV/1/0426              # net_amount taken from profile [defaults]
ksef gen sebex FV/1/0426 --issue-today  # use today as issue date
ksef gen sebex FV/1/0426 -o /path/to/output.xml
```

Available template variables include `invoice_number`, `net_amount`, `vat_amount`, `gross_amount`, `issue_date`, `period_from`, `period_to`, `due_date`, `submission_date`, `generation_timestamp`. Run `ksef profile vars` for the full list. Any key under `[defaults]` in the profile TOML is also exposed as a template variable; computed variables always take priority over `[defaults]`.

By default, the issue date is the end of the current billing month: before the 15th it falls on the last day of the **previous** month (so the invoice covers the month just ended); on the 15th or later it falls on the last day of the **current** month. Override with `--issue-today`.

## Exporting to PDF

`ksef export` renders an invoice as a PDF that mirrors the official KSeF generator's layout (header, parties, line items, VAT summary, payment block, QR code on the verification page).

```
ksef export FV/1/01                       # render synced invoice (filename = KSeF number)
ksef export 1                             # by list position
ksef export Januszex                      # match by seller name
ksef export invoice.xml                   # render a local XML file directly
ksef export FV/1/01 -o report.pdf         # custom output path
```

**Languages** (`--lang`):

```
ksef export FV/1/01 --lang pl             # Polish only (default, matches official)
ksef export FV/1/01 --lang en             # English only
ksef export FV/1/01 --lang pl/en          # bilingual: Polish primary, English secondary in lighter gray
ksef export FV/1/01 --lang en/pl          # bilingual: English primary, Polish secondary
ksef export FV/1/01 --lang dual           # alias for pl/en
```

## Disclaimer

This software is provided as-is, without any warranty. The author is not responsible for any data loss, financial damage, or other consequences arising from its use. Always verify synced data against the official KSeF portal.

# ksef

CLI tool for managing Polish e-invoices via [KSeF](https://www.podatki.gov.pl/ksef/) (Krajowy System e-Faktur). Syncs received and issued invoices from the KSeF API, stores them locally for offline browsing and search, and supports sending invoice XML files directly to KSeF.

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

## Disclaimer

This software is provided as-is, without any warranty. The author is not responsible for any data loss, financial damage, or other consequences arising from its use. Always verify synced data against the official KSeF portal.

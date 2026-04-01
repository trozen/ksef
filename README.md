# ksef

CLI tool for browsing Polish e-invoices from [KSeF](https://www.podatki.gov.pl/ksef/) (Krajowy System e-Faktur). Syncs invoices from the KSeF API and stores them locally for offline browsing and search.

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

Create `~/.config/trozen/ksef/config.toml`:

```toml
[ksef]
nip = "YOUR_NIP"
environment = "prod"          # test / demo / prod
token_path = "/path/to/your/ksef.token"
data_dir = "/path/to/safe/storage/ksef"  # where invoices will be stored

[ksef.sync]
date_from = "2026-01-01"      # earliest date to sync from
max_per_sync = 100
```

## Getting a KSeF Token

Log into https://ap.ksef.mf.gov.pl, authenticate with Profil Zaufany or a qualified electronic signature, and generate a token with at least invoice-reading permissions. Save the token value to the file referenced by `token_path` in the config (e.g. `~/.config/trozen/ksef/ksef.token`).

Treat the token as a password — keep it out of version control and restrict file permissions (`chmod 600`).

Official documentation: https://ksef.podatki.gov.pl

## Usage

Running `ksef` with no arguments shows a dashboard with config summary and recent invoices.

```
ksef                     # dashboard
ksef sync                # fetch new invoices (incremental)
ksef sync -f             # force re-sync last 30 days
ksef list                # list all invoices
ksef list -s Januszex    # filter by seller
ksef show 1              # show invoice #1 from the list
ksef show FV/1/01        # match by invoice number
ksef show Januszex       # match by seller name
```

## Disclaimer

This software is provided as-is, without any warranty. The author is not responsible for any data loss, financial damage, or other consequences arising from its use. Always verify synced data against the official KSeF portal.

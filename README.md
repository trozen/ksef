# ksef

CLI tool for browsing and managing Polish e-invoices from [KSeF](https://www.podatki.gov.pl/ksef/) (Krajowy System e-Faktur).

Syncs invoices from the KSeF API and stores them locally for offline browsing.

## Installation

```
uv pip install .
```

Or install as a standalone tool:

```
uv tool install .
```

Requires Python 3.12+.

## Configuration

Create `~/.config/trozen/ksef/config.toml`:

```toml
[ksef]
nip = "YOUR_NIP"
environment = "prod"          # test / demo / prod
token_path = "/path/to/your/ksef.token"
data_dir = "/path/to/safe/storage/ksef"

[ksef.sync]
date_from = "2026-01-01"
max_per_sync = 100
```

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

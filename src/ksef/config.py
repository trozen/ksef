from __future__ import annotations

import os
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

import tomli_w
from rich.console import Console

CONFIG_DIR = Path.home() / ".config" / "trozen" / "ksef"
CONFIG_PATH = CONFIG_DIR / "config.toml"
LOCAL_CONFIG_NAME = "ksef.config.toml"

KSEF_ENVIRONMENTS = {
    "test": "https://api-test.ksef.mf.gov.pl/v2",
    "demo": "https://api-demo.ksef.mf.gov.pl/v2",
    "prod": "https://api.ksef.mf.gov.pl/v2",
}

KSEF_QR_BASE_URLS = {
    "test": "https://qr-test.ksef.mf.gov.pl",
    "demo": "https://qr-demo.ksef.mf.gov.pl",
    "prod": "https://qr.ksef.mf.gov.pl",
}


@dataclass
class SyncConfig:
    date_from: str = "2026-01-01"
    max_per_sync: int = 100


@dataclass
class Config:
    nip: str = ""
    environment: str = "prod"
    token_path: str = ""
    data_dir: str = ""
    allow_send: bool = False
    sync: SyncConfig = field(default_factory=SyncConfig)

    @property
    def base_url(self) -> str:
        return KSEF_ENVIRONMENTS.get(self.environment, KSEF_ENVIRONMENTS["prod"])

    @property
    def data_path(self) -> Path:
        return Path(self.data_dir)

    @property
    def invoices_dir(self) -> Path:
        return self.data_path / "invoices"

    @property
    def profiles_dir(self) -> Path:
        return self.data_path / "profiles"

    @property
    def sync_state_path(self) -> Path:
        return self.data_path / "sync.json"

    @property
    def session_cache_path(self) -> Path:
        return self.data_path / "session-cache.json"

    @property
    def pending_sessions_path(self) -> Path:
        return self.data_path / "pending-sessions.json"

    def validate(self) -> list[str]:
        errors = []
        if not self.nip:
            errors.append("ksef.nip is required")
        if not self.token_path:
            errors.append("ksef.token_path is required")
        if not self.data_dir:
            errors.append("ksef.data_dir is required — set it to a safe location for invoice storage")
        elif not Path(self.data_dir).parent.exists():
            errors.append(f"Parent directory of data_dir does not exist: {self.data_dir}")
        if self.environment not in KSEF_ENVIRONMENTS:
            errors.append(f"ksef.environment must be one of: {', '.join(KSEF_ENVIRONMENTS)}")
        if self.token_path and not Path(self.token_path).exists():
            errors.append(f"Token file not found: {self.token_path}")
        return errors


def resolve_config_path(cli_path: str | None = None) -> Path:
    """Resolve config path: CLI flag > KSEF_CONFIG env var > local ksef.config.toml > default."""
    if cli_path:
        return Path(cli_path)
    env_path = os.environ.get("KSEF_CONFIG")
    if env_path:
        return Path(env_path)
    local = Path.cwd() / LOCAL_CONFIG_NAME
    if local.exists():
        return local
    return CONFIG_PATH


def peek_environment(path: Path) -> str | None:
    """Read just the environment field from config without full validation."""
    try:
        with open(path, "rb") as f:
            raw = tomllib.load(f)
        return raw.get("ksef", {}).get("environment")
    except Exception:
        return None


def load_config(path: Path | None = None) -> Config:
    config_path = path or CONFIG_PATH
    if not config_path.exists():
        _print_config_instructions(config_path)
        sys.exit(1)

    with open(config_path, "rb") as f:
        raw = tomllib.load(f)

    ksef = raw.get("ksef", {})
    sync_raw = ksef.get("sync", {})

    cfg = Config(
        nip=ksef.get("nip", ""),
        environment=ksef.get("environment", "prod"),
        token_path=ksef.get("token_path", ""),
        data_dir=ksef.get("data_dir", ""),
        allow_send=bool(ksef.get("allow_send", False)),
        sync=SyncConfig(
            date_from=sync_raw.get("date_from", "2026-01-01"),
            max_per_sync=sync_raw.get("max_per_sync", 100),
        ),
    )

    errors = cfg.validate()
    if errors:
        console = Console(stderr=True)
        console.print(f"[red]Configuration errors in {config_path}:[/red]")
        for err in errors:
            console.print(f"  [red]•[/red] {err}")
        sys.exit(1)

    return cfg


def save_config(cfg: Config) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    data = {
        "ksef": {
            "nip": cfg.nip,
            "environment": cfg.environment,
            "token_path": cfg.token_path,
            "data_dir": cfg.data_dir,
            "sync": {
                "date_from": cfg.sync.date_from,
                "max_per_sync": cfg.sync.max_per_sync,
            },
        }
    }
    with open(CONFIG_PATH, "wb") as f:
        tomli_w.dump(data, f)


def _print_config_instructions(path: Path | None = None) -> None:
    console = Console(stderr=True)
    console.print(f"[red]Config file not found:[/red] {path or CONFIG_PATH}")
    console.print()
    console.print("Create it with the following contents:")
    console.print()
    example = """\
[ksef]
nip = "YOUR_NIP"
environment = "prod"          # test / demo / prod
token_path = "/path/to/your/ksef.token"
data_dir = "/path/to/safe/storage/ksef"

[ksef.sync]
date_from = "2026-01-01"
max_per_sync = 100"""
    console.print(example, style="dim")

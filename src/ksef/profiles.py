from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

import tomli_w


@dataclass
class Profile:
    name: str
    template_path: Path
    vat_rate: int = 23
    payment_days: int = 14
    output_prefix: str = "invoice_"
    defaults: dict[str, str] = field(default_factory=dict)


def _toml_path(name: str, profiles_dir: Path) -> Path:
    return profiles_dir / f"{name}.toml"


def _template_path(name: str, profiles_dir: Path) -> Path:
    return profiles_dir / f"{name}.xml"


def profile_exists(name: str, profiles_dir: Path) -> bool:
    return _toml_path(name, profiles_dir).exists()


def load_profile(name: str, profiles_dir: Path) -> Profile:
    toml_file = _toml_path(name, profiles_dir)
    if not toml_file.exists():
        raise FileNotFoundError(f"Profile '{name}' not found. Run: ksef profile list")
    with open(toml_file, "rb") as f:
        data = tomllib.load(f)
    return Profile(
        name=name,
        template_path=_template_path(name, profiles_dir),
        vat_rate=data.get("vat_rate", 23),
        payment_days=data.get("payment_days", 14),
        output_prefix=data.get("output_prefix", "invoice_"),
        defaults={k: str(v) for k, v in data.get("defaults", {}).items()},
    )


def create_profile(
    name: str,
    template_source: Path,
    profiles_dir: Path,
    vat_rate: int = 23,
    payment_days: int = 14,
    output_prefix: str = "invoice_",
) -> Profile:
    profiles_dir.mkdir(parents=True, exist_ok=True)
    dest = _template_path(name, profiles_dir)
    dest.write_text(template_source.read_text(encoding="utf-8"), encoding="utf-8")
    with open(_toml_path(name, profiles_dir), "wb") as f:
        tomli_w.dump({"vat_rate": vat_rate, "payment_days": payment_days, "output_prefix": output_prefix, "defaults": {}}, f)
    return load_profile(name, profiles_dir)


def list_profiles(profiles_dir: Path) -> list[Profile]:
    if not profiles_dir.exists():
        return []
    return sorted(
        [load_profile(p.stem, profiles_dir) for p in profiles_dir.glob("*.toml")],
        key=lambda p: p.name,
    )


def delete_profile(name: str, profiles_dir: Path) -> None:
    if not profile_exists(name, profiles_dir):
        raise FileNotFoundError(f"Profile '{name}' not found.")
    _toml_path(name, profiles_dir).unlink()
    if _template_path(name, profiles_dir).exists():
        _template_path(name, profiles_dir).unlink()

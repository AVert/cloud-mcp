"""Settings, read from environment variables (see .env.example)."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

DEFAULT_API_URL = "https://api.sweb.ru"
_PACKAGE_SPECS = Path(__file__).resolve().parent / "specs"  # installed wheel
DEFAULT_SPECS_DIR = (
    _PACKAGE_SPECS if _PACKAGE_SPECS.is_dir() else Path(__file__).resolve().parents[2] / "specs"
)
_TRUE = {"1", "true", "yes", "on"}


def _flag(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    return default if raw is None or raw == "" else raw.strip().lower() in _TRUE


@dataclass(frozen=True)
class Account:
    name: str
    login: str
    password: str


def _parse_accounts(raw: str) -> tuple[Account, ...]:
    """SWEB_ACCOUNTS_FILE: {"name": {"login": "...", "password": "..."}}
    or {"name": "login:password"}."""
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("SWEB_ACCOUNTS_FILE must contain a JSON object")
    out: list[Account] = []
    for name, value in data.items():
        if isinstance(value, str):
            login, _, password = value.partition(":")
        elif isinstance(value, dict):
            login, password = str(value.get("login", "")), str(value.get("password", ""))
        else:
            raise ValueError(f"account {name!r}: expected object or 'login:password'")
        out.append(Account(str(name), login, password))
    return tuple(out)


def _load_accounts() -> tuple[tuple[Account, ...], str]:
    """Single source of truth: the JSON file named by SWEB_ACCOUNTS_FILE."""
    path = os.environ.get("SWEB_ACCOUNTS_FILE", "").strip()
    if not path:
        return (), ""
    raw = Path(path).expanduser().read_text(encoding="utf-8")
    accounts = _parse_accounts(raw) if raw.strip() else ()
    default = os.environ.get("SWEB_ACCOUNT", "").strip()
    if accounts and not default:
        default = accounts[0].name
    return accounts, default


@dataclass(frozen=True)
class Settings:
    api_url: str = DEFAULT_API_URL
    login: str = ""
    password: str = ""
    accounts: tuple[Account, ...] = ()
    default_account: str = ""
    timeout: float = 30.0
    groups: frozenset[str] = frozenset()  # empty = all
    readonly: bool = True
    allow_destructive: bool = False
    specs_dir: Path = DEFAULT_SPECS_DIR
    overrides_path: Path | None = None
    max_concurrency: int = 4
    min_interval: float = 0.2  # seconds between request starts
    max_retries: int = 3
    backoff_base: float = 0.5  # seconds; doubles per attempt, capped at 30

    @classmethod
    def from_env(cls) -> Settings:
        groups = {g.strip().strip("/") for g in os.environ.get("SWEB_GROUPS", "").split(",")}
        overrides = os.environ.get("SWEB_OVERRIDES") or None
        accounts, default_account = _load_accounts()
        return cls(
            api_url=(os.environ.get("SWEB_API_URL") or DEFAULT_API_URL).rstrip("/"),
            accounts=accounts,
            default_account=default_account,
            timeout=float(os.environ.get("SWEB_TIMEOUT") or 30),
            groups=frozenset(g for g in groups if g),
            readonly=_flag("SWEB_READONLY", True),
            allow_destructive=_flag("SWEB_ALLOW_DESTRUCTIVE", False),
            specs_dir=Path(os.environ.get("SWEB_SPECS_DIR") or DEFAULT_SPECS_DIR),
            overrides_path=Path(overrides) if overrides else None,
            max_concurrency=int(os.environ.get("SWEB_MAX_CONCURRENCY") or 4),
            min_interval=float(os.environ.get("SWEB_MIN_INTERVAL") or 0.2),
            max_retries=int(os.environ.get("SWEB_MAX_RETRIES") or 3),
            backoff_base=float(os.environ.get("SWEB_BACKOFF_BASE") or 0.5),
        )

    def account(self, name: str = "") -> Account:
        """Named account, or the default one when name is empty."""
        want = name or self.default_account
        for acc in self.accounts:
            if acc.name == want:
                return acc
        known = ", ".join(a.name for a in self.accounts) or "none"
        raise KeyError(f"unknown account {want!r} (known: {known})")

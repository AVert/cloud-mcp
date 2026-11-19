"""Settings and per-provider credentials.

Accounts live in one JSON file (``CLOUD_ACCOUNTS_FILE``), because a single server now talks to
several providers; the file is read lazily so a token can be added without a restart.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_ACCOUNTS = Path.home() / ".config" / "cloud-mcp" / "accounts.json"
KNOWN_PROVIDERS = frozenset({"timeweb", "selectel", "tilda"})
DEFAULT_CACHE = Path.home() / ".cache" / "cloud-mcp"
TRISTATE = {"1": True, "true": True, "yes": True, "0": False, "false": False, "no": False}


def env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name, "").strip().lower()
    return TRISTATE.get(raw, default)


def env_list(name: str) -> list[str]:
    raw = os.environ.get(name, "").replace(" ", ",")
    return [item for item in raw.split(",") if item]


@dataclass(frozen=True)
class Account:
    provider: str
    token: str = ""
    static_token: str = ""
    login: str = ""
    password: str = ""
    account_id: str = ""
    project_id: str = ""
    project_token: str = ""
    region: str = ""
    public_key: str = ""
    private_key: str = ""
    sub_accounts: dict[str, dict[str, str]] = field(default_factory=dict)
    default_account: str = ""

    def as_env(self) -> str:
        return "configured" if self.usable else "missing"

    @property
    def usable(self) -> bool:
        return bool(
            self.token
            or self.project_token
            or self.static_token
            or self.login
            or self.public_key
            or self.private_key
        )


@dataclass(frozen=True)
class Settings:
    accounts_file: Path = DEFAULT_ACCOUNTS
    cache_dir: Path = DEFAULT_CACHE
    providers: tuple[str, ...] = ()
    readonly: bool = False
    allow_destructive: bool = False
    timeout: float = 60.0
    accounts: dict[str, Account] = field(default_factory=dict)

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            accounts_file=Path(
                os.environ.get("CLOUD_ACCOUNTS_FILE")
                or os.environ.get("SWEB_ACCOUNTS_FILE")
                or DEFAULT_ACCOUNTS
            ).expanduser(),
            cache_dir=Path(os.environ.get("CLOUD_CACHE_DIR") or DEFAULT_CACHE).expanduser(),
            providers=tuple(env_list("CLOUD_PROVIDERS")),
            readonly=env_bool("CLOUD_READONLY", False),
            allow_destructive=env_bool("CLOUD_ALLOW_DESTRUCTIVE", False),
            timeout=float(os.environ.get("CLOUD_TIMEOUT") or 60),
            accounts=load_accounts(),
        )

    def account(self, provider: str) -> Account:
        existing = self.accounts.get(provider)
        if existing:
            return existing
        if provider == "sweb":
            token = os.environ.get("SWEB_TOKEN", "")
            login = os.environ.get("SWEB_LOGIN", "")
            password = os.environ.get("SWEB_PASSWORD", "")
            if token or (login and password):
                return Account(provider="sweb", token=token, login=login, password=password)
        return Account(provider=provider)


def _sub_accounts(raw: object) -> dict[str, dict[str, str]]:
    if not isinstance(raw, dict):
        return {}
    parsed: dict[str, dict[str, str]] = {}
    for name, value in raw.items():
        if isinstance(value, str):
            login, _, password = value.partition(":")
        elif isinstance(value, dict):
            login, password = str(value.get("login", "")), str(value.get("password", ""))
        else:
            continue
        parsed[str(name)] = {"login": login, "password": password}
    return parsed


def _entry(provider: str, raw: object) -> Account:
    if isinstance(raw, str):
        return Account(provider=provider, token=raw)
    if not isinstance(raw, dict):
        return Account(provider=provider)
    return Account(
        provider=provider,
        token=str(raw.get("token") or raw.get("iam_token") or ""),
        project_token=str(raw.get("project_token") or ""),
        project_id=str(raw.get("project_id") or ""),
        static_token=str(raw.get("static_token") or ""),
        login=str(raw.get("login") or raw.get("service_user") or ""),
        password=str(raw.get("password") or raw.get("secret") or ""),
        account_id=str(raw.get("account_id") or raw.get("domain") or ""),
        region=str(raw.get("region") or ""),
        public_key=str(raw.get("public_key") or raw.get("publickey") or ""),
        private_key=str(raw.get("private_key") or raw.get("privatekey") or ""),
    )


def _sweb_env_account() -> Account:
    """Compatibility with the old per-method sweb-mcp: SWEB_TOKEN or SWEB_ACCOUNTS_FILE
    ({"name": {"login","password"}} or {"name": "login:password"}) + SWEB_ACCOUNT default."""
    token = os.environ.get("SWEB_TOKEN") or ""
    file = os.environ.get("SWEB_ACCOUNTS_FILE") or ""
    subs: dict[str, dict[str, str]] = {}
    if file:
        try:
            raw = json.loads(Path(file).expanduser().read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            raw = {}
        if isinstance(raw, dict):
            subs = _sub_accounts(raw)
    default = os.environ.get("SWEB_ACCOUNT") or ""
    login = os.environ.get("SWEB_LOGIN") or ""
    password = os.environ.get("SWEB_PASSWORD") or ""
    if subs and not (login or token):
        chosen = subs.get(default) or next(iter(subs.values()))
        login, password = chosen.get("login", ""), chosen.get("password", "")
    return Account(
        provider="sweb",
        token=token,
        login=login,
        password=password,
        sub_accounts=subs,
        default_account=default,
    )


def load_accounts(path: Path | str | None = None) -> dict[str, Account]:
    path = Path(path or os.environ.get("CLOUD_ACCOUNTS_FILE") or DEFAULT_ACCOUNTS).expanduser()
    accounts: dict[str, Account] = {}
    if path.exists():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            raw = {}
        if isinstance(raw, dict):
            for provider, value in raw.items():
                entry = _entry(provider, value)
                if entry.usable and provider in KNOWN_PROVIDERS:
                    accounts[provider] = entry
            if not accounts and raw and all(isinstance(v, str) and v for v in raw.values()):
                # Legacy single-provider file like {"default": "<token>"}: treat it as timeweb.
                accounts["timeweb"] = _entry("timeweb", next(iter(raw.values())))
    timeweb_token = os.environ.get("TIMEWEB_TOKEN") or ""
    timeweb_file = os.environ.get("TIMEWEB_ACCOUNTS_FILE") or ""
    if "timeweb" not in accounts:
        if timeweb_token:
            accounts["timeweb"] = Account(provider="timeweb", token=timeweb_token)
        elif timeweb_file and Path(timeweb_file).exists():
            try:
                legacy = json.loads(Path(timeweb_file).read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                legacy = {}
            default = os.environ.get("TIMEWEB_ACCOUNT") or ""
            value = (
                legacy.get(default)
                if default and default in legacy
                else next(iter(legacy.values()), None)
            )
            entry = _entry("timeweb", value)
            if entry.token:
                accounts["timeweb"] = entry
    if "selectel" not in accounts:
        static = os.environ.get("SELECTEL_STATIC_TOKEN") or ""
        iam = os.environ.get("SELECTEL_IAM_TOKEN") or ""
        login = os.environ.get("SELECTEL_SERVICE_USER") or ""
        password = os.environ.get("SELECTEL_SERVICE_PASSWORD") or ""
        if static or iam or login:
            accounts["selectel"] = Account(
                provider="selectel",
                token=iam,
                static_token=static,
                login=login,
                password=password,
                account_id=os.environ.get("SELECTEL_ACCOUNT_ID") or "",
                region=os.environ.get("SELECTEL_REGION") or "",
            )
    if "sweb" not in accounts:
        sweb = _sweb_env_account()
        if sweb.usable:
            accounts["sweb"] = sweb
    tilda_public = os.environ.get("TILDA_PUBLIC_KEY") or ""
    tilda_private = os.environ.get("TILDA_PRIVATE_KEY") or ""
    if "tilda" not in accounts and (tilda_public or tilda_private):
        accounts["tilda"] = Account(
            provider="tilda", public_key=tilda_public, private_key=tilda_private
        )
    return accounts

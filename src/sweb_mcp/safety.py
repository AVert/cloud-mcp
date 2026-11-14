"""Classify API methods (the spec has no read/write flags) and gate execution.

Kinds: read < write < destructive / paid. Order: overrides -> PAID table ->
destructive regex -> read regex -> write (default, conservative).
Manual overrides: JSON file {"/vps:reboot": "write", ...} via SWEB_OVERRIDES.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from .config import Settings

KINDS = ("read", "write", "destructive", "paid")

# Orders / money / plan changes (billable). key = "<path>:<method>".
PAID = {
    "/vps:create", "/vps:createFirst", "/vps:copy", "/vps:changePlan",
    "/balancer:create", "/balancer:edit",
    "/dbaas:createInstance", "/dbaas:editInstance",
    "/domains:reg", "/domains:regList", "/domains:prolong", "/domains:prolongList",
    "/domains/bonus:buy",
    "/vh/ddg:enable", "/monitoring:enable", "/monitoring:change",
    "/vh/partnerProgram:createOrderVh", "/vh/partnerProgram:createOrderVip",
    "/vh/partnerProgram:createOrderVps", "/vh/partnerProgram:sendWithdrawalOrder",
    "/vh/ssl:prolongCertificate", "/vps/ssl:orderSubmit",
    "/vps/ip:add", "/vps/ip:addProtected", "/vps/remoteBackup:create",
}
# Names that look mutating but only read.
READ_EXPLICIT = {"createEnable", "checkLogin", "regAvailable", "validateUsers", "getPmaUser",
                 "enableInfo", "standardPlans", "vipPlans", "vpsOsConfig", "plans", "logs", "load"}

_DESTRUCTIVE = re.compile(
    r"^(remove|del|delete|drop|reinstall|restore|move|powerOff|reboot|databaseMysqlImport)"
    r"|Delete|Remove|Drop|Restore|Import")
_READ = re.compile(
    r"^(index|info|history|getinfo|serverInfo|isRunning|price\w*|count\w*|download\w*)$"
    r"|^(get|is)|Get[A-Z]|(Info|Config)$")
_READ_LIST = re.compile(r"List$")
_LIST_MUTATORS = re.compile(r"^(reg|move|remove|prolong|changeProlong|activate|deactivate)")


def load_overrides(path: Path | None) -> dict[str, str]:
    if not path:
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    bad = {v for v in data.values() if v not in KINDS}
    if bad:
        raise ValueError(f"invalid override kinds: {bad}")
    return data


def classify(path: str, name: str, overrides: dict[str, str] | None = None) -> str:
    key = f"{path}:{name}"
    if overrides and key in overrides:
        return overrides[key]
    if key in PAID:
        return "paid"
    if name in READ_EXPLICIT:
        return "read"
    if _DESTRUCTIVE.search(name):
        return "destructive"
    if _READ.search(name) or (_READ_LIST.search(name) and not _LIST_MUTATORS.search(name)):
        return "read"
    return "write"


def authorize(kind: str, confirm: bool, s: Settings) -> str | None:
    """Return a refusal message, or None if the call may proceed."""
    if kind == "read":
        return None
    if s.readonly:
        return f"Refused: {kind} operation while SWEB_READONLY=1. Set SWEB_READONLY=0 to enable."
    if kind in ("destructive", "paid") and not s.allow_destructive:
        return f"Refused: {kind} operation requires SWEB_ALLOW_DESTRUCTIVE=1."
    if not confirm:
        return f"Refused: {kind} operation requires confirm=true."
    return None

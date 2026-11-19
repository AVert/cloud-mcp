"""Classify every operation as read / write / destructive / paid before it is snapshotted.

The class is stored in the snapshot, so a call never guesses: the server only authorises what the
snapshot says. Rules are conservative — an unknown POST is `write` (needs `confirm`), never `read`.
"""

from __future__ import annotations

import re

from .normalize import Operation

READ_METHODS = frozenset({"get", "head"})
DESTRUCTIVE_WORDS = frozenset(
    {
        "delete",
        "reboot",
        "shutdown",
        "reset",
        "restore",
        "rollback",
        "regenerate",
        "reinstall",
        "detach",
        "unbind",
        "revoke",
        "terminate",
        "reissue",
        "cancel",
        "purge",
        "destroy",
        "remove",
        "wipe",
        "poweroff",
        "hard_reboot",
        "hard_shutdown",
    }
)
PAID_RESOURCES = frozenset(
    {
        "servers",
        "server",
        "databases",
        "database",
        "clusters",
        "cluster",
        "disks",
        "disk",
        "ips",
        "ip",
        "buckets",
        "bucket",
        "balancers",
        "registries",
        "instances",
        "volumes",
        "nodes",
        "node_groups",
        "floatingips",
        "floating_ips",
        "routers",
        "certificates",
        "domains",
        "mailboxes",
        "accounts",
        "projects",
        "federations",
        "backups",
        "checkpoints",
        "plans",
        "secrets",
        "configs",
        "clones",
        "upgrades",
    }
)


def _words(op: Operation) -> set[str]:
    return {w for w in op.tool.split("_") if w} | {
        w for w in op.path.strip("/").split("/") if w and not w.startswith("{")
    }


def classify(op: Operation) -> str:
    method = op.method.lower()
    if method in READ_METHODS:
        return "read"
    words = _words(op)
    tail = op.path.rstrip("/").rsplit("/", 1)[-1]
    opens_item = not tail.startswith("{")
    if method == "delete" or (words & DESTRUCTIVE_WORDS):
        return "destructive"
    if method == "post" and opens_item and (words & PAID_RESOURCES):
        return "paid"
    return "write"


RPC_PAID = {
    "/vps:create",
    "/vps:createFirst",
    "/vps:copy",
    "/vps:changePlan",
    "/balancer:create",
    "/balancer:edit",
    "/dbaas:createInstance",
    "/dbaas:editInstance",
    "/domains:reg",
    "/domains:regList",
    "/domains:prolong",
    "/domains:prolongList",
    "/domains/bonus:buy",
    "/vh/ddg:enable",
    "/monitoring:enable",
    "/monitoring:change",
    "/vh/partnerProgram:createOrderVh",
    "/vh/partnerProgram:createOrderVip",
    "/vh/partnerProgram:createOrderVps",
    "/vh/partnerProgram:sendWithdrawalOrder",
    "/vh/ssl:prolongCertificate",
    "/vps/ssl:orderSubmit",
    "/vps/ip:add",
    "/vps/ip:addProtected",
    "/vps/remoteBackup:create",
}

RPC_READ_EXPLICIT = {
    "createEnable",
    "checkLogin",
    "regAvailable",
    "validateUsers",
    "getPmaUser",
    "enableInfo",
    "standardPlans",
    "vipPlans",
    "vpsOsConfig",
    "plans",
    "logs",
    "load",
}

_RPC_DESTRUCTIVE = re.compile(
    r"^(remove|del|delete|drop|reinstall|restore|move|powerOff|reboot|databaseMysqlImport)"
    r"|Delete|Remove|Drop|Restore|Import"
)
_RPC_READ = re.compile(
    r"^(index|info|history|getinfo|serverInfo|isRunning|price\w*|count\w*|download\w*)$"
    r"|^(get|is)|Get[A-Z]|(Info|Config)$"
)
_RPC_READ_LIST = re.compile(r"List$")
_RPC_LIST_MUTATORS = re.compile(r"^(reg|move|remove|prolong|changeProlong|activate|deactivate)")


def classify_rpc(path: str, name: str, overrides: dict[str, str] | None = None) -> str:
    """SpaceWeb JSON-RPC methods carry no read/write flags: infer from the name, with an
    explicit table for money/orders and for names that only look mutating."""
    key = f"{path}:{name}"
    if overrides and key in overrides:
        return overrides[key]
    if key in RPC_PAID:
        return "paid"
    if name in RPC_READ_EXPLICIT:
        return "read"
    if _RPC_DESTRUCTIVE.search(name):
        return "destructive"
    if _RPC_READ.search(name) or (
        _RPC_READ_LIST.search(name) and not _RPC_LIST_MUTATORS.search(name)
    ):
        return "read"
    return "write"

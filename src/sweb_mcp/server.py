"""MCP server: one tool per API method + meta tools (list / describe / call)."""

from __future__ import annotations

import json
import sys
from dataclasses import replace
from typing import Any

import mcp.types as types
from mcp.server.lowlevel import Server

from .client import SwebClient, SwebError
from .config import Account, Settings
from .safety import KINDS, authorize
from .spec import Method, in_groups, load_methods

META = {"sweb_list_methods", "sweb_describe", "sweb_call", "sweb_accounts", "sweb_use_account"}
INSTRUCTIONS = (
    "SpaceWeb (sweb.ru) API. Tools: <object>_<method> — sites_index, vps_index, domains_dns_info…\n"
    "1) Explore: sweb_list_methods(group=/search=) → sweb_describe(path, method) → call the tool.\n"
    "2) Accounts: sweb_accounts (list + current) → sweb_use_account(name) for this session, "
    'or pass account="name" on a single call.\n'
    "3) Safety: read runs freely; write needs confirm=true; destructive/paid need SWEB_READONLY=0 "
    "+ SWEB_ALLOW_DESTRUCTIVE=1.\n"
    '4) Errors: "[code] message"; -32603 = token expired (auto re-login), '
    "429 = rate limit (auto retry)."
)


def _text(data: Any) -> list[types.TextContent]:
    s = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False, indent=2)
    return [types.TextContent(type="text", text=s)]


def _summary(m: Method) -> dict[str, Any]:
    return {
        "tool": m.tool_name,
        "path": m.path,
        "method": m.name,
        "kind": m.kind,
        "description": m.description.splitlines()[0] if m.description else "",
    }


def _meta_tools(methods: list[Method], accounts: tuple[Account, ...] = ()) -> list[types.Tool]:
    groups = sorted({m.group for m in methods})
    tools = [
        types.Tool(
            name="sweb_list_methods",
            description="List available SpaceWeb API methods (optionally filtered).",
            inputSchema={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "group": {
                        "type": "string",
                        "description": f"Path prefix, e.g. {', '.join(groups)} or vh/mail",
                    },
                    "kind": {"type": "string", "enum": list(KINDS)},
                    "search": {
                        "type": "string",
                        "description": "Substring of method name or description",
                    },
                },
            },
            annotations=types.ToolAnnotations(readOnlyHint=True, openWorldHint=False),
        ),
        types.Tool(
            name="sweb_describe",
            description="Describe one API method: kind, description and parameter schema.",
            inputSchema={
                "type": "object",
                "additionalProperties": False,
                "required": ["path", "method"],
                "properties": {
                    "path": {"type": "string", "description": "Endpoint path, e.g. /vps/ip"},
                    "method": {"type": "string"},
                },
            },
            annotations=types.ToolAnnotations(readOnlyHint=True, openWorldHint=False),
        ),
        types.Tool(
            name="sweb_call",
            description=(
                "Call any API method by path+method. "
                "Safety rules are identical to the per-method tools."
            ),
            inputSchema={
                "type": "object",
                "additionalProperties": False,
                "required": ["path", "method"],
                "properties": {
                    "path": {"type": "string", "description": "Endpoint path, e.g. /vps/ip"},
                    "method": {"type": "string"},
                    "params": {"type": "object", "description": "Named method parameters"},
                    "account": {
                        "type": "string",
                        "description": "Account name (see sweb_accounts)",
                    },
                    "confirm": {"type": "boolean"},
                },
            },
            annotations=types.ToolAnnotations(
                readOnlyHint=False, destructiveHint=True, openWorldHint=True
            ),
        ),
    ]
    if accounts:
        tools += [
            types.Tool(
                name="sweb_accounts",
                description="List configured SpaceWeb accounts and the current default.",
                inputSchema={"type": "object", "additionalProperties": False, "properties": {}},
                annotations=types.ToolAnnotations(readOnlyHint=True, openWorldHint=False),
            ),
            types.Tool(
                name="sweb_use_account",
                description="Switch the default account for subsequent calls.",
                inputSchema={
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["name"],
                    "properties": {"name": {"type": "string", "description": "Account name"}},
                },
                annotations=types.ToolAnnotations(readOnlyHint=True, openWorldHint=False),
            ),
        ]
    return tools


def _method_tool(m: Method, with_account: bool = False) -> types.Tool:
    ro = m.kind == "read"
    desc = f"[{m.kind.upper()}] {m.description}".strip()
    schema = m.input_schema(with_confirm=not ro)
    if with_account:
        schema["properties"]["account"] = {
            "type": "string",
            "description": "Account name (see sweb_accounts); default when omitted",
        }
    return types.Tool(
        name=m.tool_name,
        description=desc,
        inputSchema=schema,
        annotations=types.ToolAnnotations(
            readOnlyHint=ro, destructiveHint=m.kind in ("destructive", "paid"), openWorldHint=True
        ),
    )


def build_server(settings: Settings, client: SwebClient | None = None) -> Server:
    methods = [
        m
        for m in load_methods(settings.specs_dir, settings.overrides_path)
        if in_groups(m, settings.groups)
    ]
    by_tool = {m.tool_name: m for m in methods}
    by_key = {(m.path, m.name): m for m in methods}
    clients: dict[str, SwebClient] = {}
    state = {"account": settings.default_account}
    multi = len(settings.accounts) > 1
    server = Server("sweb-mcp", instructions=INSTRUCTIONS)

    def api_for(name: str = "") -> SwebClient:
        if client is not None:
            return client
        if not settings.accounts:
            raise SwebError(
                "config", "no accounts: set SWEB_ACCOUNTS_FILE to a JSON file (see .env.example)"
            )
        acc = settings.account(name or state["account"])
        if acc.name not in clients:
            clients[acc.name] = SwebClient(
                replace(settings, login=acc.login, password=acc.password)
            )
        return clients[acc.name]

    @server.list_tools()
    async def list_tools() -> list[types.Tool]:
        return _meta_tools(methods, settings.accounts) + [_method_tool(m, multi) for m in methods]

    async def run(
        m: Method, args: dict[str, Any], confirm: bool, account: str = ""
    ) -> list[types.TextContent]:
        if msg := authorize(m.kind, confirm, settings):
            raise SwebError("refused", msg)
        return _text(await api_for(account).call(m.path, m.name, args, retry=m.kind == "read"))

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any] | None) -> list[types.TextContent]:
        a = dict(arguments or {})
        if name == "sweb_accounts":
            return _text(
                {
                    "current": state["account"],
                    "accounts": [
                        {
                            "name": acc.name,
                            "login": acc.login,
                            "default": acc.name == state["account"],
                        }
                        for acc in settings.accounts
                    ],
                }
            )
        if name == "sweb_use_account":
            acc = settings.account(str(a.get("name", "")))
            state["account"] = acc.name
            return _text({"current": acc.name, "login": acc.login})
        if name == "sweb_list_methods":
            g, kind, q = (
                (a.get("group") or "").strip("/"),
                a.get("kind"),
                (a.get("search") or "").lower(),
            )
            rows = [
                _summary(m)
                for m in methods
                if (not g or in_groups(m, frozenset({g})))
                and (not kind or m.kind == kind)
                and (not q or q in m.name.lower() or q in m.description.lower())
            ]
            return _text({"count": len(rows), "methods": rows})
        if name in ("sweb_describe", "sweb_call"):
            m = by_key.get((str(a.get("path", "")).rstrip("/") or "/", a.get("method")))
            if m is None:
                raise SwebError(
                    "unknown",
                    f"No method {a.get('path')}:{a.get('method')} (see sweb_list_methods)",
                )
            if name == "sweb_describe":
                return _text(
                    {
                        **_summary(m),
                        "description": m.description,
                        "inputSchema": m.input_schema(with_confirm=m.kind != "read"),
                    }
                )
            return await run(
                m, dict(a.get("params") or {}), bool(a.get("confirm")), str(a.get("account") or "")
            )
        m = by_tool.get(name)
        if m is None:
            raise SwebError("unknown", f"Unknown tool: {name}")
        return await run(m, a, bool(a.pop("confirm", False)), str(a.pop("account", "") or ""))

    return server


def log(msg: str) -> None:
    print(f"[sweb-mcp] {msg}", file=sys.stderr, flush=True)

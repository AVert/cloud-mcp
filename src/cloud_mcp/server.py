"""MCP server: three discovery tools and one dispatcher, provider is an argument, not env."""

from __future__ import annotations

import json
from dataclasses import replace

from mcp import types
from mcp.server import Server
from mcp.types import TextContent

from . import catalog as catalog_mod
from . import registry as registry_mod
from .client import CloudClient, CloudError, split_args
from .config import Settings, load_accounts
from .search import search

INSTRUCTIONS = """Multi-provider cloud MCP (timeweb, selectel, tilda). Discovery-first:
1) cloud_search(query, provider=...) -> ranked operations;
2) cloud_describe(provider, tool) -> full parameter/body schema;
3) cloud_call(provider, tool, args) -> execute (read runs freely; write needs confirm=true;
   destructive/paid also need CLOUD_READONLY=0 + CLOUD_ALLOW_DESTRUCTIVE=1).
Wide overview: cloud_catalog(provider) writes a greppable file with every operation.
Errors: '[code] message'."""


def _summary(op) -> dict[str, object]:
    out: dict[str, object] = {
        "provider": op.provider,
        "product": op.product,
        "tool": op.tool,
        "path": op.path,
        "method": op.method.upper(),
        "kind": op.kind,
        "summary": op.summary,
        "params": [p.name for p in op.params],
        "required": [p.name for p in op.params if p.required],
    }
    if not op.base_url:
        out["configured"] = False
        out["hint"] = f"needs SELECTEL_BASE_{op.product.upper().replace('-', '_')}"
    if op.deprecated:
        out["deprecated"] = True
    return out


def _text(payload: object) -> TextContent:
    return TextContent(type="text", text=json.dumps(payload, ensure_ascii=False, indent=2))


def build_server(settings: Settings | None = None):
    settings = settings or Settings.from_env()
    providers = registry_mod.enabled(registry_mod.load(), settings.providers)
    operations = [op for provider in providers.values() for op in provider.operations]
    by_tool = {(op.provider, op.tool): op for op in operations}
    state = {"settings": settings, "stamp": _accounts_stamp(settings)}
    client = CloudClient(settings)
    server = Server("cloud-mcp", instructions=INSTRUCTIONS)

    def current_settings() -> Settings:
        """Re-read the accounts file when it changes, so a new token or provider is picked up
        without a restart (the file is small; a stat check per tool call is cheap)."""
        current = state["settings"]
        stamp = _accounts_stamp(current)
        if stamp == state["stamp"] and current.accounts:
            return current
        accounts = load_accounts(current.accounts_file)
        if accounts or stamp != state["stamp"]:
            current = replace(current, accounts=accounts)
            state["settings"] = current
            state["stamp"] = stamp
        return current

    def provider_or_default(name: str) -> str:
        name = (name or "").strip().lower()
        if name:
            if name not in providers:
                raise CloudError("args", f"unknown provider '{name}': {sorted(providers)}")
            return name
        if len(providers) == 1:
            return next(iter(providers))
        raise CloudError("args", f"provider is required here: {sorted(providers)}")

    @server.list_tools()
    async def list_tools() -> list[types.Tool]:
        tools = [
            types.Tool(
                name="cloud_search",
                description=(
                    "Find API operations across providers by a free-form query (RU or EN); "
                    "returns the best matches with their tool names, methods and parameters"
                ),
                inputSchema={
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["query"],
                    "properties": {
                        "query": {"type": "string"},
                        "provider": {
                            "type": "string",
                            "description": "sweb|timeweb|selectel|tilda",
                        },
                        "product": {"type": "string", "description": "selectel product slug"},
                        "kind": {"type": "string", "description": "read|write|destructive|paid"},
                        "top": {"type": "integer", "description": "default 5"},
                    },
                },
                annotations=types.ToolAnnotations(readOnlyHint=True, openWorldHint=False),
            ),
            types.Tool(
                name="cloud_describe",
                description="Full parameter and body schema of one operation",
                inputSchema={
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["provider", "tool"],
                    "properties": {
                        "provider": {"type": "string"},
                        "tool": {"type": "string"},
                    },
                },
                annotations=types.ToolAnnotations(readOnlyHint=True, openWorldHint=False),
            ),
            types.Tool(
                name="cloud_call",
                description=(
                    "Execute an operation. Flat args are routed to path/query/header/body by the "
                    "operation schema; 'confirm': true is required for write/destructive/paid"
                ),
                inputSchema={
                    "type": "object",
                    "additionalProperties": True,
                    "required": ["provider", "tool"],
                    "properties": {
                        "provider": {"type": "string"},
                        "tool": {"type": "string"},
                        "confirm": {"type": boolean_hint(), "description": "required for writes"},
                    },
                },
                annotations=types.ToolAnnotations(
                    readOnlyHint=False, destructiveHint=True, openWorldHint=True
                ),
            ),
            types.Tool(
                name="cloud_providers",
                description="Providers, their products, operation counts and credential state",
                inputSchema={"type": "object", "additionalProperties": False, "properties": {}},
                annotations=types.ToolAnnotations(readOnlyHint=True, openWorldHint=False),
            ),
            types.Tool(
                name="cloud_catalog",
                description=(
                    "Write a greppable catalog file (rules + one line per operation) for a provider"
                ),
                inputSchema={
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["provider"],
                    "properties": {
                        "provider": {"type": "string"},
                        "path": {"type": "string", "description": "target file"},
                    },
                },
                annotations=types.ToolAnnotations(readOnlyHint=True, openWorldHint=False),
            ),
        ]
        return tools

    def boolean_hint() -> str:
        return "boolean"

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, object]) -> list[TextContent]:
        settings = current_settings()
        client.settings = settings
        try:
            return [await handle(name, dict(arguments), settings)]
        except CloudError as error:
            return [_text({"error": {"code": error.code, "message": error.message}})]

    async def handle(name: str, a: dict[str, object], settings: Settings) -> TextContent:
        if name == "cloud_search":
            provider = str(a.get("provider") or "").strip().lower()
            if provider and provider not in providers:
                raise CloudError("args", f"unknown provider '{provider}': {sorted(providers)}")
            scope = [op for op in operations if not provider or op.provider == provider]
            hits = search(
                scope,
                str(a.get("query") or ""),
                int(a.get("top") or 5),
                product=str(a.get("product") or ""),
                kind=str(a.get("kind") or ""),
            )
            return _text(
                {
                    "query": a.get("query"),
                    "matched": len(hits),
                    "methods": [_summary(op) for op in hits],
                    "hint": "cloud_describe(provider, tool) for the full schema",
                }
            )
        if name == "cloud_describe":
            provider = provider_or_default(str(a.get("provider") or ""))
            op = by_tool.get((provider, str(a.get("tool") or "")))
            if op is None:
                raise CloudError(
                    "args", f"unknown tool '{a.get('tool')}' for {provider}: use cloud_search"
                )
            return _text(
                {
                    **_summary(op),
                    "base_url": op.base_url,
                    "auth": op.auth,
                    "params": [
                        {
                            "name": p.name,
                            "in": p.location,
                            "required": p.required,
                            **({"schema": p.schema} if p.schema else {}),
                            **({"description": p.description} if p.description else {}),
                        }
                        for p in op.params
                    ],
                    **({"body": op.body} if op.body else {}),
                }
            )
        if name == "cloud_call":
            provider = provider_or_default(str(a.get("provider") or ""))
            op = by_tool.get((provider, str(a.get("tool") or "")))
            if op is None:
                raise CloudError(
                    "args", f"unknown tool '{a.get('tool')}' for {provider}: use cloud_search"
                )
            confirm = a.get("confirm") is True
            authorize(op, settings, confirm)
            account_name = str(a.get("account") or "")
            args = {
                k: v for k, v in a.items() if k not in ("provider", "tool", "confirm", "account")
            }
            path, query, body = split_args(op, args)
            result = await client.request(op, path, query, body, account_name)
            return _text({"status": result.status, "url": result.url, "body": result.body})
        if name == "cloud_providers":
            current = current_settings()
            providers_info = []
            for name, provider in providers.items():
                account = current.account(name)
                info: dict[str, object] = {
                    "provider": name,
                    "title": provider.title,
                    "operations": len(provider.operations),
                    "products": provider.counts(),
                    "credentials": account.as_env(),
                    "accounts_file": str(current.accounts_file),
                }
                if name == "selectel":
                    info["credential_kinds"] = {
                        "iam_account": bool(account.token or account.login),
                        "iam_project": bool(
                            account.project_token or (account.login and account.project_id)
                        ),
                        "static": bool(account.static_token),
                    }
                providers_info.append(info)
            return _text({"providers": providers_info})
        if name == "cloud_catalog":
            provider = providers[provider_or_default(str(a.get("provider") or ""))]
            target = str(a.get("path") or "") or str(
                settings.cache_dir / f"catalog-{provider.name}.md"
            )
            return _text(
                catalog_mod.write_catalog(provider, __import__("pathlib").Path(target).expanduser())
            )
        raise CloudError("args", f"unknown tool {name}")

    return server


def _accounts_stamp(settings: Settings) -> tuple[str, float, int]:
    try:
        stat = settings.accounts_file.stat()
    except OSError:
        return (str(settings.accounts_file), 0.0, 0)
    return (str(settings.accounts_file), stat.st_mtime, stat.st_size)


def authorize(op, settings: Settings, confirm: bool) -> None:
    if op.kind == "read":
        return
    if settings.readonly:
        raise CloudError("readonly", f"{op.kind} is blocked by CLOUD_READONLY=1", 403)
    if op.kind in ("destructive", "paid") and not settings.allow_destructive:
        raise CloudError(
            "confirm",
            f"{op.kind} needs CLOUD_READONLY=0 and CLOUD_ALLOW_DESTRUCTIVE=1",
            403,
        )
    if not confirm:
        raise CloudError("confirm", f"{op.kind} operation needs confirm=true", 403)


def main() -> None:
    import anyio
    from mcp.server.stdio import stdio_server

    async def run() -> None:
        server = build_server()
        async with stdio_server() as (read, write):
            await server.run(read, write, server.create_initialization_options())

    anyio.run(run)


if __name__ == "__main__":
    main()

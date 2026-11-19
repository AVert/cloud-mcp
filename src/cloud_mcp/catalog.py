"""Offline catalog: rules of the provider plus one line per operation, written to a greppable file.

This is the "read here" file of the discovery-first interface: the model greps it instead of
paging through cloud_search.
"""

from __future__ import annotations

from pathlib import Path

from .registry import Provider


def render(provider: Provider) -> str:
    lines = [
        f"# {provider.title} — how to work through cloud-mcp",
        "",
        "Call `cloud_search` with a free-form query, `cloud_describe(provider, tool)` for the full",
        "schema, then `cloud_call(provider, tool, args)`. Unknown operations: grep this file.",
        "",
        "- `cloud_call` routes flat args by the parameter table: path/query/header go where the",
        "  schema says, unknown args become the JSON body.",
        "- Lists are paginated: pass limit/offset (selectel uses per-page/page or size/page).",
        "- `[read]` is free; `[write]` needs confirm=true; `[destructive]`/`[paid]` also need",
        "  CLOUD_READONLY=0 and CLOUD_ALLOW_DESTRUCTIVE=1.",
        "- Errors come back as `[code] message`.",
    ]
    if provider.name == "selectel":
        lines += [
            "- Auth is per product: account APIs take an IAM token (X-Auth-Token), legacy ones",
            "  (tickets, billing) take a static token (X-Token). Provide both in the accounts",
            "  file; without login/password of a service user only products that accept the",
            "  static token will work.",
            "- Products listed with `base: none` need SELECTEL_BASE_<SLUG> (region hosts).",
        ]
    lines += ["", f"# Catalog ({len(provider.operations)} operations)", ""]
    current = None
    for op in sorted(provider.operations, key=lambda o: (o.product, o.tool)):
        if op.product != current:
            current = op.product
            lines += ["", f"## {current}", ""]
        required = ", ".join(p.name for p in op.params if p.required) or "-"
        deprecated = " (deprecated)" if op.deprecated else ""
        base = f"\tbase: {op.base_url}" if not op.base_url else ""
        lines.append(
            f"{op.tool}\t{op.method.upper()} {op.path}\t[{op.kind}]{deprecated}\t"
            f"{op.summary or op.path}{base}\trequired: {required}"
        )
    return "\n".join(lines) + "\n"


def write_catalog(provider: Provider, path: Path) -> dict[str, object]:
    text = render(provider)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return {
        "path": str(path),
        "operations": len(provider.operations),
        "bytes": len(text.encode()),
        "products": len(provider.products),
    }

#!/usr/bin/env python3
"""Refresh the API snapshots from the providers' public documentation.

    python scripts/sync_specs.py            # download and rewrite specs/
    python scripts/sync_specs.py --check    # report drift, exit 1 when something changed

The docs are the source of truth; ``specs/`` is a normalised snapshot that the server reads at
runtime, so a live call never depends on network access to a documentation site.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from cloud_mcp.core.normalize import Operation, build_operations, document_base, security_auth  # noqa: E402
from cloud_mcp.core.safety import classify  # noqa: E402

SPECS = ROOT / "specs"
TIMEWEB_SPEC = "https://timeweb.cloud/api-docs-data/bundle.json"
SELECTEL_INDEX = "https://docs.selectel.ru/api/"
SELECTEL_SPEC = "https://docs.selectel.ru/api/{slug}.json"
SELECTEL_API = "https://api.selectel.ru"
SWEB_DOCS_URL = "https://apidoc.sweb.ru"
SWEB_API = "https://api.sweb.ru"
SWEB_NEEDLE = "JSON.parse("

DEFAULT_REGION = "ru-2"
REGION_TOKEN = re.compile(r"(?:^|\.)([a-z]{2}-\d+)\.")
DOCS_URLS = "https://docs.selectel.ru/api/urls/"

SELECTEL_BASE = {
    "audit-logs": "https://api.selectel.ru/audit-logs",
    "cdn": "https://api.selectel.ru/cdn/v3",
    "certificates-manager": "https://cloud.api.selcloud.ru/certificate-manager/v1",
    "craas": "https://cr.selcloud.ru/api",
    "dns-actual": "https://api.selectel.ru/domains/v2",
    "dns-legacy": "https://api.selectel.ru/domains/v1",
    "email-service": "https://api.selectel.ru/ses",
    "global-router": "https://api.selectel.ru/naas/v1",
    "lets-encrypt-certificates": "https://api.selectel.ru/certs/le",
    "mobile-farm": "https://api.selectel.ru/mobfarm",
    "secrets-manager": "https://cloud.api.selcloud.ru/secrets-manager/v1",
    "tickets": "https://api.selectel.ru/support",
    "tickets-attachments": "https://api.selectel.ru/files",
    "users-and-roles": SELECTEL_API,
    "balance": SELECTEL_API,
    "balance-statistics": SELECTEL_API,
    "billing-reports": SELECTEL_API,
    "billing-transactions": SELECTEL_API,
    "federations": SELECTEL_API,
    "ip-addresses": f"{SELECTEL_API}/ipam/v1",
    "quota-management": SELECTEL_API,
    "cloud-projects-and-resources": f"{SELECTEL_API}/vpc/resell/v2",
    "dedicated": f"{SELECTEL_API}/servers/v2",
}

SELECTEL_AUTH = {
    "iam_token_account_scoped": "iam_account",
    "iam_token_project_scoped": "iam_project",
    "static_token": "static",
    "X-Auth-Token": "iam_account",
}


def fetch(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "cloud-mcp sync"})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request, timeout=120) as response:
        return response.read()


def load_json(url: str) -> Any:
    return json.loads(fetch(url).decode("utf-8"))


def selectel_base_table() -> dict[str, dict[str, str]]:
    """slug -> {region: url} from the docs URL tables (one row per API, one tab per region).

    Only selcloud.ru hosts are kept: servercore.com is the international brand of the same
    endpoints, and the account region selects between them at runtime.
    """
    html = fetch(DOCS_URLS).decode("utf-8", "replace")
    table: dict[str, dict[str, str]] = {}
    for row in re.split(r"<tr>", html)[1:]:
        slug_m = re.search(r"href=/api/([a-z0-9-]+)/", row)
        url_m = re.search(r"<code[^>]*>(https://[^<]+)</code>", row)
        if not slug_m or not url_m:
            continue
        url = url_m.group(1).strip().rstrip("/")
        if "selcloud.ru" not in url:
            continue
        host = url.split("/", 3)[2]
        region_m = REGION_TOKEN.search(host)
        region = region_m.group(1) if region_m else "global"
        table.setdefault(slug_m.group(1), {}).setdefault(region, url)
    return table


def selectel_products() -> list[str]:
    html = fetch(SELECTEL_INDEX).decode("utf-8", "replace")
    pattern = re.compile(r"href=/api/([a-z0-9][a-z0-9-]*)/")
    return sorted(set(pattern.findall(html)) - {"api"})


def auth_of(doc: dict[str, Any]) -> str:
    """Product-wide fallback auth: operation-level ``security`` overrides this per call."""
    return security_auth(doc, None)


def _fit_base_to_paths(url: str, doc: dict[str, Any]) -> str:
    """Line up the docs URL with the spec paths: drop a doubled version segment, add the spec's
    basePath only when neither the URL nor the paths carry a version of their own."""
    url = url.rstrip("/")
    tail = url.rsplit("/", 1)[-1]
    url_versioned = bool(re.fullmatch(r"v\d+", tail))
    paths = [p for p in (doc.get("paths") or {}) if not p.startswith("/{")]
    first = sorted(paths, key=len)[0].strip("/") if paths else ""
    first_versioned = bool(re.fullmatch(r"v\d+", first.split("/", 1)[0])) if first else False
    if url_versioned and (first == tail or first.startswith(tail + "/")):
        url = url.rsplit("/", 1)[0]
    base_path = (doc.get("basePath") or "").strip("/")
    if (
        base_path
        and not url_versioned
        and not first_versioned
        and not url.endswith("/" + base_path)
        and f"/{base_path}/" not in url + "/"
    ):
        url = f"{url}/{base_path}"
    return url.rstrip("/")


def bases_of(
    slug: str, doc: dict[str, Any], docs_table: dict[str, dict[str, str]]
) -> dict[str, str]:
    """Region -> base URL. Env override wins, then the docs table, then curated/spec data."""
    override = os.environ.get(f"SELECTEL_BASE_{slug.upper().replace('-', '_')}")
    if override:
        return {"global": override.rstrip("/")}
    if slug in docs_table and docs_table[slug]:
        return {region: _fit_base_to_paths(url, doc) for region, url in docs_table[slug].items()}
    base = SELECTEL_BASE.get(slug)
    if base is None:
        url, base_path = document_base(doc)
        base = ((url or SELECTEL_API) + base_path).rstrip("/")
    return {"global": _fit_base_to_paths(base, doc)}


def pick_region(bases: dict[str, str]) -> str:
    if DEFAULT_REGION in bases:
        return DEFAULT_REGION
    for region in bases:
        if region.startswith("ru-"):
            return region
    return sorted(bases)[0]


def timeweb_operations() -> tuple[dict[str, Any], list[Operation]]:
    doc = load_json(TIMEWEB_SPEC)
    operations = build_operations(
        provider="timeweb",
        product="cloud",
        base_url="https://api.timeweb.cloud",
        auth="bearer",
        doc=doc,
    )
    for op in operations:
        op.kind = classify(op)
    meta = {
        "provider": "timeweb",
        "title": (doc.get("info") or {}).get("title") or "Timeweb Cloud",
        "operations": len(operations),
        "auth": "bearer",
        "base_url": "https://api.timeweb.cloud",
    }
    return meta, operations


def selectel_operations(
    docs_table: dict[str, dict[str, str]] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, list[Operation]]]:
    products: list[dict[str, Any]] = []
    by_product: dict[str, list[Operation]] = {}
    skipped: list[str] = []
    docs_table = docs_table if docs_table is not None else selectel_base_table()
    for slug in selectel_products():
        try:
            doc = load_json(SELECTEL_SPEC.format(slug=slug))
        except Exception:
            skipped.append(slug)
            continue
        if not isinstance(doc, dict) or not doc.get("paths"):
            skipped.append(slug)
            continue
        bases = bases_of(slug, doc, docs_table)
        base = bases[pick_region(bases)]
        auth = auth_of(doc)
        operations = build_operations(
            provider="selectel",
            product=slug,
            base_url=base or "",
            auth=auth,
            doc=doc,
            tool_prefix=slug.replace("-", "_"),
            per_op_security=True,
        )
        for op in operations:
            op.kind = classify(op)
        if not operations:
            skipped.append(slug)
            continue
        by_product[slug] = operations
        products.append(
            {
                "slug": slug,
                "title": (doc.get("info") or {}).get("title") or slug,
                "base_url": base,
                "base_urls": bases,
                "regional": len(bases) > 1 or "global" not in bases,
                "auth": auth,
                "operations": len(operations),
                "configured": True,
            }
        )
    if skipped:
        print(f"skipped (not a JSON OpenAPI document): {', '.join(skipped)}")
    return products, by_product


def sweb_documents() -> list[dict[str, Any]]:
    """apidoc.sweb.ru is a SPA that inlines one OpenRPC document per API object as JSON.parse("…")
    (double-encoded). Logic ported from sanchpet/sweb-go-sdk (MIT)."""
    manifest = json.loads(fetch(f"{SWEB_DOCS_URL}/asset-manifest.json"))
    files = manifest.get("files") or {}
    urls = sorted(
        {
            (SWEB_DOCS_URL + value if value.startswith("/") else value)
            for value in files.values()
            if value.endswith(".js")
        }
    )
    source = "\n".join(fetch(url).decode("utf-8", "replace") for url in urls)
    documents: list[dict[str, Any]] = []
    seen: set[str] = set()
    index = 0
    while (found := source.find(SWEB_NEEDLE, index)) >= 0:
        start = found + len(SWEB_NEEDLE)
        if start >= len(source) or source[start] != '"':
            index = start
            continue
        end = start + 1
        while end < len(source) and source[end] != '"':
            end += 2 if source[end] == "\\" else 1
        if end >= len(source):
            break
        literal, index = source[start : end + 1], end + 1
        try:
            document = json.loads(json.loads(literal))
        except ValueError:
            continue
        if not isinstance(document, dict) or not (
            document.get("openrpc") or document.get("methods")
        ):
            continue
        fingerprint = json.dumps(document, sort_keys=True)
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        documents.append(document)
    return documents


def _sweb_schema(document: dict[str, Any], schema: Any) -> dict[str, Any]:
    reference = (schema or {}).get("$ref", "") if isinstance(schema, dict) else ""
    if not reference.startswith("#/"):
        return schema if isinstance(schema, dict) else {}
    node: Any = document
    for part in reference[2:].split("/"):
        node = node.get(part) if isinstance(node, dict) else None
    return node if isinstance(node, dict) else {}


def sweb_operations() -> tuple[dict[str, Any], list[dict[str, Any]]]:
    from cloud_mcp.core.safety import classify_rpc  # noqa: E402

    overrides: dict[str, str] = {}
    override_file = SPECS / "sweb-overrides.json"
    if override_file.exists():
        overrides = json.loads(override_file.read_text(encoding="utf-8"))
    operations: list[dict[str, Any]] = []
    seen: set[str] = set()
    for document in sweb_documents():
        server = ((document.get("servers") or [{}])[0].get("url") or "").removeprefix(SWEB_API)
        path = "/" + server.strip("/")
        for method in document.get("methods") or []:
            name = str(method.get("name") or "")
            if not name:
                continue
            tool = f"{path.strip('/').replace('/', '_')}_{name}"
            if tool in seen:
                continue
            seen.add(tool)
            params: list[dict[str, Any]] = []
            for param in method.get("params") or []:
                if not isinstance(param, dict) or not param.get("name"):
                    continue
                entry: dict[str, Any] = {
                    "name": str(param["name"]),
                    "in": "rpc",
                    "required": bool(param.get("required")),
                    "schema": _sweb_schema(document, param.get("schema")),
                }
                if param.get("description"):
                    entry["description"] = str(param["description"])
                params.append(entry)
            description = str(method.get("description") or "")
            operations.append(
                {
                    "tool": tool,
                    "method": "post",
                    "path": path,
                    "rpc": name,
                    "summary": description.splitlines()[0] if description else name,
                    "kind": classify_rpc(path, name, overrides),
                    "params": params,
                }
            )
    operations.sort(key=lambda item: item["tool"])
    meta = {
        "provider": "sweb",
        "title": "SpaceWeb",
        "base_url": SWEB_API,
        "auth": "sweb",
        "operations": len(operations),
    }
    return meta, operations


def write_json(path: Path, payload: Any) -> bool:
    text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=False)
    if path.exists() and path.read_text(encoding="utf-8") == text:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text + "\n", encoding="utf-8")
    return True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="report drift instead of writing")
    args = parser.parse_args()

    changed: list[str] = []

    tw_meta, tw_operations = timeweb_operations()
    tw_snapshot = {**tw_meta, "operations_list": [op.as_dict() for op in tw_operations]}
    if args.check:
        existing = SPECS / "timeweb.json"
        current = json.loads(existing.read_text(encoding="utf-8")) if existing.exists() else {}
        if current.get("operations") != len(tw_operations):
            changed.append(f"timeweb: {current.get('operations')} -> {len(tw_operations)}")
    else:
        if write_json(SPECS / "timeweb.json", tw_snapshot):
            changed.append(f"timeweb: {len(tw_operations)} operations")

    products, by_product = selectel_operations()
    total = sum(len(ops) for ops in by_product.values())
    if args.check:
        existing = SPECS / "selectel-meta.json"
        current = json.loads(existing.read_text(encoding="utf-8")) if existing.exists() else {}
        if current.get("operations") != total:
            changed.append(f"selectel: {current.get('operations')} -> {total}")
    else:
        for slug, operations in by_product.items():
            payload = {
                "provider": "selectel",
                "product": slug,
                "operations_list": [op.as_dict() for op in operations],
            }
            write_json(SPECS / "selectel" / f"{slug}.json", payload)
        if write_json(
            SPECS / "selectel-meta.json",
            {
                "provider": "selectel",
                "title": "Selectel",
                "operations": total,
                "products": products,
            },
        ):
            changed.append(f"selectel: {len(products)} products, {total} operations")

    sweb_meta, sweb_ops = sweb_operations()
    if args.check:
        existing = SPECS / "sweb.json"
        current = json.loads(existing.read_text(encoding="utf-8")) if existing.exists() else {}
        if current.get("operations") != len(sweb_ops):
            changed.append(f"sweb: {current.get('operations')} -> {len(sweb_ops)}")
    else:
        if write_json(SPECS / "sweb.json", {**sweb_meta, "operations_list": sweb_ops}):
            changed.append(f"sweb: {len(sweb_ops)} operations")

    tilda_file = SPECS / "tilda.json"
    if tilda_file.exists():
        tilda_raw = json.loads(tilda_file.read_text(encoding="utf-8"))
        if tilda_raw.get("operations") != len(tilda_raw.get("operations_list") or []):
            changed.append("tilda: count mismatch in hand-written snapshot")
        print(f"tilda: {tilda_raw.get('operations')} operations (hand-maintained)")

    print(f"timeweb: {len(tw_operations)} operations")
    print(f"sweb: {len(sweb_ops)} operations")
    print(f"selectel: {len(products)} products, {total} operations")
    regional = [p["slug"] for p in products if p.get("regional")]
    if regional:
        print(
            f"regional products (SELECTEL_REGION, default {DEFAULT_REGION}): {', '.join(regional)}"
        )
    if args.check:
        print("changed: " + (", ".join(changed) if changed else "no"))
        return 1 if changed else 0
    print("changed: " + (", ".join(changed) if changed else "no"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

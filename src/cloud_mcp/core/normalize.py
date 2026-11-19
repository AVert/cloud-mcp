"""Normalise an OpenAPI 2.0 / 3.x document into a flat list of operations.

Both Timeweb (OpenAPI 3.0, one document) and Selectel (mostly Swagger 2.0, one document per
product) end up in the same snapshot format, so the rest of the code never branches per provider.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any

METHODS = ("get", "post", "put", "patch", "delete", "head", "options")
SKIP_METHODS = frozenset({"head", "options"})


def slug(text: str) -> str:
    out = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")
    return out or "root"


def _ref_name(ref: str) -> str:
    return ref.rsplit("/", 1)[-1]


def deref(doc: dict[str, Any], node: Any, seen: frozenset[str] = frozenset()) -> Any:
    """Inline ``$ref`` chains, keeping only the first occurrence of a name to bound the depth."""
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str):
            name = _ref_name(ref)
            if name in seen or len(seen) > 6:
                return {"type": "object", "title": name}
            target = resolve_ref(doc, ref)
            if target is None:
                return {"type": "object", "title": name}
            return deref(doc, target, seen | {name})
        return {key: deref(doc, value, seen) for key, value in node.items()}
    if isinstance(node, list):
        return [deref(doc, item, seen) for item in node]
    return node


def resolve_ref(doc: dict[str, Any], ref: str) -> Any:
    if not ref.startswith("#/"):
        return None
    node: Any = doc
    for part in ref[2:].split("/"):
        part = part.replace("~1", "/").replace("~0", "~")
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


@dataclass
class Param:
    name: str
    location: str
    required: bool = False
    schema: dict[str, Any] = field(default_factory=dict)
    description: str = ""

    def as_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"name": self.name, "in": self.location}
        if self.required:
            out["required"] = True
        if self.schema:
            out["schema"] = self.schema
        if self.description:
            out["description"] = self.description
        return out


def scheme_auth(schemes: dict[str, Any], name: str) -> str:
    """Selectel documents both scope and header per scheme; the prose description is the only
    signal that survives their own mistakes (secrets-manager names a scheme account-scoped while
    describing — and serving — project-scoped tokens)."""
    scheme = schemes.get(name) or {}
    description = str(scheme.get("description") or "").lower()
    header = str(scheme.get("name") or "").lower()
    if "project" in description:
        return "iam_project"
    if "account" in description:
        return "iam_account"
    if name == "iam_token_project_scoped":
        return "iam_project"
    if name == "iam_token_account_scoped":
        return "iam_account"
    if header == "x-token":
        return "static"
    if header == "x-auth-token":
        return "iam_account"
    return "iam_account"


def security_auth(doc: dict[str, Any], operation: dict[str, Any] | None = None) -> str:
    """Auth for one operation: its ``security`` wins over the product-wide definition, and inside
    an OR-list the account-scoped variant is preferred (mobile-farm keys accept both but live
    endpoints reject project tokens with reader-only roles)."""
    schemes = (
        doc.get("securityDefinitions") or (doc.get("components") or {}).get("securitySchemes") or {}
    )
    groups = (
        operation.get("security")
        if operation and operation.get("security")
        else doc.get("security") or []
    )
    names = [name for group in groups for name in group if name in schemes]
    if not names:
        names = list(schemes)
    for name in names:
        if scheme_auth(schemes, name) == "iam_account":
            return "iam_account"
    return scheme_auth(schemes, names[0]) if names else "iam_account"


@dataclass
class Operation:
    provider: str
    product: str
    base_url: str
    auth: str
    tool: str
    method: str
    path: str
    summary: str
    kind: str
    rpc: str = ""
    params: list[Param] = field(default_factory=list)
    body: dict[str, Any] | None = None
    deprecated: bool = False

    def as_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "tool": self.tool,
            "method": self.method,
            "path": self.path,
            "summary": self.summary,
            "kind": self.kind,
            "auth": self.auth,
            **({"rpc": self.rpc} if self.rpc else {}),
            "params": [p.as_dict() for p in self.params],
        }
        if self.body:
            out["body"] = self.body
        if self.deprecated:
            out["deprecated"] = True
        return out


def _summary(doc_operation: dict[str, Any]) -> str:
    for key in ("summary", "description", "operationId"):
        value = doc_operation.get(key)
        if isinstance(value, str):
            text = " ".join(value.split())
            if text:
                return text[:300]
    return ""


def _params(
    doc: dict[str, Any], path_item: dict[str, Any], operation: dict[str, Any]
) -> list[Param]:
    raw: list[dict[str, Any]] = []
    raw.extend(path_item.get("parameters") or [])
    raw.extend(operation.get("parameters") or [])
    out: list[Param] = []
    for item in raw:
        item = deref(doc, item)
        if not isinstance(item, dict) or not item.get("name"):
            continue
        location = item.get("in") or "query"
        if location == "body":
            continue
        schema = item.get("schema") or {
            key: item[key] for key in ("type", "enum", "default", "format") if key in item
        }
        out.append(
            Param(
                name=item["name"],
                location=location,
                required=bool(item.get("required")),
                schema=deref(doc, schema),
                description=" ".join((item.get("description") or "").split())[:200],
            )
        )
    return out


def _body(doc: dict[str, Any], operation: dict[str, Any]) -> dict[str, Any] | None:
    body = operation.get("requestBody")
    if isinstance(body, dict):
        body = deref(doc, body)
        content = body.get("content") or {}
        for mime in ("application/json", "application/x-www-form-urlencoded", "*/*"):
            if mime in content:
                return deref(doc, (content[mime] or {}).get("schema") or {})
        if content:
            first = next(iter(content.values())) or {}
            return deref(doc, first.get("schema") or {})
    for item in operation.get("parameters") or []:
        item = deref(doc, item)
        if isinstance(item, dict) and item.get("in") == "body":
            return deref(doc, item.get("schema") or {})
    return None


VERSION_SEGMENT = re.compile(r"^v\d+$")
DROP_SEGMENTS = frozenset({"api"})
MAX_TOOL_NAME = 64
ITEM_VERB = {"get": "get", "post": "create", "put": "put", "patch": "patch", "delete": "delete"}
OTHER_VERB = {"put": "put", "patch": "patch", "delete": "delete"}


def _parts(path: str) -> list[str]:
    return [
        part
        for part in path.split("/")
        if part and part.lower() not in DROP_SEGMENTS and not VERSION_SEGMENT.match(part)
    ]


def _verb(method: str, parts: list[str], item_tail: bool) -> str:
    if item_tail:
        return ITEM_VERB[method]
    if method == "get":
        return "list"
    if method == "post":
        return "create" if len(parts) == 1 else ""
    return OTHER_VERB[method]


def path_tool(path: str, method: str) -> str:
    parts = _parts(path)
    item_tail = bool(parts) and parts[-1].startswith("{")
    named = [part for part in parts if not part.startswith("{")]
    base = slug("_".join(named)) if named else "root"
    verb = _verb(method, parts, item_tail)
    name = f"{base}_{verb}" if verb else base
    if len(name) > MAX_TOOL_NAME:
        digest = hashlib.blake2b(name.encode(), digest_size=4).hexdigest()
        name = f"{name[: MAX_TOOL_NAME - 9]}_{digest}"
    return name


def build_operations(
    *,
    provider: str,
    product: str,
    base_url: str,
    auth: str,
    doc: dict[str, Any],
    tool_prefix: str = "",
    per_op_security: bool = False,
) -> list[Operation]:
    prefix = f"{slug(tool_prefix)}_" if tool_prefix else ""
    known_base = base_url.rstrip("/")
    operations: list[Operation] = []
    used: dict[str, int] = {}
    for path, path_item in sorted((doc.get("paths") or {}).items()):
        if not isinstance(path_item, dict):
            continue
        for method in METHODS:
            operation = path_item.get(method)
            if not isinstance(operation, dict) or method in SKIP_METHODS:
                continue
            name = prefix + path_tool(path, method)
            if not name.startswith(prefix):
                name = prefix + name
            count = used.get(name, 0) + 1
            used[name] = count
            if count > 1:
                name = f"{name}_{count}"
            body = _body(doc, operation)
            operations.append(
                Operation(
                    provider=provider,
                    product=product,
                    base_url=known_base,
                    auth=security_auth(doc, operation) if per_op_security else auth,
                    tool=name,
                    method=method,
                    path=path,
                    summary=_summary(operation),
                    kind="",
                    params=_params(doc, path_item, operation),
                    body=body,
                    deprecated=bool(operation.get("deprecated")),
                )
            )
    return operations


def document_base(doc: dict[str, Any]) -> tuple[str, str]:
    """Return (base_url, base_path) declared by the document itself."""
    servers = doc.get("servers") or []
    for server in servers:
        url = (server or {}).get("url") or ""
        if url.startswith("http"):
            return url.rstrip("/"), ""
    base_path = (doc.get("basePath") or "").rstrip("/")
    host = doc.get("host") or ""
    schemes = doc.get("schemes") or []
    if host and schemes:
        return f"{schemes[0]}://{host}", base_path
    return "", base_path


def fingerprint(operations: list[Operation]) -> str:
    payload = "\n".join(
        f"{op.method} {op.path} {op.tool}" for op in sorted(operations, key=lambda o: o.tool)
    )
    return hashlib.sha256(payload.encode()).hexdigest()[:16]

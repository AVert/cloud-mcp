"""Load OpenRPC snapshots from specs/ and turn methods into MCP tool definitions."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .safety import classify, load_overrides


@dataclass(frozen=True)
class Method:
    path: str  # "/vps/ip"
    name: str  # "addLocal"
    description: str
    kind: str  # read | write | destructive | paid
    params: tuple[dict[str, Any], ...] = field(default_factory=tuple)

    @property
    def tool_name(self) -> str:
        return f"{self.path.strip('/').replace('/', '_')}_{self.name}"

    @property
    def group(self) -> str:
        return self.path.strip("/").split("/")[0]

    def input_schema(self, with_confirm: bool) -> dict[str, Any]:
        props: dict[str, Any] = {}
        for p in self.params:
            props[p["name"]] = {**p["schema"], "description": p.get("description", "")}
        if with_confirm:
            props["confirm"] = {
                "type": "boolean",
                "description": "Must be true to execute this non-read operation.",
            }
        required = [p["name"] for p in self.params if p.get("required")]
        if with_confirm:
            required.append("confirm")
        return {"type": "object", "properties": props, "required": required, "additionalProperties": False}


def _resolve(node: Any, doc: dict[str, Any]) -> Any:
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str) and ref.startswith("#/"):
            target: Any = doc
            for part in ref[2:].split("/"):
                target = target[part]
            return _resolve(target, doc)
        return {k: _resolve(v, doc) for k, v in node.items()}
    if isinstance(node, list):
        return [_resolve(v, doc) for v in node]
    return node


def load_methods(specs_dir: Path, overrides_path: Path | None = None) -> list[Method]:
    """All unique (path, method) pairs; later duplicates in the snapshot are dropped."""
    overrides = load_overrides(overrides_path)
    seen: set[tuple[str, str]] = set()
    out: list[Method] = []
    files = sorted(specs_dir.glob("*.json"))
    if not files:
        raise FileNotFoundError(f"no OpenRPC specs in {specs_dir} (set SWEB_SPECS_DIR)")
    for f in files:
        doc = json.loads(f.read_text(encoding="utf-8"))
        path = doc["servers"][0]["url"].split("api.sweb.ru", 1)[1]
        for m in doc["methods"]:
            key = (path, m["name"])
            if key in seen:
                continue
            seen.add(key)
            params = tuple(
                {**p, "schema": _resolve(p.get("schema", {}), doc)} for p in m.get("params", [])
            )
            out.append(Method(path, m["name"], m.get("description", ""),
                              classify(path, m["name"], overrides), params))
    return out


def in_groups(m: Method, groups: frozenset[str]) -> bool:
    p = m.path.strip("/")
    return not groups or any(p == g or p.startswith(g + "/") for g in groups)

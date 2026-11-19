"""Load provider snapshots into one searchable registry: provider -> product -> operations."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .core.normalize import Operation, Param


def specs_dir() -> Path:
    override = os.environ.get("CLOUD_SPECS_DIR")
    if override:
        return Path(override).expanduser()
    package = Path(__file__).resolve().parent / "specs"
    if package.exists():
        return package
    return Path(__file__).resolve().parents[2] / "specs"


@dataclass
class Product:
    slug: str
    title: str
    base_url: str
    auth: str
    operations: list[Operation] = field(default_factory=list)


@dataclass
class Provider:
    name: str
    title: str
    products: dict[str, Product] = field(default_factory=dict)
    operations: list[Operation] = field(default_factory=list)

    @property
    def configured(self) -> bool:
        return any(product.base_url for product in self.products.values())

    def counts(self) -> dict[str, int]:
        return {slug: len(product.operations) for slug, product in self.products.items()}


def _operation(
    raw: dict[str, Any], provider: str, product: str, base_url: str, auth: str
) -> Operation:
    params = [
        Param(
            name=item.get("name", ""),
            location=item.get("in", "query"),
            required=bool(item.get("required")),
            schema=item.get("schema") or {},
            description=item.get("description", ""),
        )
        for item in raw.get("params") or []
        if item.get("name")
    ]
    return Operation(
        provider=provider,
        product=product,
        base_url=base_url,
        auth=str(raw.get("auth") or auth),
        tool=raw["tool"],
        method=raw["method"],
        path=raw["path"],
        summary=raw.get("summary", ""),
        kind=raw.get("kind", "write"),
        rpc=str(raw.get("rpc") or ""),
        params=params,
        body=raw.get("body") or None,
        deprecated=bool(raw.get("deprecated")),
    )


def product_base(product_meta: dict[str, Any]) -> str:
    """Base of a selectel product: env override, then the region from SELECTEL_REGION, then the
    sync-chosen default (SELECTEL_BASE in the meta)."""
    slug = product_meta["slug"]
    override = os.environ.get(f"SELECTEL_BASE_{slug.upper().replace('-', '_')}")
    if override:
        return override.rstrip("/")
    base_urls = product_meta.get("base_urls") or {}
    region = os.environ.get("SELECTEL_REGION") or ""
    if region and region in base_urls:
        return base_urls[region]
    default = product_meta.get("base_url") or ""
    if base_urls and default not in base_urls.values():
        for candidate in base_urls.values():
            if candidate:
                return candidate
    return default


def load(root: Path | None = None) -> dict[str, Provider]:
    """Every ``specs/<provider>.json`` is a single-product provider snapshot; selectel is the
    multi-product case and is driven by ``specs/selectel-meta.json``."""
    root = root or specs_dir()
    providers: dict[str, Provider] = {}
    for file in sorted(root.glob("*.json")):
        if file.name == "selectel-meta.json":
            continue
        raw = json.loads(file.read_text(encoding="utf-8"))
        name = raw.get("provider") or file.stem
        if not isinstance(raw.get("operations_list"), list):
            continue
        provider = Provider(name=name, title=raw.get("title") or name)
        product = Product(
            slug=raw.get("product") or name,
            title=raw.get("title") or name,
            base_url=(raw.get("base_url") or "").rstrip("/"),
            auth=raw.get("auth") or "bearer",
        )
        for item in raw.get("operations_list") or []:
            product.operations.append(
                _operation(item, name, product.slug, product.base_url, product.auth)
            )
        provider.products[product.slug] = product
        provider.operations = list(product.operations)
        providers[name] = provider

    selectel_meta = root / "selectel-meta.json"
    if selectel_meta.exists():
        meta = json.loads(selectel_meta.read_text(encoding="utf-8"))
        provider = Provider(name="selectel", title=meta.get("title") or "Selectel")
        for item in meta.get("products") or []:
            slug = item["slug"]
            file = root / "selectel" / f"{slug}.json"
            if not file.exists():
                continue
            operations_raw = (
                json.loads(file.read_text(encoding="utf-8")).get("operations_list") or []
            )
            base_url = product_base(item).rstrip("/")
            product = Product(
                slug=slug,
                title=item.get("title") or slug,
                base_url=base_url,
                auth=item.get("auth") or "iam_account",
            )
            for raw in operations_raw:
                product.operations.append(_operation(raw, "selectel", slug, base_url, product.auth))
            provider.products[slug] = product
            provider.operations.extend(product.operations)
        providers["selectel"] = provider
    return providers


def enabled(providers: dict[str, Provider], names: tuple[str, ...]) -> dict[str, Provider]:
    if not names:
        return providers
    return {name: provider for name, provider in providers.items() if name in names}

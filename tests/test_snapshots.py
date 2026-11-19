"""Naming, classification and base-URL resolution of the snapshots."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cloud_mcp import registry
from cloud_mcp.core.normalize import Operation, build_operations, path_tool
from cloud_mcp.core.safety import classify

SPECS = Path(__file__).resolve().parents[1] / "specs"


@pytest.mark.parametrize(
    "path,method,expected",
    [
        ("/api/v1/servers", "get", "servers_list"),
        ("/api/v1/servers", "post", "servers_create"),
        ("/api/v1/servers/{server_id}", "get", "servers_get"),
        ("/api/v1/servers/{server_id}/reboot", "post", "servers_reboot"),
        ("/api/v1/account/services/cost", "get", "account_services_cost_list"),
        ("/api/v1/add-domain/{fqdn}", "post", "add_domain_create"),
        ("/v2/clusters/{cluster_id}/kubeconfig", "get", "clusters_kubeconfig_list"),
    ],
)
def test_tool_naming(path, method, expected):
    assert path_tool(path, method) == expected


def test_timeweb_snapshot_matches_legacy_names():
    legacy = Path("/home/avert/ai-models/mcp/timeweb/specs/timeweb-cloud.json")
    if not legacy.exists():
        pytest.skip("legacy timeweb repo not present")
    doc = json.loads(legacy.read_text(encoding="utf-8"))
    legacy_ops = build_operations(
        provider="timeweb", product="cloud", base_url="", auth="bearer", doc=doc
    )
    snapshot = json.loads((SPECS / "timeweb.json").read_text(encoding="utf-8"))
    fresh = {(op.tool, op.method, op.path) for op in legacy_ops}
    stored = {(op["tool"], op["method"], op["path"]) for op in snapshot["operations_list"]}
    assert fresh == stored


def test_selectel_counts_and_prefix():
    providers = registry.load()
    selectel = providers["selectel"]
    assert len(selectel.operations) == sum(len(p.operations) for p in selectel.products.values())
    assert all(op.tool.startswith(op.product.replace("-", "_") + "_") for op in selectel.operations)


def test_classification_samples():
    def op(method: str, path: str, tool: str) -> Operation:
        return Operation(
            provider="x",
            product="y",
            base_url="",
            auth="bearer",
            tool=tool,
            method=method,
            path=path,
            summary="",
            kind="",
        )

    assert classify(op("get", "/api/v1/servers", "servers_list")) == "read"
    assert classify(op("delete", "/api/v1/servers/{id}", "servers_delete")) == "destructive"
    assert classify(op("post", "/api/v1/servers/{id}/reboot", "servers_reboot")) == "destructive"
    assert classify(op("post", "/api/v1/servers", "servers_create")) == "paid"
    assert classify(op("patch", "/api/v1/ssh-keys/{id}", "ssh_keys_patch")) == "write"


def test_selectel_products_have_base():
    meta = json.loads((SPECS / "selectel-meta.json").read_text(encoding="utf-8"))
    assert all(p["base_url"] for p in meta["products"])
    regional = {p["slug"] for p in meta["products"] if p.get("regional")}
    assert {
        "1c-cloud",
        "cloud-public-network",
        "managed-databases",
        "managed-kubernetes",
        "managed-kubernetes-legacy",
        "object-storage",
        "private-dns",
        "quota-management",
        "scheduled-backups",
    } <= regional


def test_tilda_snapshot_shape():
    raw = json.loads((SPECS / "tilda.json").read_text(encoding="utf-8"))
    assert raw["provider"] == "tilda"
    assert raw["auth"] == "tilda_keys"
    assert raw["operations"] == len(raw["operations_list"]) == 10
    assert all(op["kind"] == "read" for op in raw["operations_list"])

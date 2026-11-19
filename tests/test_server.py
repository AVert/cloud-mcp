"""Server behaviour with the network mocked (in-memory MCP sessions)."""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from dataclasses import replace

import httpx
import pytest
import respx
from mcp.shared.memory import create_connected_server_and_client_session

from cloud_mcp.config import Account, Settings
from cloud_mcp.server import build_server

BASE = "https://api.timeweb.cloud"


def json_of(result) -> dict:
    return json.loads(" ".join(getattr(block, "text", "") for block in result.content))


@pytest.fixture
def settings(tmp_path):
    return Settings(
        accounts_file=tmp_path / "accounts.json",
        cache_dir=tmp_path / "cache",
        readonly=False,
        allow_destructive=True,
        accounts={"timeweb": Account(provider="timeweb", token="T")},
    )


@asynccontextmanager
async def session_of(server):
    async with create_connected_server_and_client_session(server) as session:
        yield session


@respx.mock
async def test_call_timeweb_read(settings):
    route = respx.get(f"{BASE}/api/v1/servers").mock(
        return_value=httpx.Response(200, json={"servers": [{"id": 1}]})
    )
    async with session_of(build_server(settings)) as session:
        result = json_of(
            await session.call_tool(
                "cloud_call", {"provider": "timeweb", "tool": "servers_list", "limit": 10}
            )
        )
    assert result["status"] == 200
    assert result["body"] == {"servers": [{"id": 1}]}
    assert route.calls[0].request.headers["authorization"] == "Bearer T"


@respx.mock
async def test_write_gates(settings):
    paid = respx.post(f"{BASE}/api/v1/servers").mock(
        return_value=httpx.Response(201, json={"server": {"id": 2}})
    )
    write = respx.post(f"{BASE}/api/v1/ssh-keys").mock(
        return_value=httpx.Response(201, json={"ssh_key": {"id": 3}})
    )

    async with session_of(build_server(replace(settings, readonly=True))) as session:
        blocked = json_of(
            await session.call_tool("cloud_call", {"provider": "timeweb", "tool": "servers_create"})
        )
        assert blocked["error"]["code"] == "readonly"

    async with session_of(
        build_server(replace(settings, readonly=False, allow_destructive=False))
    ) as session:
        paid_gate = json_of(
            await session.call_tool(
                "cloud_call",
                {"provider": "timeweb", "tool": "servers_create", "confirm": True},
            )
        )
        assert paid_gate["error"]["code"] == "confirm"

        plain = json_of(
            await session.call_tool(
                "cloud_call", {"provider": "timeweb", "tool": "ssh_keys_create"}
            )
        )
        assert plain["error"]["code"] == "confirm"
        ok = json_of(
            await session.call_tool(
                "cloud_call",
                {
                    "provider": "timeweb",
                    "tool": "ssh_keys_create",
                    "confirm": True,
                    "body": {"name": "x", "public_key": "ssh-ed25519 AAA"},
                },
            )
        )
        assert ok["status"] == 201, ok
    assert not paid.called
    assert write.called


async def test_search_describe_and_errors(settings):
    async with session_of(build_server(settings)) as session:
        hits = json_of(
            await session.call_tool("cloud_search", {"query": "перезагрузить сервер", "top": 2})
        )
        assert hits["matched"] == 2
        assert hits["methods"][0]["tool"] == "servers_reboot"

        described = json_of(
            await session.call_tool(
                "cloud_describe", {"provider": "timeweb", "tool": "servers_reboot"}
            )
        )
        assert described["base_url"] == BASE
        assert "server_id" in described["required"]

        unknown_tool = json_of(
            await session.call_tool("cloud_describe", {"provider": "timeweb", "tool": "nope"})
        )
        assert unknown_tool["error"]["code"] == "args"

        unknown_provider = json_of(
            await session.call_tool("cloud_describe", {"provider": "yandex", "tool": "x"})
        )
        assert unknown_provider["error"]["code"] == "args"


async def test_providers_and_catalog(settings, tmp_path):
    async with session_of(build_server(settings)) as session:
        providers = json_of(await session.call_tool("cloud_providers", {}))["providers"]
        counts = {item["provider"]: item["operations"] for item in providers}
        assert counts == {"tilda": 10, "timeweb": 515, "selectel": 746, "sweb": 276}

        target = tmp_path / "catalog-timeweb.md"
        info = json_of(
            await session.call_tool("cloud_catalog", {"provider": "timeweb", "path": str(target)})
        )
        assert info["operations"] == 515
        assert "servers_reboot" in target.read_text(encoding="utf-8")


@respx.mock
async def test_lazy_credentials(settings, tmp_path, monkeypatch):
    accounts = tmp_path / "accounts.json"
    accounts.write_text(json.dumps({"timeweb": {"token": "LATE"}}), encoding="utf-8")
    monkeypatch.setenv("CLOUD_ACCOUNTS_FILE", str(accounts))
    respx.get(f"{BASE}/api/v1/servers/1").mock(
        return_value=httpx.Response(200, json={"server": {"id": 1}})
    )
    async with session_of(build_server(settings)) as session:
        result = json_of(
            await session.call_tool(
                "cloud_call", {"provider": "timeweb", "tool": "servers_get", "server_id": 1}
            )
        )
        assert result["status"] == 200


async def test_project_scope_headers(settings):
    from cloud_mcp.client import CloudClient
    from cloud_mcp.core.normalize import Operation

    project = replace(
        settings,
        accounts={
            "selectel": Account(
                provider="selectel", token="ACC", project_token="PRJ", project_id="pid"
            )
        },
    )
    client = CloudClient(project)
    account_op = Operation(
        provider="selectel",
        product="balance",
        base_url="https://api.selectel.ru",
        auth="iam_account",
        tool="x",
        method="get",
        path="/v3/balances",
        summary="",
        kind="read",
    )
    project_op = replace(account_op, auth="iam_project", product="cdn")
    assert await client._headers(account_op) == {"X-Auth-Token": "ACC"}
    assert await client._headers(project_op) == {
        "X-Auth-Token": "PRJ",
        "X-Project-Id": "pid",
    }


async def test_project_scope_without_credentials_explains(settings):
    from cloud_mcp.client import CloudClient, CloudError
    from cloud_mcp.core.normalize import Operation

    client = CloudClient(
        replace(settings, accounts={"selectel": Account(provider="selectel", token="ACC")})
    )
    op = Operation(
        provider="selectel",
        product="cdn",
        base_url="https://api.selectel.ru",
        auth="iam_project",
        tool="x",
        method="get",
        path="/certificate",
        summary="",
        kind="read",
    )
    with pytest.raises(CloudError) as error:
        await client._headers(op)
    assert "project-scoped" in error.value.message


async def test_accounts_file_reread_without_restart(settings, tmp_path, monkeypatch):
    accounts = tmp_path / "accounts.json"
    accounts.write_text(json.dumps({"timeweb": {"token": "T"}}), encoding="utf-8")
    monkeypatch.setenv("CLOUD_ACCOUNTS_FILE", str(accounts))
    server = build_server(
        replace(settings, accounts={"timeweb": Account(provider="timeweb", token="T")})
    )
    async with session_of(server) as session:
        first = json_of(await session.call_tool("cloud_providers", {}))["providers"]
        by_name = {item["provider"]: item for item in first}
        assert by_name["timeweb"]["credentials"] == "configured"
        assert by_name["selectel"]["credentials"] == "missing"

        accounts.write_text(
            json.dumps({"timeweb": {"token": "T"}, "selectel": {"token": "S"}}), encoding="utf-8"
        )
        import os

        stat = os.stat(accounts)
        os.utime(accounts, (stat.st_atime + 5, stat.st_mtime + 5))
        second = json_of(await session.call_tool("cloud_providers", {}))["providers"]
        selectel = next(item for item in second if item["provider"] == "selectel")
        assert selectel["credentials"] == "configured"
        assert selectel["credential_kinds"]["iam_account"] is True

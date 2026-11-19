"""SpaceWeb provider: JSON-RPC transport, token auth, re-login and snapshot invariants."""

from __future__ import annotations

import httpx
import pytest
import respx

from cloud_mcp import registry
from cloud_mcp.client import CloudClient, CloudError, split_args
from cloud_mcp.config import Account, Settings

BASE = "https://api.sweb.ru"


@pytest.fixture(scope="module")
def sweb_ops() -> dict:
    provider = registry.load()["sweb"]
    return {op.tool: op for op in provider.operations}


def settings() -> Settings:
    return Settings(
        accounts_file=__import__("pathlib").Path("/nonexistent/accounts.json"),
        accounts={"sweb": Account(provider="sweb", login="u", password="p")},
    )


@respx.mock
async def test_rpc_envelope_and_token(sweb_ops):
    token_route = respx.post(f"{BASE}/notAuthorized/").mock(
        return_value=httpx.Response(200, json={"jsonrpc": "2.0", "id": "1", "result": "TOK"})
    )
    call_route = respx.post(f"{BASE}/vps/ip").mock(
        return_value=httpx.Response(200, json={"jsonrpc": "2.0", "id": "2", "result": {"ok": True}})
    )
    result = await CloudClient(settings()).request(
        sweb_ops["vps_ip_addLocal"], {}, {}, {"billingId": 1}
    )
    assert result.body == {"ok": True}
    assert token_route.called
    request = call_route.calls[0].request
    assert request.headers["authorization"] == "Bearer TOK"
    body = __import__("json").loads(request.content)
    assert body["method"] == "addLocal"
    assert body["params"] == {"billingId": 1}
    assert body["jsonrpc"] == "2.0"


@respx.mock
async def test_rpc_relogin_on_session_expired(sweb_ops):
    respx.post(f"{BASE}/notAuthorized/").mock(
        side_effect=[
            httpx.Response(200, json={"result": "OLD"}),
            httpx.Response(200, json={"result": "NEW"}),
        ]
    )
    respx.post(f"{BASE}/vps").mock(
        side_effect=[
            httpx.Response(200, json={"error": {"code": -32603, "message": "session expired"}}),
            httpx.Response(200, json={"result": {"ok": True}}),
        ]
    )
    result = await CloudClient(settings()).request(sweb_ops["vps_index"], {}, {}, None)
    assert result.body == {"ok": True}


@respx.mock
async def test_rpc_error_mapping(sweb_ops):
    respx.post(f"{BASE}/notAuthorized/").mock(
        return_value=httpx.Response(200, json={"result": "TOK"})
    )
    respx.post(f"{BASE}/vps").mock(
        return_value=httpx.Response(200, json={"error": {"code": 10, "message": "no such vps"}})
    )
    with pytest.raises(CloudError) as error:
        await CloudClient(settings()).request(sweb_ops["vps_index"], {}, {}, None)
    assert error.value.code == "rpc" and "no such vps" in error.value.message


@respx.mock
async def test_extended_result_error(sweb_ops):
    respx.post(f"{BASE}/notAuthorized/").mock(
        return_value=httpx.Response(200, json={"result": "TOK"})
    )
    respx.post(f"{BASE}/vps").mock(
        return_value=httpx.Response(
            200, json={"result": {"extendedResult": {"code": 5, "message": "bad order"}}}
        )
    )
    with pytest.raises(CloudError) as error:
        await CloudClient(settings()).request(sweb_ops["vps_index"], {}, {}, None)
    assert "bad order" in error.value.message


def test_split_args_routes_everything_into_params(sweb_ops):
    op = sweb_ops["vps_ip_addLocal"]
    path, query, body = split_args(op, {"billingId": 7, "extra": "x"})
    assert path == {} and query == {}
    assert body == {"billingId": 7, "extra": "x"}


def test_snapshot_invariants(sweb_ops):
    assert len(sweb_ops) == 276
    assert sweb_ops["vps_ip_add"].kind == "paid"
    assert sweb_ops["vps_reboot"].kind == "destructive"
    assert sweb_ops["domains_index"].kind == "read"
    assert all(op.rpc and op.method == "post" and op.auth == "sweb" for op in sweb_ops.values())
    assert all(p.location == "rpc" for op in sweb_ops.values() for p in op.params)


def test_legacy_sweb_env_account(tmp_path, monkeypatch):
    legacy = tmp_path / "sweb.json"
    legacy.write_text(
        '{"work": {"login": "l1", "password": "p1"}, "home": "l2:p2"}', encoding="utf-8"
    )
    monkeypatch.setenv("SWEB_ACCOUNTS_FILE", str(legacy))
    monkeypatch.setenv("SWEB_ACCOUNT", "home")
    monkeypatch.setenv("CLOUD_ACCOUNTS_FILE", str(tmp_path / "missing.json"))
    for name in ("CLOUD_ACCOUNTS_FILE",):
        monkeypatch.delenv(name, raising=False)
    from cloud_mcp.config import load_accounts

    account = load_accounts(tmp_path / "missing.json")["sweb"]
    assert (account.login, account.password) == ("l2", "p2")
    assert set(account.sub_accounts) == {"work", "home"}

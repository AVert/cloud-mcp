import json

import httpx
import pytest
import respx
from mcp.shared.memory import create_connected_server_and_client_session as connect

from sweb_mcp.config import Account, Settings, _parse_accounts
from sweb_mcp.server import build_server

BASE = "https://api.sweb.ru"


def rpc(result=None, error=None):
    return httpx.Response(200, json={"jsonrpc": "2.0", "id": "1", **({"error": error} if error else {"result": result})})


def test_parse_accounts_forms():
    accs = _parse_accounts(json.dumps({"ours": {"login": "a", "password": "b"}, "client": "c:d"}))
    assert [(a.name, a.login, a.password) for a in accs] == [("ours", "a", "b"), ("client", "c", "d")]


def test_env_accounts_file(tmp_path, monkeypatch):
    f = tmp_path / "accounts.json"
    f.write_text(json.dumps({"ours": {"login": "a", "password": "b"}}), encoding="utf-8")
    monkeypatch.setenv("SWEB_ACCOUNTS_FILE", str(f))
    monkeypatch.delenv("SWEB_ACCOUNT", raising=False)
    s = Settings.from_env()
    assert s.default_account == "ours"
    assert s.account().login == "a"
    assert s.account("ours").password == "b"


def test_env_no_file(monkeypatch):
    monkeypatch.delenv("SWEB_ACCOUNTS_FILE", raising=False)
    monkeypatch.delenv("SWEB_ACCOUNT", raising=False)
    s = Settings.from_env()
    assert s.accounts == ()
    assert s.default_account == ""


def test_unknown_account():
    s = Settings(accounts=(Account("a", "u", "p"),), default_account="a")
    with pytest.raises(KeyError):
        s.account("nope")


@respx.mock
async def test_server_routes_by_account():
    def auth(request):
        return rpc("TOK-" + json.loads(request.content)["params"]["login"])

    respx.post(f"{BASE}/notAuthorized/").mock(side_effect=auth)
    vps = respx.post(f"{BASE}/vps").mock(return_value=rpc([]))
    s = Settings(accounts=(Account("a", "ua", "pa"), Account("b", "ub", "pb")),
                 default_account="a", min_interval=0)
    async with connect(build_server(s), raise_exceptions=False) as sess:
        names = {t.name for t in (await sess.list_tools()).tools}
        assert {"sweb_accounts", "sweb_use_account"} <= names

        r = await sess.call_tool("sweb_accounts", {})
        assert json.loads(r.content[0].text)["current"] == "a"

        r = await sess.call_tool("vps_index", {"account": "b"})
        assert not r.isError
        assert vps.calls[-1].request.headers["authorization"] == "Bearer TOK-ub"

        await sess.call_tool("sweb_use_account", {"name": "b"})
        r = await sess.call_tool("vps_index", {})
        assert not r.isError
        assert vps.calls[-1].request.headers["authorization"] == "Bearer TOK-ub"

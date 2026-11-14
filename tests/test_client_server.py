import json

import httpx
import pytest
import respx
from mcp.shared.memory import create_connected_server_and_client_session as connect

from sweb_mcp.client import SwebClient, SwebError
from sweb_mcp.config import Account, Settings
from sweb_mcp.server import build_server

BASE = "https://api.sweb.ru"


def rpc(result=None, error=None):
    return httpx.Response(
        200,
        json={"jsonrpc": "2.0", "id": "1", **({"error": error} if error else {"result": result})},
    )


@respx.mock
async def test_login_and_call(settings):
    auth = respx.post(f"{BASE}/notAuthorized/").mock(return_value=rpc("TOK"))
    call = respx.post(f"{BASE}/pay").mock(return_value=rpc({"balance": 5}))
    c = SwebClient(settings)
    assert await c.call("/pay", "index") == {"balance": 5}
    assert call.calls[0].request.headers["authorization"] == "Bearer TOK"
    assert json.loads(auth.calls[0].request.content)["params"] == {"login": "u", "password": "p"}


@respx.mock
async def test_relogin_on_session_expired(settings):
    respx.post(f"{BASE}/notAuthorized/").mock(side_effect=[rpc("T1"), rpc("T2")])
    call = respx.post(f"{BASE}/pay").mock(
        side_effect=[rpc(error={"code": -32603, "message": "expired"}), rpc(1)]
    )
    assert await SwebClient(settings).call("/pay", "index") == 1
    assert call.calls[1].request.headers["authorization"] == "Bearer T2"


@respx.mock
async def test_errors(settings):
    respx.post(f"{BASE}/notAuthorized/").mock(return_value=rpc("T"))
    respx.post(f"{BASE}/pay").mock(
        side_effect=[
            httpx.Response(500, text="boom"),
            rpc(error={"code": 5, "message": "bad"}),
            rpc({"extendedResult": {"code": 0, "message": "nope"}}),
        ]
    )
    c = SwebClient(settings)
    for code in (500, 5, "extendedResult"):
        with pytest.raises(SwebError) as e:
            await c.call("/pay", "index")
        assert e.value.code == code


async def test_missing_credentials():
    with pytest.raises(SwebError, match="login/password"):
        await SwebClient(Settings()).call("/pay", "index")


@respx.mock
async def test_server_end_to_end(settings):
    respx.post(f"{BASE}/notAuthorized/").mock(return_value=rpc("T"))
    vps = respx.post(f"{BASE}/vps").mock(return_value=rpc([{"billingId": "x"}]))
    async with connect(build_server(settings), raise_exceptions=False) as s:
        tools = (await s.list_tools()).tools
        assert len(tools) == 276 + 5
        names = {t.name for t in tools}
        assert {
            "vps_index",
            "vps_ip_addLocal",
            "sweb_call",
            "sweb_accounts",
            "sweb_use_account",
        } <= names

        r = await s.call_tool("vps_index", {})
        assert not r.isError and "billingId" in r.content[0].text

        r = await s.call_tool("vps_reboot", {"billingId": "x"})  # no confirm
        assert r.isError and "confirm" in r.content[0].text
        assert vps.call_count == 1

        r = await s.call_tool(
            "sweb_call",
            {"path": "/vps", "method": "reboot", "params": {"billingId": "x"}, "confirm": True},
        )
        assert not r.isError and vps.call_count == 2

        r = await s.call_tool("sweb_list_methods", {"kind": "paid", "group": "vps"})
        assert json.loads(r.content[0].text)["count"] > 0


@respx.mock
async def test_readonly_blocks(specs_dir):
    ro = Settings(
        accounts=(Account("default", "u", "p"),), default_account="default", specs_dir=specs_dir
    )
    async with connect(build_server(ro), raise_exceptions=False) as s:
        r = await s.call_tool("vps_rename", {"billingId": "x", "alias": "n", "confirm": True})
        assert r.isError and "SWEB_READONLY" in r.content[0].text


# --- rate limiting / retries -------------------------------------------------


def fast(**kw):
    return Settings(
        accounts=(Account("default", "u", "p"),),
        default_account="default",
        min_interval=0,
        backoff_base=0,
        **kw,
    )


@respx.mock
async def test_429_retried_even_for_writes():
    respx.post(f"{BASE}/notAuthorized/").mock(return_value=rpc("T"))
    call = respx.post(f"{BASE}/vps").mock(
        side_effect=[httpx.Response(429, headers={"Retry-After": "0"}), rpc(1)]
    )
    assert await SwebClient(fast()).call("/vps", "rename", {}, retry=False) == 1
    assert call.call_count == 2


@respx.mock
async def test_503_and_network_retried_only_for_reads():
    respx.post(f"{BASE}/notAuthorized/").mock(return_value=rpc("T"))
    call = respx.post(f"{BASE}/vps").mock(
        side_effect=[httpx.Response(503), httpx.ConnectError("x"), rpc([])]
    )
    assert await SwebClient(fast()).call("/vps", "index", {}, retry=True) == []
    assert call.call_count == 3
    call.reset()
    call.side_effect = [httpx.Response(503), rpc(1)]
    with pytest.raises(SwebError) as e:  # write: no retry, outcome unknown
        await SwebClient(fast()).call("/vps", "reboot", {}, retry=False)
    assert e.value.code == 503 and call.call_count == 1


@respx.mock
async def test_retries_exhausted():
    respx.post(f"{BASE}/notAuthorized/").mock(return_value=rpc("T"))
    call = respx.post(f"{BASE}/vps").mock(return_value=httpx.Response(429))
    with pytest.raises(SwebError) as e:
        await SwebClient(fast(max_retries=2)).call("/vps", "index", {}, retry=True)
    assert e.value.code == 429 and call.call_count == 3


@respx.mock
async def test_concurrency_cap():
    import asyncio

    respx.post(f"{BASE}/notAuthorized/").mock(return_value=rpc("T"))
    cur = peak = 0

    async def handler(request):
        nonlocal cur, peak
        cur += 1
        peak = max(peak, cur)
        await asyncio.sleep(0.02)
        cur -= 1
        return rpc(1)

    respx.post(f"{BASE}/vps").mock(side_effect=handler)
    c = SwebClient(fast(max_concurrency=2))
    await c.call("/vps", "index", {}, retry=True)  # login first
    await asyncio.gather(*(c.call("/vps", "index", {}, retry=True) for _ in range(8)))
    assert peak == 2


@respx.mock
async def test_min_interval_paces_requests():
    import time

    respx.post(f"{BASE}/notAuthorized/").mock(return_value=rpc("T"))
    respx.post(f"{BASE}/vps").mock(return_value=rpc(1))
    c = SwebClient(
        Settings(
            accounts=(Account("default", "u", "p"),),
            default_account="default",
            min_interval=0.05,
            backoff_base=0,
        )
    )
    t0 = time.monotonic()
    for _ in range(4):
        await c.call("/vps", "index", {})
    assert time.monotonic() - t0 >= 0.15  # 5 requests incl. login -> 4 gaps of 0.05

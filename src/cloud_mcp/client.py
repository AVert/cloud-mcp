"""HTTP client for every provider: auth injection, retries and error mapping.

Auth is per-operation (`op.auth`), because Selectel mixes IAM-account, IAM-project, static-token
APIs while Timeweb uses Bearer and Tilda passes its keys as query parameters.
"""

from __future__ import annotations

import asyncio
import itertools
import os
import time
from dataclasses import dataclass, replace
from urllib.parse import quote

import httpx

from .config import Account, Settings
from .core.normalize import Operation

IDENTITY_TOKEN_URL = "https://cloud.api.selcloud.ru/identity/v3/auth/tokens"
IAM_TTL = 60 * 55
SWEB_SESSION_EXPIRED = -32603


class CloudError(Exception):
    def __init__(self, code: str, message: str, status: int = 0):
        super().__init__(f"[{code}] {message}")
        self.code = code
        self.message = message
        self.status = status


@dataclass
class CallResult:
    status: int
    body: object
    url: str


def split_args(
    op: Operation, args: dict[str, object]
) -> tuple[dict[str, str], dict[str, object], dict[str, object] | None]:
    """Route flat arguments to path/query/header/body by the operation's parameter table."""
    path: dict[str, str] = {}
    query: dict[str, object] = {}
    headers: dict[str, object] = {}
    rpc_params: dict[str, object] = {}
    explicit_body = args.pop("body", None)
    if not isinstance(explicit_body, dict):
        explicit_body = None
    leftovers: dict[str, object] = {}
    known = {param.name for param in op.params}
    for key, value in args.items():
        if key in known:
            continue
        leftovers[key] = value
    for param in op.params:
        if param.name not in args:
            continue
        value = args[param.name]
        if param.location == "path":
            path[param.name] = str(value)
        elif param.location == "query":
            query[param.name] = value
        elif param.location == "header":
            headers[param.name] = value
        elif param.location == "rpc":
            rpc_params[param.name] = value
    if op.rpc:
        merged = {**rpc_params, **leftovers}
        if explicit_body:
            merged = {**merged, **explicit_body}
        return {}, {}, (merged or None)
    body = explicit_body
    if body is None and op.body and leftovers:
        body = leftovers
        leftovers = {}
    return path, {**query, **leftovers}, body


def render_url(op: Operation, path: dict[str, str]) -> str:
    url = op.path
    for param in op.params:
        if param.location != "path":
            continue
        value = path.get(param.name)
        if not value:
            raise CloudError("args", f"missing path parameter: {param.name}")
        url = url.replace("{" + param.name + "}", quote(str(value), safe=""))
    return op.base_url + url


class CloudClient:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._iam: dict[str, tuple[str, float]] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._sweb_tokens: dict[str, str] = {}
        self._ids = itertools.count(1)
        self._sweb_next = 0.0
        self._sweb_interval = float(os.environ.get("SWEB_MIN_INTERVAL") or 0.2)
        self._sweb_max = max(1, int(os.environ.get("SWEB_MAX_CONCURRENCY") or 4))
        self._sweb_sem: dict[str, asyncio.Semaphore] = {}

    def _account(self, provider: str, name: str = "") -> Account:
        account = self.settings.account(provider)
        if account.sub_accounts:
            wanted = name or account.default_account or sorted(account.sub_accounts)[0]
            sub = account.sub_accounts.get(wanted)
            if sub is None:
                known = ", ".join(sorted(account.sub_accounts)) or "none"
                raise CloudError("args", f"unknown account '{wanted}' (known: {known})")
            account = replace(
                account,
                login=sub.get("login", ""),
                password=sub.get("password", ""),
                token="",
            )
        elif name:
            raise CloudError("args", f"{provider} has no named accounts configured")
        if not account.usable:
            raise CloudError(
                "config",
                f"no credentials for provider '{provider}': put them into "
                f"{self.settings.accounts_file} ({account.as_env()})",
            )
        return account

    async def _iam_token(self, account: Account, scope: str = "account") -> str:
        """Mint or reuse an IAM token for the requested scope (KRaft Keystone password auth)."""
        if scope == "account" and account.token:
            return account.token
        if scope == "project" and account.project_token:
            return account.project_token
        key = f"{account.provider}:{account.login}:{scope}:{account.project_id}"
        cached = self._iam.get(key)
        if cached and cached[1] > time.time():
            return cached[0]
        lock = self._locks.setdefault(key, asyncio.Lock())
        async with lock:
            cached = self._iam.get(key)
            if cached and cached[1] > time.time():
                return cached[0]
            if not (account.login and account.password):
                if scope == "project":
                    raise CloudError(
                        "config",
                        "project-scoped selectel token required for this product: add "
                        "project_token + project_id, or login/password of a service user and "
                        "run scripts/selectel_auth.py --login … --project-id …",
                    )
                raise CloudError(
                    "config",
                    "selectel IAM token required: provide iam_token or login/password of a "
                    "service user (+account_id) in the accounts file",
                )
            domain = {"name": account.account_id or account.login}
            if scope == "project":
                if not account.project_id:
                    raise CloudError(
                        "config",
                        "project-scoped token needs project_id in the accounts file",
                    )
                target: dict[str, object] = {
                    "project": {"id": account.project_id, "domain": domain}
                }
            else:
                target = {"domain": domain}
            payload = {
                "auth": {
                    "identity": {
                        "methods": ["password"],
                        "password": {
                            "user": {
                                "name": account.login,
                                "domain": domain,
                                "password": account.password,
                            }
                        },
                    },
                    "scope": target,
                }
            }
            async with httpx.AsyncClient(trust_env=False, timeout=self.settings.timeout) as client:
                response = await client.post(IDENTITY_TOKEN_URL, json=payload)
            if response.status_code != 201:
                raise CloudError(
                    "auth",
                    f"selectel token request failed: {response.status_code} {response.text[:200]}",
                    response.status_code,
                )
            token = response.headers.get("X-Subject-Token") or ""
            if not token:
                raise CloudError("auth", "selectel token response has no X-Subject-Token")
            self._iam[key] = (token, time.time() + IAM_TTL)
            return token

    async def _sweb_token(self, account: Account, base_url: str) -> str:
        """SpaceWeb auth: Bearer token from getToken, reused until the session expires."""
        if account.token:
            return account.token
        key = f"sweb:{account.login}:{account.password}"
        cached = self._sweb_tokens.get(key)
        if cached:
            return cached
        lock = self._locks.setdefault(key, asyncio.Lock())
        async with lock:
            cached = self._sweb_tokens.get(key)
            if cached:
                return cached
            if not (account.login and account.password):
                raise CloudError(
                    "config",
                    "sweb needs login/password (or a token) in the accounts file",
                )
            envelope = {
                "jsonrpc": "2.0",
                "id": str(next(self._ids)),
                "method": "getToken",
                "params": {"login": account.login, "password": account.password},
            }
            async with httpx.AsyncClient(trust_env=False, timeout=self.settings.timeout) as client:
                response = await client.post(f"{base_url}/notAuthorized/", json=envelope)
            try:
                data = response.json()
            except ValueError as error:
                raise CloudError(
                    "auth",
                    f"sweb getToken: HTTP {response.status_code} {response.text[:200]}",
                    response.status_code,
                ) from error
            if not isinstance(data, dict) or not isinstance(data.get("result"), str):
                raise CloudError("auth", f"sweb getToken failed: {str(data)[:200]}")
            self._sweb_tokens[key] = data["result"]
            return data["result"]

    async def _sweb_pace(self, provider: str) -> None:
        if self._sweb_interval <= 0:
            return
        lock = self._locks.setdefault(f"pace:{provider}", asyncio.Lock())
        async with lock:
            now = time.monotonic()
            wait = self._sweb_next - now
            self._sweb_next = max(now, self._sweb_next) + self._sweb_interval
        if wait > 0:
            await asyncio.sleep(wait)

    async def _rpc(
        self, op: Operation, body: dict[str, object] | None, account_name: str = ""
    ) -> CallResult:
        account = self._account(op.provider, account_name)
        base = op.base_url.rstrip("/")
        token = await self._sweb_token(account, base)
        url = f"{base}{op.path}"
        envelope: dict[str, object] = {
            "jsonrpc": "2.0",
            "id": str(next(self._ids)),
            "method": op.rpc,
            "params": body or {},
        }
        key = f"sweb:{account.login}:{account.password}"
        reauthenticated = False
        semaphore = self._sweb_sem.setdefault(op.provider, asyncio.Semaphore(self._sweb_max))
        for attempt in range(3):
            await self._sweb_pace(op.provider)
            headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
            async with semaphore:
                async with httpx.AsyncClient(
                    trust_env=False, timeout=self.settings.timeout
                ) as client:
                    response = await client.post(url, json=envelope, headers=headers)
            if response.status_code == 429 and attempt < 2:
                await asyncio.sleep(2**attempt)
                continue
            if response.status_code >= 500 and op.kind == "read" and attempt < 2:
                await asyncio.sleep(2**attempt)
                continue
            try:
                data: object = response.json()
            except ValueError as error:
                raise CloudError(
                    "api",
                    f"HTTP {response.status_code}: {response.text[:300]}",
                    response.status_code,
                ) from error
            if response.status_code != 200:
                raise CloudError(
                    "api", f"HTTP {response.status_code}: {str(data)[:300]}", response.status_code
                )
            if not isinstance(data, dict):
                raise CloudError("rpc", f"unexpected payload: {str(data)[:300]}")
            error = data.get("error")
            if error:
                code = error.get("code") if isinstance(error, dict) else error
                if code == SWEB_SESSION_EXPIRED and not reauthenticated:
                    self._sweb_tokens.pop(key, None)
                    token = await self._sweb_token(account, base)
                    envelope["id"] = str(next(self._ids))
                    reauthenticated = True
                    continue
                message = error.get("message") if isinstance(error, dict) else error
                raise CloudError("rpc", f"{code}: {message}")
            result = data.get("result")
            extended = result.get("extendedResult") if isinstance(result, dict) else None
            if isinstance(extended, dict) and extended.get("code") not in (0, None):
                raise CloudError("rpc", str(extended.get("message") or extended))
            return CallResult(status=response.status_code, body=result, url=url)
        raise CloudError("retry", "sweb retries exhausted")

    async def _headers(self, op: Operation) -> dict[str, str]:
        account = self._account(op.provider)
        if op.auth == "bearer":
            return {"Authorization": f"Bearer {account.token or account.static_token}"}
        if op.auth == "static":
            if not (account.static_token or account.token):
                raise CloudError("config", f"static token required for {op.provider}/{op.product}")
            return {"X-Token": account.static_token or account.token}
        if op.auth == "iam_project":
            headers = {"X-Auth-Token": await self._iam_token(account, "project")}
            if account.project_id:
                headers["X-Project-Id"] = account.project_id
            return headers
        if op.auth == "iam_account":
            return {"X-Auth-Token": await self._iam_token(account, "account")}
        return {}

    async def _auth_query(self, op: Operation) -> dict[str, str]:
        if op.auth != "tilda_keys":
            return {}
        account = self._account(op.provider)
        if not (account.public_key and account.private_key):
            raise CloudError(
                "config",
                f"tilda needs public_key and private_key in {self.settings.accounts_file}",
            )
        return {"publickey": account.public_key, "privatekey": account.private_key}

    async def request(
        self,
        op: Operation,
        path: dict[str, str],
        query: dict[str, object],
        body: dict[str, object] | None,
        account_name: str = "",
    ) -> CallResult:
        if op.rpc:
            return await self._rpc(op, body, account_name)
        if not op.base_url:
            raise CloudError(
                "config",
                f"no base URL configured for {op.provider}/{op.product}: set it in "
                f"specs or SELECTEL_BASE_{op.product.upper().replace('-', '_')}",
            )
        url = render_url(op, path)
        params = {**query, **await self._auth_query(op)}
        headers = await self._headers(op)
        is_read = op.kind == "read"
        for attempt in range(3):
            async with httpx.AsyncClient(trust_env=False, timeout=self.settings.timeout) as client:
                response = await client.request(
                    op.method.upper(),
                    url,
                    params={k: v for k, v in params.items() if v is not None},
                    headers=headers,
                    json=body if body is not None and op.method != "get" else None,
                )
            if response.status_code == 429 and attempt < 2:
                await asyncio.sleep(2**attempt)
                continue
            if response.status_code >= 500 and is_read and attempt < 2:
                await asyncio.sleep(2**attempt)
                continue
            break
        try:
            payload: object = response.json()
        except ValueError:
            payload = response.text[:2000]
        if response.status_code >= 400:
            message = response.text[:300] if not isinstance(payload, dict) else str(payload)[:300]
            raise CloudError("api", f"HTTP {response.status_code}: {message}", response.status_code)
        return CallResult(status=response.status_code, body=payload, url=str(response.request.url))

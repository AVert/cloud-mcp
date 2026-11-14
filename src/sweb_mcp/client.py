"""Async JSON-RPC 2.0 client for api.sweb.ru (token auth, auto re-login)."""

from __future__ import annotations

import asyncio
import itertools
import time
from dataclasses import replace
from typing import Any

import httpx

from .config import Settings

SESSION_EXPIRED = -32603
RETRY_ALWAYS = {429}  # rejected before processing: safe even for writes
RETRY_READ_ONLY = {502, 503, 504}  # outcome unknown: only idempotent reads
MAX_WAIT = 30.0


class SwebError(Exception):
    def __init__(self, code: int | str, message: str):
        super().__init__(f"[{code}] {message}")
        self.code, self.message = code, message


class SwebClient:
    def __init__(self, settings: Settings, http: httpx.AsyncClient | None = None):
        if not settings.login and settings.accounts:
            acc = settings.account()
            settings = replace(settings, login=acc.login, password=acc.password)
        self._s = settings
        self._http = http or httpx.AsyncClient(timeout=settings.timeout, trust_env=False)
        self._token = ""
        self._lock = asyncio.Lock()
        self._ids = itertools.count(1)
        self._sem = asyncio.Semaphore(max(1, settings.max_concurrency))
        self._pace_lock = asyncio.Lock()
        self._next_slot = 0.0

    async def aclose(self) -> None:
        await self._http.aclose()

    async def _pace(self) -> None:
        async with self._pace_lock:
            now = time.monotonic()
            wait = self._next_slot - now
            self._next_slot = max(now, self._next_slot) + self._s.min_interval
        if wait > 0:
            await asyncio.sleep(wait)

    def _delay(self, attempt: int, resp: httpx.Response | None) -> float:
        ra = resp.headers.get("Retry-After", "") if resp is not None else ""
        if ra.isdigit():
            return min(float(ra), MAX_WAIT)
        return min(self._s.backoff_base * 2**attempt, MAX_WAIT)

    async def _post(
        self, path: str, method: str, params: dict[str, Any], auth: bool, retry: bool = False
    ) -> Any:
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if auth and self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        body = {"jsonrpc": "2.0", "id": str(next(self._ids)), "method": method, "params": params}
        for attempt in range(self._s.max_retries + 1):
            last = attempt == self._s.max_retries
            resp: httpx.Response | None = None
            async with self._sem:
                await self._pace()
                try:
                    resp = await self._http.post(self._s.api_url + path, json=body, headers=headers)
                except httpx.HTTPError as e:
                    if not (retry and not last):
                        raise SwebError("network", f"{type(e).__name__}: {e}") from e
            if resp is not None:
                codes = RETRY_ALWAYS | (RETRY_READ_ONLY if retry else set())
                if resp.status_code in codes and not last:
                    pass  # retry below
                else:
                    return self._parse(resp)
            await asyncio.sleep(self._delay(attempt, resp))
        raise SwebError("retry", "retries exhausted")  # unreachable

    @staticmethod
    def _parse(r: httpx.Response) -> Any:
        if r.status_code != 200:
            raise SwebError(r.status_code, f"HTTP {r.status_code}: {r.text[:300]}")
        try:
            data = r.json()
        except ValueError as e:
            raise SwebError("decode", f"invalid JSON: {r.text[:300]}") from e
        if err := data.get("error"):
            raise SwebError(err.get("code", "error"), str(err.get("message", err)))
        result = data.get("result")
        ext = result.get("extendedResult") if isinstance(result, dict) else None
        if isinstance(ext, dict) and ext.get("code") == 0:
            raise SwebError("extendedResult", str(ext.get("message") or ext))
        return result

    async def _login(self, stale: str) -> None:
        async with self._lock:
            if self._token != stale:  # someone refreshed meanwhile
                return
            if not (self._s.login and self._s.password):
                raise SwebError(
                    "config", "account has no login/password (check SWEB_ACCOUNTS_FILE)"
                )
            token = await self._post(
                "/notAuthorized/",
                "getToken",
                {"login": self._s.login, "password": self._s.password},
                auth=False,
            )
            if not isinstance(token, str) or not token:
                raise SwebError("auth", "getToken returned no token")
            self._token = token

    async def call(
        self, path: str, method: str, params: dict[str, Any] | None = None, retry: bool = False
    ) -> Any:
        params = params or {}
        if not self._token:
            await self._login("")
        used = self._token
        try:
            return await self._post(path, method, params, auth=True, retry=retry)
        except SwebError as e:
            if e.code != SESSION_EXPIRED:
                raise
        await self._login(used)
        return await self._post(path, method, params, auth=True, retry=retry)

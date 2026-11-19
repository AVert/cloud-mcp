#!/usr/bin/env python3
"""Prepare Selectel credentials for cloud-mcp: mint, verify and store them.

Turns "create a service user and paste the keys" into one local command — nothing sensitive goes
through chat or shell history:

    python scripts/selectel_auth.py --login svc-cloud --account-id 123456   # пароль спросим
    python scripts/selectel_auth.py --iam-token <panel-token>                # 24 ч, проверка
    python scripts/selectel_auth.py --project-token <tok> --project-id <id>  # проектный доступ
    python scripts/selectel_auth.py --static-token <api-key>                 # legacy X-Token
    python scripts/selectel_auth.py --check                                  # что работает сейчас

The file keeps every other provider: entries are merged, not replaced. ``--check`` reports each
credential against a real read endpoint, so a wrong key fails here, not in the middle of work.
"""

from __future__ import annotations

import argparse
import datetime
import getpass
import hashlib
import hmac
import json
import os
import stat
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

DEFAULT_ACCOUNTS = Path.home() / ".config" / "cloud-mcp" / "accounts.json"
IDENTITY_URL = "https://cloud.api.selcloud.ru/identity/v3/auth/tokens"
IAM_PROBE = "https://api.selectel.ru/v3/balances"
STATIC_PROBE = "https://api.selectel.ru/support/v2/tickets/count"
PROJECT_PROBE = "https://api.selectel.ru/cdn/v3/certificate"
S3_HOSTS = (
    "s3.ru-1.storage.selcloud.ru",
    "s3.ru-3.storage.selcloud.ru",
    "s3.ru-6.storage.selcloud.ru",
    "s3.ru-7.storage.selcloud.ru",
    "s3.gis-1.storage.selcloud.ru",
    "s3.kz-1.srvstorage.uz",
    "s3.uz-2.srvstorage.uz",
)
SELECTEL_TIMEOUT = 30


def request(
    url: str,
    method: str = "GET",
    body: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[int, dict[str, str], bytes]:
    payload = json.dumps(body).encode() if body is not None else None
    prepared = urllib.request.Request(
        url,
        data=payload,
        method=method,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "cloud-mcp auth",
            **(headers or {}),
        },
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(prepared, timeout=SELECTEL_TIMEOUT) as response:
            return response.status, dict(response.headers), response.read()
    except urllib.error.HTTPError as error:
        return error.code, dict(error.headers), error.read()


def mint_iam_token(
    login: str, password: str, account_id: str, project_id: str = ""
) -> tuple[str | None, str]:
    domain = {"name": account_id}
    scope: dict[str, Any] = (
        {"project": {"id": project_id, "domain": domain}} if project_id else {"domain": domain}
    )
    body = {
        "auth": {
            "identity": {
                "methods": ["password"],
                "password": {"user": {"name": login, "domain": domain, "password": password}},
            },
            "scope": scope,
        }
    }
    status, headers, payload = request(IDENTITY_URL, "POST", body)
    if status != 201:
        reason = "неверный логин/пароль/аккаунт" if status in (401, 403) else payload[:200]
        return None, f"итог {status}: {reason}"
    token = headers.get("X-Subject-Token") or headers.get("x-subject-token") or ""
    if not token:
        return None, "в ответе нет X-Subject-Token"
    return token, "ok"


def _detail(payload: bytes, status: int) -> str:
    text = payload[:160].decode("utf-8", "replace").strip()
    if text.startswith("<"):
        return f"{status} (неверный или истёкший токен)"
    return f"{status}: {text}"


def probe_iam(token: str) -> tuple[bool, str]:
    status, _, payload = request(IAM_PROBE, headers={"X-Auth-Token": token})
    if status == 200:
        try:
            balances = json.loads(payload)
        except json.JSONDecodeError:
            balances = {}
        return True, f"200, балансов: {len(balances.get('balances') or balances or [])}"
    return False, _detail(payload, status)


def probe_project(token: str, project_id: str) -> tuple[bool, str]:
    status, _, payload = request(
        PROJECT_PROBE, headers={"X-Auth-Token": token, "X-Project-Id": project_id}
    )
    if status == 200:
        return True, "200"
    return False, _detail(payload, status)


def probe_static(token: str) -> tuple[bool, str]:
    status, _, payload = request(STATIC_PROBE, headers={"X-Token": token})
    if status == 200:
        return True, f"200, {payload[:80].decode('utf-8', 'replace')}"
    return False, _detail(payload, status)


def s3_headers(
    access: str, secret: str, host: str, region: str, now: datetime.datetime | None = None
) -> dict[str, str]:
    """AWS SigV4 for a GET on / (ListBuckets): Selectel S3 accepts UNSIGNED-PAYLOAD."""
    moment = now or datetime.datetime.now(datetime.UTC)
    amz_date = moment.strftime("%Y%m%dT%H%M%SZ")
    date_stamp = moment.strftime("%Y%m%d")
    canonical = f"GET\n/\n\nhost:{host}\nx-amz-date:{amz_date}\nhost;x-amz-date\nUNSIGNED-PAYLOAD"
    scope = f"{date_stamp}/{region}/s3/aws4_request"
    to_sign = (
        f"AWS4-HMAC-SHA256\n{amz_date}\n{scope}\n{hashlib.sha256(canonical.encode()).hexdigest()}"
    )
    key = _sigv4_key(secret, date_stamp, region)
    signature = hmac.new(key, to_sign.encode(), hashlib.sha256).hexdigest()
    return {
        "Authorization": (
            f"AWS4-HMAC-SHA256 Credential={access}/{scope}, "
            "SignedHeaders=host;x-amz-date, "
            f"Signature={signature}"
        ),
        "x-amz-date": amz_date,
        "x-amz-content-sha256": "UNSIGNED-PAYLOAD",
    }


def _sigv4_key(secret: str, date_stamp: str, region: str) -> bytes:
    key = hmac.new(f"AWS4{secret}".encode(), date_stamp.encode(), hashlib.sha256).digest()
    key = hmac.new(key, region.encode(), hashlib.sha256).digest()
    key = hmac.new(key, b"s3", hashlib.sha256).digest()
    return hmac.new(key, b"aws4_request", hashlib.sha256).digest()


def probe_s3(access: str, secret: str, host: str, region: str | None = None) -> tuple[bool, str]:
    region = region or host.split(".")[1]
    try:
        status, _, payload = request(
            f"https://{host}/", headers=s3_headers(access, secret, host, region)
        )
    except (urllib.error.URLError, OSError) as error:
        reason = getattr(error, "reason", error)
        return False, f"{host}: {reason}"
    text = payload[:120].decode("utf-8", "replace").replace("\n", " ")
    if status == 200:
        return True, f"200 ListBuckets, host {host}"
    return False, f"{status} {text}"


def probe_s3_anywhere(access: str, secret: str, preferred: str = "") -> tuple[bool, str, str]:
    hosts = (preferred,) if preferred else S3_HOSTS
    for host in hosts:
        good, detail = probe_s3(access, secret, host)
        if good:
            return True, detail, host
    return False, detail, ""


def probe_s3_ftp(
    access: str, secret: str, host: str = "ftp.ru-1.storage.selcloud.ru"
) -> tuple[bool, str]:
    """The EC2 key pair doubles as FTP credentials, so a failed S3-API lookup can still be
    verified against the FTP gateway (pools ru-1 and ru-7)."""
    from ftplib import FTP_TLS

    try:
        ftp = FTP_TLS()
        ftp.connect(host, 21, timeout=25)
        ftp.auth()
        ftp.login(access, secret)
        ftp.quit()
    except OSError as error:
        return False, f"{host}: {error}"
    except Exception as error:
        return False, f"{host}: {str(error)[:120]}"
    return True, f"FTP-логин ок, {host}"


def probe_s3_pair(access: str, secret: str, preferred: str = "") -> tuple[bool, str, str]:
    """SigV4 sweep first; if no S3 gateway knows the key yet, fall back to FTP login."""
    good, detail, host = probe_s3_anywhere(access, secret, preferred)
    if good:
        return True, detail, host
    good, ftp_detail = probe_s3_ftp(access, secret)
    if good:
        return True, f"S3 API ещё не знает ключ ({detail[:60]}); {ftp_detail}", ""
    return False, detail, ""


def merge_accounts(path: Path, entry: dict[str, str], drop: tuple[str, ...] = ()) -> dict[str, Any]:
    current: dict[str, Any] = {}
    if path.exists():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                current = loaded
        except json.JSONDecodeError:
            current = {}
    existing = current.get("selectel")
    if isinstance(existing, str):
        existing = {"token": existing}
    merged = {**(existing or {}), **{k: v for k, v in entry.items() if v or k not in entry}}
    merged = {key: value for key, value in merged.items() if value and key not in drop}
    current["selectel"] = merged
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(current, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    return current


def check(path: Path) -> int:
    if not path.exists():
        print(f"нет файла учёток: {path}")
        return 1
    try:
        entry = json.loads(path.read_text(encoding="utf-8")).get("selectel") or {}
    except json.JSONDecodeError as error:
        print(f"файл {path} не читается как JSON: {error}")
        return 1
    if isinstance(entry, str):
        entry = {"token": entry}
    ok = True
    if entry.get("token"):
        good, detail = probe_iam(entry["token"])
        ok &= good
        print(f"IAM-токен: {'ок' if good else 'ошибка'} — {detail}")
    elif entry.get("login") and entry.get("password") and entry.get("account_id"):
        token, detail = mint_iam_token(entry["login"], entry["password"], entry["account_id"])
        if not token:
            print(f"IAM: сервисный пользователь {entry['login']} — Keystone: {detail}")
            ok = False
        else:
            good, probe = probe_iam(token)
            ok &= good
            print(
                f"IAM: сервисный пользователь {entry['login']} — "
                f"{'ок' if good else 'ошибка'}, {probe}"
            )
    elif entry.get("login"):
        print(f"IAM: сервисный пользователь {entry['login']} — нет password/account_id")
        ok = False
    else:
        print("IAM: не настроен (ни token, ни login/password)")
        ok = False
    if entry.get("project_token"):
        good, detail = probe_project(entry["project_token"], entry.get("project_id") or "")
        ok &= good
        print(f"project-токен: {'ок' if good else 'ошибка'} — {detail}")
    elif (
        entry.get("login")
        and entry.get("password")
        and entry.get("account_id")
        and entry.get("project_id")
    ):
        token, detail = mint_iam_token(
            entry["login"], entry["password"], entry["account_id"], entry["project_id"]
        )
        if token:
            good, probe = probe_project(token, entry["project_id"])
            ok &= good
            print(f"project-токен (mint): {'ок' if good else 'ошибка'} — {probe}")
        else:
            print(f"project-токен (mint): Keystone {detail}")
            ok = False
    else:
        print("project-токен: не настроен (CDN, DNS, MKS, MDB, приватный DNS, бэкапы)")
    if entry.get("static_token"):
        good, detail = probe_static(entry["static_token"])
        ok &= good
        print(f"static-токен: {'ок' if good else 'ошибка'} — {detail}")
    else:
        print("static-токен: не настроен (legacy: тикеты, биллинг)")
    if entry.get("s3_access_key") and entry.get("s3_secret_key"):
        good, detail, host = probe_s3_pair(
            entry["s3_access_key"], entry["s3_secret_key"], entry.get("s3_host") or ""
        )
        ok &= good
        print(f"s3-ключи: {'ок' if good else 'ошибка'} — {detail}")
    else:
        print("s3-ключи: не настроены (объектное хранилище, SigV4)")
    return 0 if ok else 1


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--accounts-file", default=str(DEFAULT_ACCOUNTS))
    parser.add_argument("--login", help="сервисный пользователь Selectel")
    parser.add_argument("--account-id", help="номер аккаунта (правый верхний угол панели)")
    parser.add_argument(
        "--password", help="пароль сервисного пользователя (лучше не указывать — спросим)"
    )
    parser.add_argument("--iam-token", help="готовый IAM-токен (24 ч, для быстрой проверки)")
    parser.add_argument("--project-id", help="id проекта (нужен для X-Project-Id)")
    parser.add_argument(
        "--project-token", help="готовый project-scoped IAM-токен (24 ч, быстрая проверка)"
    )
    parser.add_argument("--static-token", help="API-ключ для legacy-продуктов (X-Token)")
    parser.add_argument("--s3-access-key", help="Access key объектного хранилища (SigV4)")
    parser.add_argument("--s3-secret-key", help="Secret key объектного хранилища")
    parser.add_argument("--s3-host", help="конкретный S3-эндпоинт (иначе перебираем регионы)")
    parser.add_argument("--mf-proxy-key", help="Proxy-ключ мобильной фермы (на память)")
    parser.add_argument("--check", action="store_true", help="проверить, что уже сохранено")
    args = parser.parse_args()
    path = Path(args.accounts_file).expanduser()

    if args.check:
        return check(path)

    entry: dict[str, str] = {}
    if args.iam_token:
        good, detail = probe_iam(args.iam_token)
        print(f"IAM-токен: {'ок' if good else 'ошибка'} — {detail}")
        if not good:
            return 2
        entry["token"] = args.iam_token
    elif args.login or args.account_id:
        if not (args.login and args.account_id):
            parser.error("нужны оба: --login и --account-id")
        password = (
            args.password
            or os.environ.get("SELECTEL_SERVICE_PASSWORD")
            or getpass.getpass(f"пароль сервисного пользователя {args.login}: ")
        )
        token, detail = mint_iam_token(args.login, password, args.account_id, args.project_id or "")
        print(f"Keystone: {detail}")
        if not token:
            return 2
        if args.project_id:
            good, probe = probe_project(token, args.project_id)
            print(f"project-токен: {'ок' if good else 'ошибка'} — {probe}")
            if not good:
                return 2
            entry.update(
                login=args.login,
                password=password,
                account_id=args.account_id,
                project_id=args.project_id,
                project_token=token,
            )
        else:
            good, probe = probe_iam(token)
            print(f"IAM-токен: {'ок' if good else 'ошибка'} — {probe}")
            if not good:
                return 2
            entry.update(login=args.login, password=password, account_id=args.account_id)

    if args.project_token:
        if not args.project_id:
            parser.error("для --project-token нужен --project-id (идёт в заголовок X-Project-Id)")
        good, detail = probe_project(args.project_token, args.project_id)
        print(f"project-токен: {'ок' if good else 'ошибка'} — {detail}")
        if not good:
            return 2
        entry.update(project_token=args.project_token, project_id=args.project_id)

    if args.static_token:
        good, detail = probe_static(args.static_token)
        print(f"static-токен: {'ок' if good else 'ошибка'} — {detail}")
        if not good:
            return 2
        entry["static_token"] = args.static_token

    if args.s3_access_key or args.s3_secret_key:
        if not (args.s3_access_key and args.s3_secret_key):
            parser.error("нужны оба: --s3-access-key и --s3-secret-key")
        good, detail, host = probe_s3_pair(
            args.s3_access_key, args.s3_secret_key, args.s3_host or ""
        )
        print(f"s3-ключи: {'ок' if good else 'ошибка'} — {detail}")
        if not good:
            return 2
        entry["s3_access_key"] = args.s3_access_key
        entry["s3_secret_key"] = args.s3_secret_key
        if host:
            entry["s3_host"] = host

    if args.mf_proxy_key:
        entry["mf_proxy_key"] = args.mf_proxy_key
        print("proxy-ключ мобильной фермы сохранён (проверка — GET /api/v3/keys/proxy)")

    if not entry:
        parser.error("нечего сохранять: укажи --login/--account-id, --iam-token или --static-token")

    data = merge_accounts(path, entry)
    print(f"сохранено в {path} (0600), провайдеры в файле: {', '.join(sorted(data))}")
    print("проверка: python scripts/selectel_auth.py --check")
    return 0


if __name__ == "__main__":
    sys.exit(main())

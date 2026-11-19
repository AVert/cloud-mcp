#!/usr/bin/env python3
"""Create and maintain the Selectel service user that cloud-mcp authenticates as.

One command instead of clicking through IAM → Сервисные пользователи:

    python scripts/selectel_service_user.py --account-id 123456
    python scripts/selectel_service_user.py --account-id 123456 --write     # member, не reader
    python scripts/selectel_service_user.py --account-id 123456 --s3        # + access key для S3
    python scripts/selectel_service_user.py --list
    python scripts/selectel_service_user.py --delete svc-cloud-mcp --yes

Default is least privilege: ``reader`` на аккаунте (все проекты, квоты, биллинг) плюс ``reader``
на проекте (продуктам, которые проверяют права внутри проекта). Пароль генерируется локально,
нигде не печатается и попадает в файл учёток с правами 0600. После успешной проверки панельные
токены (24 ч) из файла убираются — иначе клиент продолжал бы ходить ими до истечения.
"""

from __future__ import annotations

import argparse
import json
import secrets
import string
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from selectel_auth import (  # noqa: E402
    DEFAULT_ACCOUNTS,
    check,
    merge_accounts,
    mint_iam_token,
    probe_iam,
    probe_project,
    request,
)

IAM_URL = "https://api.selectel.ru/iam/v1"
DEFAULT_NAME = "svc-cloud-mcp"
READ_ROLE = "reader"
WRITE_ROLE = "member"


def generate_password(length: int = 32) -> str:
    """Build the password Selectel accepts: upper, lower, digit and a symbol.

    Anything weaker comes back as ``insecure_password``.
    """
    alphabet = string.ascii_letters + string.digits + "!@#%^&*()-_=+"
    while True:
        candidate = "".join(secrets.choice(alphabet) for _ in range(length))
        if (
            any(char.islower() for char in candidate)
            and any(char.isupper() for char in candidate)
            and any(char.isdigit() for char in candidate)
            and any(char in "!@#%^&*()-_=+" for char in candidate)
        ):
            return candidate


def roles_payload(write: bool, project_id: str = "") -> list[dict[str, str]]:
    if write:
        return [{"role_name": WRITE_ROLE, "scope": "account"}]
    roles = [{"role_name": READ_ROLE, "scope": "account"}]
    if project_id:
        roles.append({"role_name": READ_ROLE, "scope": "project", "project_id": project_id})
    return roles


def iam(token: str, method: str, path: str, body: dict[str, Any] | None = None) -> tuple[int, Any]:
    status, _, payload = request(f"{IAM_URL}{path}", method, body, {"X-Auth-Token": token})
    try:
        data = json.loads(payload) if payload else {}
    except json.JSONDecodeError:
        data = {"raw": payload[:300].decode("utf-8", "replace")}
    return status, data


def account_domain(token: str) -> str:
    status, data = iam(token, "GET", "/projects")
    if status != 200:
        raise RuntimeError(f"определение номера аккаунта: {status} {data}")
    for project in data.get("projects") or []:
        domain = str(project.get("domain_name") or "")
        if domain:
            return domain
    return ""


def service_users(token: str) -> list[dict[str, Any]]:
    status, data = iam(token, "GET", "/service_users?limit=200")
    if status == 403:
        raise RuntimeError(
            "нужен админский токен: у сервисного пользователя только reader. "
            "Передай панельный IAM-токен через --token"
        )
    if status != 200:
        raise RuntimeError(f"список сервисных пользователей: {status} {data}")
    items = data.get("items") or data.get("service_users") or []
    return [item for item in items if isinstance(item, dict)]


def find_user(users: list[dict[str, Any]], name: str) -> dict[str, Any] | None:
    return next((user for user in users if user.get("name") == name), None)


def user_id(payload: dict[str, Any]) -> str:
    nested = payload.get("service_user") or {}
    return str(payload.get("id") or nested.get("id") or "")


def describe(user: dict[str, Any]) -> str:
    roles = user.get("roles") or []
    rendered = ", ".join(
        f"{role.get('role_name')}@{role.get('scope')}"
        + (f":{role.get('project_id')[:8]}" if role.get("project_id") else "")
        for role in roles
        if isinstance(role, dict)
    )
    return f"{user.get('name')} [{user.get('id')}] {rendered or 'без ролей'}"


def create_user(
    token: str, name: str, password: str, roles: list[dict[str, str]]
) -> tuple[str, dict[str, Any]]:
    status, data = iam(
        token,
        "POST",
        "/service_users",
        {
            "name": name,
            "description": "cloud-mcp automation (scripts/selectel_service_user.py)",
            "password": password,
            "enabled": True,
            "roles": roles,
        },
    )
    if status not in (200, 201):
        raise RuntimeError(f"создание сервисного пользователя: {status} {data}")
    found = user_id(data)
    if not found:
        users = service_users(token)
        existing = find_user(users, name)
        found = user_id(existing or {})
    if not found:
        raise RuntimeError(f"пользователь создан, но id не найден: {data}")
    return found, data


def set_roles(token: str, uid: str, roles: list[dict[str, str]]) -> None:
    status, data = iam(token, "PUT", f"/service_users/{uid}/roles", {"roles": roles})
    if status not in (200, 204):
        raise RuntimeError(f"назначение ролей: {status} {data}")


def rotate_password(token: str, uid: str, password: str) -> None:
    status, data = iam(token, "PATCH", f"/service_users/{uid}", {"password": password})
    if status not in (200, 204):
        raise RuntimeError(f"смена пароля: {status} {data}")


def make_credentials(token: str, uid: str, name: str, project_id: str) -> dict[str, str]:
    status, data = iam(
        token, "POST", f"/service_users/{uid}/credentials", {"name": name, "project_id": project_id}
    )
    if status not in (200, 201):
        raise RuntimeError(f"выпуск access key: {status} {data}")
    nested = data.get("credentials") or data
    access = str(nested.get("access_key") or nested.get("key") or "")
    secret = str(nested.get("secret_key") or nested.get("secret") or "")
    if not (access and secret):
        raise RuntimeError(f"выпущен ключ, но поля не разобраны: {sorted(data)}")
    return {"s3_access_key": access, "s3_secret_key": secret}


def read_entry(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    try:
        entry = json.loads(path.read_text(encoding="utf-8")).get("selectel") or {}
    except json.JSONDecodeError:
        return {}
    if isinstance(entry, str):
        return {"token": entry}
    return {key: str(value) for key, value in entry.items() if isinstance(value, (str, int))}


def admin_token(entry: dict[str, str], override: str) -> tuple[str, str]:
    if override:
        return override, "--token"
    if entry.get("token"):
        return entry["token"], "IAM-токен из файла учёток"
    if entry.get("login") and entry.get("password") and entry.get("account_id"):
        minted, detail = mint_iam_token(entry["login"], entry["password"], entry["account_id"])
        if minted:
            return minted, f"mint {entry['login']}"
        raise RuntimeError(f"Keystone для {entry['login']}: {detail}")
    raise RuntimeError("нужен админский доступ: положи iam-токен в файл учёток или передай --token")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--accounts-file", default=str(DEFAULT_ACCOUNTS))
    parser.add_argument("--token", default="", help="админский IAM-токен (иначе берём из файла)")
    parser.add_argument("--name", default=DEFAULT_NAME, help="имя сервисного пользователя")
    parser.add_argument("--account-id", default="", help="номер аккаунта (домен Keystone)")
    parser.add_argument("--project-id", default="", help="id проекта для project-scope роли")
    parser.add_argument("--write", action="store_true", help="member вместо reader")
    parser.add_argument("--s3", action="store_true", help="выпустить access key/secret для S3")
    parser.add_argument(
        "--keep-panel-tokens", action="store_true", help="не убирать токены из файла"
    )
    parser.add_argument("--list", action="store_true", help="показать сервисных пользователей")
    parser.add_argument("--delete", default="", metavar="NAME", help="удалить пользователя")
    parser.add_argument("--yes", action="store_true", help="подтвердить удаление")
    parser.add_argument("--check", action="store_true", help="проверить, что сохранено")
    args = parser.parse_args()
    path = Path(args.accounts_file).expanduser()

    if args.check:
        return check(path)

    entry = read_entry(path)
    try:
        token, source = admin_token(entry, args.token)
        print(f"admin: {source}")

        if args.list:
            users = service_users(token)
            print(f"сервисных пользователей: {len(users)}")
            for user in users:
                print(" ", describe(user))
            return 0

        if args.delete:
            users = service_users(token)
            target = find_user(users, args.delete)
            if not target:
                print(f"нет такого сервисного пользователя: {args.delete}")
                return 2
            if not args.yes:
                print(f"удалить {describe(target)}? повтори с --yes")
                return 2
            status, data = iam(token, "DELETE", f"/service_users/{user_id(target)}")
            if status not in (200, 204):
                print(f"удаление: {status} {data}")
                return 2
            print(f"удалён: {args.delete}")
            return 0

        account_id = args.account_id or entry.get("account_id") or account_domain(token)
        if not account_id:
            parser.error("нужен --account-id: он же домен Keystone при выпуске токена")
        project_id = args.project_id or entry.get("project_id") or ""
        roles = roles_payload(args.write, project_id)

        users = service_users(token)
        existing = find_user(users, args.name)
        password = ""
        if existing:
            uid = user_id(existing)
            if entry.get("login") == args.name and entry.get("password"):
                minted, _ = mint_iam_token(args.name, entry["password"], account_id)
                if minted:
                    password = entry["password"]
            if not password:
                password = generate_password()
                rotate_password(token, uid, password)
                print(f"пароль для {args.name} обновлён")
            else:
                print(f"пароль для {args.name} уже сохранён и рабочий")
        else:
            password = generate_password()
            uid, _ = create_user(token, args.name, password, roles)
            print(f"создан сервисный пользователь {args.name} [{uid}]")

        set_roles(token, uid, roles)
        print("роли: " + ", ".join(f"{r['role_name']}@{r['scope']}" for r in roles))

        account_token, detail = mint_iam_token(args.name, password, account_id)
        if not account_token:
            print(f"проверка account-токена: Keystone {detail}")
            return 2
        good, probe = probe_iam(account_token)
        print(f"account-токен: {'ок' if good else 'ошибка'} — {probe}")
        if not good:
            return 2

        if project_id:
            project_token, detail = mint_iam_token(args.name, password, account_id, project_id)
            if not project_token:
                print(f"проверка project-токена: Keystone {detail}")
                return 2
            good, probe = probe_project(project_token, project_id)
            print(f"project-токен: {'ок' if good else 'ошибка'} — {probe}")
            if not good:
                return 2

        new_entry = {
            "login": args.name,
            "password": password,
            "account_id": account_id,
            "project_id": project_id,
        }
        drop: tuple[str, ...] = () if args.keep_panel_tokens else ("token", "project_token")
        if args.s3:
            if not project_id:
                print("--s3: нужен --project-id, ключ выпускается в проект")
                return 2
            new_entry.update(make_credentials(token, uid, args.name, project_id))
            print("access key для S3 сохранён в файл учёток")
        data = merge_accounts(path, new_entry, drop)
        dropped = " (панельные токены убраны)" if drop else ""
        print(f"сохранено в {path}{dropped}, провайдеры: {', '.join(sorted(data))}")
        print("проверка: python scripts/selectel_auth.py --check")
        return 0
    except RuntimeError as error:
        print(f"ошибка: {error}")
        return 2


if __name__ == "__main__":
    sys.exit(main())

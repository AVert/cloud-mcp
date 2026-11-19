"""The service-user helper gives least privilege by default and never hides a secret in logs."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location(
    "selectel_service_user", SCRIPTS / "selectel_service_user.py"
)
service_user = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(service_user)


def test_password_has_every_class():
    password = service_user.generate_password()
    assert len(password) == 32
    assert any(char.islower() for char in password)
    assert any(char.isupper() for char in password)
    assert any(char.isdigit() for char in password)
    assert any(char in "!@#%^&*()-_=+" for char in password)
    assert service_user.generate_password() != password


def test_read_roles_cover_account_and_project():
    assert service_user.roles_payload(write=False) == [{"role_name": "reader", "scope": "account"}]
    assert service_user.roles_payload(write=False, project_id="pid") == [
        {"role_name": "reader", "scope": "account"},
        {"role_name": "reader", "scope": "project", "project_id": "pid"},
    ]


def test_write_role_is_a_single_member():
    assert service_user.roles_payload(write=True, project_id="pid") == [
        {"role_name": "member", "scope": "account"}
    ]


def test_user_lookup_and_id_shapes():
    users = [{"id": "a", "name": "svc-cloud-mcp"}, {"id": "b", "name": "other"}]
    found = service_user.find_user(users, "svc-cloud-mcp")
    assert found == {"id": "a", "name": "svc-cloud-mcp"}
    assert service_user.find_user(users, "missing") is None
    assert service_user.user_id({"id": "x"}) == "x"
    assert service_user.user_id({"service_user": {"id": "y"}}) == "y"
    assert service_user.user_id({}) == ""


def test_describe_renders_roles_without_secrets():
    user = {
        "id": "uid",
        "name": "svc-cloud-mcp",
        "password": "should-not-appear",
        "roles": [{"role_name": "reader", "scope": "account"}],
    }
    rendered = service_user.describe(user)
    assert "reader@account" in rendered
    assert "should-not-appear" not in rendered


def test_role_payload_shortens_project_id():
    user = {
        "id": "uid",
        "name": "svc",
        "roles": [
            {
                "role_name": "reader",
                "scope": "project",
                "project_id": "abcdef0123456789abcdef0123456789",
            }
        ],
    }
    assert ":abcdef01" in service_user.describe(user)

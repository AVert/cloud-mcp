import json
import re

import pytest
from jsonschema import Draft202012Validator

from sweb_mcp.config import Settings
from sweb_mcp.safety import authorize, classify
from sweb_mcp.spec import in_groups, load_methods


def test_all_methods_covered(specs_dir):
    raw = {(json.loads(f.read_text())["servers"][0]["url"].split("api.sweb.ru")[1], m["name"])
           for f in specs_dir.glob("*.json") for m in json.loads(f.read_text())["methods"]}
    ms = load_methods(specs_dir)
    assert len(ms) == len(raw) == 276
    assert len({m.tool_name for m in ms}) == len(ms)  # no tool name collisions


def test_tool_names_and_schemas_valid(specs_dir):
    for m in load_methods(specs_dir):
        assert re.fullmatch(r"[A-Za-z0-9_-]{1,64}", m.tool_name), m.tool_name
        Draft202012Validator.check_schema(m.input_schema(with_confirm=m.kind != "read"))


@pytest.mark.parametrize("path,name,kind", [
    ("/vps", "index", "read"), ("/vps", "createEnable", "read"), ("/vps", "reboot", "destructive"),
    ("/vps", "create", "paid"), ("/vps", "rename", "write"), ("/domains", "regList", "paid"),
    ("/domains", "removeList", "destructive"), ("/vh/mail", "getMailQuota", "read"),
    ("/vh/hosting", "databaseGetList", "read"), ("/monitoring/checks", "activateList", "write"),
])
def test_classify(path, name, kind):
    assert classify(path, name) == kind


def test_override():
    assert classify("/vps", "reboot", {"/vps:reboot": "write"}) == "write"


def test_authorize():
    ro, rw = Settings(), Settings(readonly=False)
    full = Settings(readonly=False, allow_destructive=True)
    assert authorize("read", False, ro) is None
    assert "SWEB_READONLY" in authorize("write", True, ro)
    assert "confirm" in authorize("write", False, rw)
    assert authorize("write", True, rw) is None
    assert "SWEB_ALLOW_DESTRUCTIVE" in authorize("paid", True, rw)
    assert authorize("destructive", True, full) is None


def test_groups(specs_dir):
    ms = load_methods(specs_dir)
    sel = [m for m in ms if in_groups(m, frozenset({"vh/mail"}))]
    assert sel and all(m.path == "/vh/mail" for m in sel)
    assert {m.path for m in ms if in_groups(m, frozenset({"vps"}))} >= {"/vps", "/vps/ip"}

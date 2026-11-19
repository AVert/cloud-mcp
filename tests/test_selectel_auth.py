"""The Selectel credential helper merges, never replaces, and fails loudly on a bad key."""

from __future__ import annotations

import importlib.util
import json
import stat
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "selectel_auth.py"
spec = importlib.util.spec_from_file_location("selectel_auth", SCRIPT)
auth = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(auth)


def test_merge_keeps_other_providers(tmp_path):
    path = tmp_path / "accounts.json"
    path.write_text(json.dumps({"timeweb": {"token": "T"}}), encoding="utf-8")
    data = auth.merge_accounts(path, {"static_token": "S"})
    assert data["timeweb"] == {"token": "T"}
    assert data["selectel"] == {"static_token": "S"}
    assert stat.S_IMODE(path.stat().st_mode) == 0o600

    data = auth.merge_accounts(path, {"token": "I"})
    assert data["selectel"] == {"static_token": "S", "token": "I"}


def test_merge_accepts_legacy_string_entry(tmp_path):
    path = tmp_path / "accounts.json"
    path.write_text(json.dumps({"selectel": "OLD"}), encoding="utf-8")
    data = auth.merge_accounts(path, {"static_token": "S"})
    assert data["selectel"] == {"token": "OLD", "static_token": "S"}


def test_merge_survives_broken_file(tmp_path):
    path = tmp_path / "accounts.json"
    path.write_text("{not json", encoding="utf-8")
    data = auth.merge_accounts(path, {"token": "I"})
    assert data == {"selectel": {"token": "I"}}


def test_check_reports_missing_file(tmp_path, capsys):
    assert auth.check(tmp_path / "nope.json") == 1
    assert "нет файла" in capsys.readouterr().out


def test_check_marks_working_and_broken_credentials(tmp_path, monkeypatch, capsys):
    path = tmp_path / "accounts.json"
    path.write_text(
        json.dumps({"selectel": {"token": "GOOD", "static_token": "BAD"}}), encoding="utf-8"
    )
    monkeypatch.setattr(auth, "probe_iam", lambda token: (token == "GOOD", "200"))
    monkeypatch.setattr(auth, "probe_static", lambda token: (token == "GOOD", "401"))
    assert auth.check(path) == 1
    out = capsys.readouterr().out
    assert "IAM-токен: ок" in out
    assert "static-токен: ошибка" in out


def test_mint_reports_bad_password(monkeypatch):
    monkeypatch.setattr(auth, "request", lambda *a, **k: (401, {}, b'{"error":{}}'))
    token, detail = auth.mint_iam_token("svc", "wrong", "123")
    assert token is None
    assert "401" in detail


def test_mint_reads_subject_token(monkeypatch):
    monkeypatch.setattr(auth, "request", lambda *a, **k: (201, {"X-Subject-Token": "TOK"}, b"{}"))
    assert auth.mint_iam_token("svc", "pwd", "123") == ("TOK", "ok")


def test_merge_drops_stale_panel_tokens(tmp_path):
    path = tmp_path / "accounts.json"
    path.write_text(
        json.dumps({"timeweb": {"token": "T"}, "selectel": {"token": "P", "project_token": "Q"}}),
        encoding="utf-8",
    )
    data = auth.merge_accounts(
        path,
        {"login": "svc-cloud-mcp", "password": "x", "account_id": "1"},
        drop=("token", "project_token"),
    )
    assert data["timeweb"] == {"token": "T"}
    assert data["selectel"] == {"login": "svc-cloud-mcp", "password": "x", "account_id": "1"}
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_s3_headers_are_deterministic_sigv4():
    import datetime

    now = datetime.datetime(2026, 11, 19, 12, 0, 0, tzinfo=datetime.UTC)
    headers = auth.s3_headers("ACC", "SEC", "s3.ru-1.storage.selcloud.ru", "ru-1", now)
    assert headers["x-amz-date"] == "20261119T120000Z"
    assert headers["x-amz-content-sha256"] == "UNSIGNED-PAYLOAD"
    assert "Credential=ACC/20261119/ru-1/s3/aws4_request" in headers["Authorization"]
    assert "SignedHeaders=host;x-amz-date" in headers["Authorization"]


def test_probe_s3_reports_real_endpoint(monkeypatch):
    monkeypatch.setattr(auth, "request", lambda *a, **k: (200, {}, b"<ListAllMyBuckets/>"))
    good, detail = auth.probe_s3("A", "S", "s3.ru-1.storage.selcloud.ru")
    assert good and "s3.ru-1" in detail

    monkeypatch.setattr(
        auth, "request", lambda *a, **k: (403, {}, b"<Error><Code>InvalidAccessKeyId</Code>")
    )
    good, detail = auth.probe_s3("A", "S", "s3.ru-1.storage.selcloud.ru")
    assert not good and "403" in detail


def test_probe_s3_anywhere_skips_dead_hosts(monkeypatch):
    def fake_request(url, *args, **kwargs):
        if "ru-1" in url:
            raise auth.urllib.error.URLError("Name or service not known", OSError(-2, "nope"))
        return 200, {}, b"ok"

    monkeypatch.setattr(auth, "request", fake_request)
    good, detail, host = auth.probe_s3_anywhere("A", "S", "")
    assert good and host == "s3.ru-3.storage.selcloud.ru"


def test_probe_s3_pair_falls_back_to_ftp(monkeypatch):
    def fake_s3(access, secret, preferred=""):
        return False, "403 InvalidAccessKeyId", ""

    def fake_ftp(access, secret, host=""):
        return True, "FTP-логин ок"

    monkeypatch.setattr(auth, "probe_s3_anywhere", fake_s3)
    monkeypatch.setattr(auth, "probe_s3_ftp", fake_ftp)
    good, detail, host = auth.probe_s3_pair("A", "S")
    assert good and host == "" and "FTP" in detail

    monkeypatch.setattr(auth, "probe_s3_ftp", lambda *a: (False, "530"))
    good, detail, host = auth.probe_s3_pair("A", "S")
    assert not good and "403" in detail

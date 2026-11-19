"""The offline Tilda inventory parses what the published page actually contains."""

from __future__ import annotations

import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "tilda_backup.py"
spec = importlib.util.spec_from_file_location("tilda_backup", SCRIPT)
tilda = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(tilda)

PAGE = b"""<!doctype html>
<html><head><title>Test &amp; page</title>
<meta name="description" content="Desc">
<meta property="og:title" content="OG title"></head>
<body>
<div id="rec100" data-record-type="131"><img src="https://static.tildacdn.com/a.jpg"></div>
<div id="rec101" data-record-type="215">
  <a href="/about">about</a><a href="https://example.org/x">out</a>
  <div style="background-image: url('https://static.tildacdn.com/bg.png')"></div>
  <form action="/forms"></form>
</div>
<script src="https://static.tildacdn.com/js/tilda.js"></script>
<link rel="stylesheet" href="https://static.tildacdn.com/css/tilda.css">
</body></html>"""


def test_inventory_fields():
    page = tilda.page_inventory("https://example.com/", PAGE)
    assert page["title"] == "Test & page"
    assert page["description"] == "Desc"
    assert page["og"] == {"og:title": "OG title"}
    assert page["blocks"] == 2
    assert page["record_types"] == ["131", "215"]
    assert set(page["images"]) == {
        "https://static.tildacdn.com/a.jpg",
        "https://static.tildacdn.com/bg.png",
    }
    assert page["links"] == {"internal": ["/about"], "external": ["https://example.org/x"]}
    assert page["forms"] == 1
    assert page["scripts"] == ["https://static.tildacdn.com/js/tilda.js"]
    assert page["styles"] == ["https://static.tildacdn.com/css/tilda.css"]
    assert page["bytes"] == len(PAGE)


def test_safe_names_are_unique():
    seen: dict[str, int] = {}
    first = tilda.safe_name("https://example.com/page.html", seen)
    second = tilda.safe_name("https://example.com/page", seen)
    assert first != second
    assert first.endswith(".html")


def test_sitemap_parsing(monkeypatch):
    xml = b"<urlset><url><loc>https://example.com/a</loc></url><url><loc>https://example.com/b</loc></url></urlset>"
    monkeypatch.setattr(tilda, "fetch", lambda url, limit=0: (200, xml))
    assert tilda.sitemap_urls("https://example.com") == [
        "https://example.com/a",
        "https://example.com/b",
    ]

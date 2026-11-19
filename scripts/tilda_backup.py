#!/usr/bin/env python3
"""Offline backup and inventory of a published Tilda site — no API, no credentials, no tokens.

Tilda's export API and MCP keys require the Business tariff; published pages are public, so the
whole read side works without any tariff: sitemap -> pages -> structured inventory on disk. The
model then reads the inventory (a few hundred bytes per page) instead of driving a browser.

    python scripts/tilda_backup.py --site https://example.com --out ~/tilda/example
    python scripts/tilda_backup.py --site https://example.com --out ~/tilda/example --diff
    python scripts/tilda_backup.py --url https://example.com/page.html --out ~/tilda/one
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from html import unescape
from pathlib import Path
from urllib.parse import urlparse

USER_AGENT = "tilda-backup/1.0 (+offline read-only inventory)"
SITEMAP_LIMIT_BYTES = 8 * 1024 * 1024
PAGE_LIMIT_BYTES = 8 * 1024 * 1024

TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.S | re.I)
DESCRIPTION = re.compile(r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']*)', re.I)
OG = re.compile(r'<meta[^>]+property=["\'](og:[a-z:]+)["\'][^>]+content=["\']([^"\']*)', re.I)
BLOCK = re.compile(r'<div[^>]+id=["\'](rec\d+)["\'][^>]*>')
RECORD_TYPE = re.compile(r'data-record-type=["\'](\d+)["\']')
IMAGE = re.compile(r'<img[^>]+src=["\']([^"\'>]+)', re.I)
BG_IMAGE = re.compile(r"background-image:\s*url\(([^)]+)\)", re.I)
LINK = re.compile(r'<a[^>]+href=["\']([^"\'>]+)', re.I)
FORM = re.compile(r'<form[^>]+(?:action=["\']([^"\']*)["\'])?', re.I)
SCRIPT = re.compile(r'<script[^>]+src=["\']([^"\'>]+)', re.I)
STYLE = re.compile(r'<link[^>]+rel=["\']stylesheet["\'][^>]+href=["\']([^"\'>]+)', re.I)
LOC = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>", re.I)


def fetch(url: str, limit: int = PAGE_LIMIT_BYTES) -> tuple[int, bytes]:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request, timeout=60) as response:
        body = response.read(limit)
        return response.status, body


def sitemap_urls(site: str) -> list[str]:
    site = site.rstrip("/")
    for candidate in (f"{site}/sitemap.xml", f"{site}/sitemap_index.xml"):
        try:
            status, body = fetch(candidate, SITEMAP_LIMIT_BYTES)
        except (urllib.error.URLError, OSError):
            continue
        if status != 200:
            continue
        urls = LOC.findall(body.decode("utf-8", "replace"))
        if urls:
            return list(dict.fromkeys(urls))
    return [site + "/"]


def page_inventory(url: str, body: bytes) -> dict[str, object]:
    html = body.decode("utf-8", "replace")
    images = {unescape(u) for u in IMAGE.findall(html)}
    images |= {unescape(u).strip("\"' ") for u in BG_IMAGE.findall(html)}
    links = [unescape(u) for u in LINK.findall(html)]
    host = urlparse(url).netloc
    internal = sorted({u for u in links if u.startswith("/") or host in u})
    external = sorted({u for u in links if u.startswith("http") and host not in u})
    title = TITLE.search(html)
    description = DESCRIPTION.search(html)
    return {
        "url": url,
        "status": 200,
        "bytes": len(body),
        "sha256": hashlib.sha256(html.encode("utf-8", "replace")).hexdigest(),
        "title": unescape(title.group(1)).strip() if title else "",
        "description": unescape(description.group(1)).strip() if description else "",
        "og": {key: unescape(value) for key, value in OG.findall(html)},
        "blocks": len(BLOCK.findall(html)),
        "record_types": sorted({t for t in RECORD_TYPE.findall(html)}),
        "images": sorted(images),
        "links": {"internal": internal, "external": external},
        "forms": len(FORM.findall(html)),
        "scripts": sorted({unescape(u) for u in SCRIPT.findall(html)}),
        "styles": sorted({unescape(u) for u in STYLE.findall(html)}),
    }


def safe_name(url: str, seen: dict[str, int]) -> str:
    path = urlparse(url).path.strip("/") or "index"
    name = re.sub(r"[^a-zA-Z0-9._-]+", "_", path)
    if name.endswith(".html"):
        name = name[: -len(".html")]
    count = seen.get(name, 0) + 1
    seen[name] = count
    return f"{name}.html" if count == 1 else f"{name}__{count}.html"


def backup(urls: list[str], out: Path, workers: int, delay: float) -> dict[str, object]:
    pages_dir = out / "pages"
    pages_dir.mkdir(parents=True, exist_ok=True)
    seen: dict[str, int] = {}
    entries: list[dict[str, object]] = []
    errors: list[dict[str, str]] = []

    def one(url: str) -> dict[str, object] | dict[str, str]:
        try:
            status, body = fetch(url)
        except (urllib.error.URLError, OSError) as error:
            return {"url": url, "error": str(error)[:300]}
        if status != 200:
            return {"url": url, "error": f"HTTP {status}"}
        if delay:
            time.sleep(delay)
        (pages_dir / safe_name(url, seen)).write_bytes(body)
        return page_inventory(url, body)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        for result in pool.map(one, urls):
            if "error" in result:
                errors.append(result)  # type: ignore[arg-type]
            else:
                entries.append(result)

    entries.sort(key=lambda item: str(item["url"]))
    index = {
        "pages": entries,
        "errors": errors,
        "total": len(entries),
        "bytes": sum(int(item["bytes"]) for item in entries),
    }
    (out / "index.json").write_text(
        json.dumps(index, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    return index


def diff(out: Path, index: dict[str, object]) -> list[dict[str, object]]:
    previous_file = out / "index.prev.json"
    previous = (
        json.loads(previous_file.read_text(encoding="utf-8")) if previous_file.exists() else None
    )
    changes: list[dict[str, object]] = []
    if previous is not None:
        old = {str(page["url"]): page for page in previous.get("pages", [])}
        new = {str(page["url"]): page for page in index["pages"]}  # type: ignore[index]
        for url in sorted(set(old) | set(new)):
            if url not in old:
                changes.append({"url": url, "change": "added"})
            elif url not in new:
                changes.append({"url": url, "change": "removed"})
            elif old[url]["sha256"] != new[url]["sha256"]:
                fields = [
                    key
                    for key in ("title", "description", "blocks", "images", "links", "record_types")
                    if old[url].get(key) != new[url].get(key)
                ]
                changes.append({"url": url, "change": "changed", "fields": fields})
    (out / "index.prev.json").write_text(
        json.dumps(index, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    return changes


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--site", help="site root; pages come from /sitemap.xml")
    group.add_argument("--url", help="single page URL")
    parser.add_argument("--out", required=True, help="backup directory")
    parser.add_argument("--max-pages", type=int, default=0, help="0 = no limit")
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--delay", type=float, default=0.2, help="seconds between requests")
    parser.add_argument("--diff", action="store_true", help="compare with the previous run")
    args = parser.parse_args()

    urls = sitemap_urls(args.site) if args.site else [args.url]
    if args.max_pages:
        urls = urls[: args.max_pages]
    out = Path(args.out).expanduser()
    index = backup(urls, out, max(1, min(args.workers, 4)), args.delay)
    print(
        f"pages: {index['total']}, errors: {len(index['errors'])}, "
        f"bytes: {index['bytes']}, index: {out / 'index.json'}"
    )
    if args.diff:
        changes = diff(out, index)
        print(json.dumps(changes[:50], ensure_ascii=False, indent=1))
        print(f"changes: {len(changes)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

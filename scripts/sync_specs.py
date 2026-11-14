#!/usr/bin/env python3
"""Refresh specs/*.json from the live docs site (apidoc.sweb.ru).

The site is a React SPA that inlines one OpenRPC document per API object in its JS
bundle as `JSON.parse("...")`. Logic ported from sanchpet/sweb-go-sdk (MIT, api-spec/gen).
Usage: sync_specs.py [--check]   (--check: report drift, write nothing)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import httpx

DOCS_URL = os.environ.get("SWEB_DOCS_URL", "https://apidoc.sweb.ru")
API_HOST = os.environ.get("SWEB_API_URL", "https://api.sweb.ru")
OUT = Path(os.environ.get("SWEB_SPECS_DIR") or Path(__file__).resolve().parents[1] / "specs")
NEEDLE = "JSON.parse("


def fetch(c: httpx.Client, url: str) -> str:
    r = c.get(url)
    r.raise_for_status()
    return r.text


def extract(src: str) -> list[dict]:
    """Find every JSON.parse("...") literal (double-decode) that is an OpenRPC document."""
    docs, seen, i = [], set(), 0
    while (idx := src.find(NEEDLE, i)) >= 0:
        p = idx + len(NEEDLE)
        if p >= len(src) or src[p] != '"':
            i = p
            continue
        j = p + 1
        while j < len(src) and src[j] != '"':
            j += 2 if src[j] == "\\" else 1
        if j >= len(src):
            break
        lit, i = src[p : j + 1], j + 1
        try:
            obj = json.loads(json.loads(lit))
        except ValueError:
            continue
        if not isinstance(obj, dict) or not ("openrpc" in obj or "methods" in obj):
            continue
        norm = json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False)
        if norm not in seen:
            seen.add(norm)
            docs.append(obj)
    return docs


def slug(doc: dict) -> str:
    url = (doc.get("servers") or [{}])[0].get("url", "")
    return url.removeprefix(API_HOST).strip("/").lower().replace("/", "-") or "object"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    check = ap.parse_args().check
    with httpx.Client(timeout=60, trust_env=False, follow_redirects=True) as c:
        files = json.loads(fetch(c, DOCS_URL + "/asset-manifest.json"))["files"].values()
        urls = sorted(
            {(DOCS_URL + v if v.startswith("/") else v) for v in files if v.endswith(".js")}
        )
        blob = "\n".join(fetch(c, u) for u in urls)
    docs = extract(blob)
    if not docs:
        print("no OpenRPC documents found - bundle layout may have changed", file=sys.stderr)
        return 1
    # larger documents first so slug collisions get a stable -2 suffix
    docs.sort(key=lambda d: (slug(d), -len(d.get("methods", [])), d["methods"][0]["name"]))
    counts: dict[str, int] = {}
    new: dict[str, str] = {}
    for d in docs:
        s = slug(d)
        counts[s] = counts.get(s, 0) + 1
        name = s if counts[s] == 1 else f"{s}-{counts[s]}"
        new[name + ".json"] = json.dumps(d, indent=2, sort_keys=True, ensure_ascii=False) + "\n"

    def methods(text: str) -> set[str]:
        d = json.loads(text)
        return {f"{d['servers'][0]['url']}:{m['name']}" for m in d["methods"]}

    old = {f.name: f.read_text(encoding="utf-8") for f in OUT.glob("*.json")}
    old_m = set().union(*(methods(t) for t in old.values())) if old else set()
    new_m = set().union(*(methods(t) for t in new.values()))
    print(f"documents: {len(old)} -> {len(new)}; methods: {len(old_m)} -> {len(new_m)}")
    for m in sorted(new_m - old_m):
        print("  + method", m)
    for m in sorted(old_m - new_m):
        print("  - method", m)
    changed = sorted(n for n in new if json.loads(new[n]) != json.loads(old.get(n, "null")))
    print("changed files:", changed or "none")
    if check:
        return 1 if (new_m != old_m or changed) else 0
    OUT.mkdir(exist_ok=True)
    for f in OUT.glob("*.json"):
        f.unlink()
    for n, t in new.items():
        (OUT / n).write_text(t, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())

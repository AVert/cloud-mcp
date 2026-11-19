#!/usr/bin/env python3
"""Live sweep: call every read-only operation of a provider (no path templates) and classify
the outcomes, so snapshot bugs surface as 401/404 clusters instead of surprises later.

Usage:
    python scripts/live_sweep.py --provider selectel --output /tmp/sweep.json
    python scripts/live_sweep.py --provider timeweb --concurrency 3

Read-only by construction: operations with kind != "read" and templated paths are skipped.
Credentials come from the accounts file; the table printed at the end groups outcomes per
product — see the spec-live-sweep skill for the failure taxonomy.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cloud_mcp import registry  # noqa: E402
from cloud_mcp.client import CloudClient, CloudError  # noqa: E402
from cloud_mcp.config import Settings  # noqa: E402

OK_CODES = ("200", "204")


def outcome(item: dict) -> str:
    return item.get("error") or str(item["status"])


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", default="selectel")
    parser.add_argument("--output", default="/tmp/live_sweep.json")
    parser.add_argument("--concurrency", type=int, default=6)
    args = parser.parse_args()

    settings = Settings.from_env()
    providers = registry.enabled(registry.load(), settings.providers)
    provider = providers[args.provider]
    targets = [op for op in provider.operations if op.kind == "read" and "{" not in op.path]
    print(
        f"{args.provider}: read-операций без шаблонных id: "
        f"{len(targets)} из {len(provider.operations)}"
    )

    client = CloudClient(settings)
    semaphore = asyncio.Semaphore(args.concurrency)
    results: dict[str, dict] = {}

    async def run(op):
        async with semaphore:
            try:
                call = await client.request(op, {}, {}, None)
                results[op.tool] = {"status": call.status, "product": op.product, "path": op.path}
            except CloudError as error:
                results[op.tool] = {
                    "status": error.status or -1,
                    "product": op.product,
                    "path": op.path,
                    "error": error.code,
                }

    progress = 0
    tasks = []

    async def tracked(op):
        nonlocal progress
        await run(op)
        progress += 1
        if progress % 50 == 0:
            print(f"... {progress}/{len(targets)}")

    tasks = [tracked(op) for op in targets]
    await asyncio.gather(*tasks)

    by_product: dict[str, Counter] = defaultdict(Counter)
    for item in results.values():
        by_product[item["product"]][outcome(item)] += 1
    header = f"{'продукт':32} {'ок':>4} {'401':>4} {'403':>4} {'404':>4} {'прочее':>8}"
    print(header)
    for product in sorted(by_product):
        counts = by_product[product]
        ok = sum(v for k, v in counts.items() if k in OK_CODES)
        unauth = sum(v for k, v in counts.items() if k == "401")
        forbidden = sum(v for k, v in counts.items() if k == "403")
        missing = sum(v for k, v in counts.items() if k == "404")
        rest = sum(counts.values()) - ok - unauth - forbidden - missing
        print(f"{product:32} {ok:>4} {unauth:>4} {forbidden:>4} {missing:>4} {rest:>8}")

    Path(args.output).write_text(
        json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print(f"полный отчёт: {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

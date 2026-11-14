from __future__ import annotations

import asyncio

import mcp.server.stdio

from .client import SwebClient
from .config import Settings
from .server import build_server, log


async def serve() -> None:
    settings = Settings.from_env()
    client = SwebClient(settings)
    server = build_server(settings, client)
    log(f"readonly={settings.readonly} destructive={settings.allow_destructive} "
        f"groups={sorted(settings.groups) or 'all'} creds={'set' if settings.login else 'MISSING'}")
    try:
        async with mcp.server.stdio.stdio_server() as (read, write):
            await server.run(read, write, server.create_initialization_options())
    finally:
        await client.aclose()


def main() -> None:
    asyncio.run(serve())


if __name__ == "__main__":
    main()

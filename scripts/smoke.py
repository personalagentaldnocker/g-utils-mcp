"""Read-only MCP smoke check against a configured endpoint."""

import asyncio
import json
import os

import typer
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


async def run():
    url = os.environ["MCP_URL"].rstrip("/")
    if not url.startswith("https://"):
        raise ValueError("MCP_URL must be HTTPS")
    headers = {"Authorization": "Bearer " + os.environ["MCP_TOKEN"]}
    async with streamable_http_client(url + "/mcp", headers=headers) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            result = await session.call_tool("workspace_capabilities", {})
            if result.isError:
                raise ValueError("Capability check failed")
            print(
                json.dumps(
                    {"tool_count": len(tools.tools), "capabilities": result.structuredContent},
                    indent=2,
                )
            )


def main():
    try:
        asyncio.run(run())
    except Exception:
        typer.echo("Smoke check failed; check configuration, authentication and policy", err=True)
        raise typer.Exit(1) from None


if __name__ == "__main__":
    main()

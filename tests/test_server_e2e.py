from __future__ import annotations

import asyncio
import socket
from pathlib import Path
from typing import cast

from fastmcp import Client
from mcp.types import TextResourceContents

from lmnop.handler.models import AppendResult, ResolveResult
from lmnop.handler.server import HandlerApplication, create_mcp
from tests.helpers import FakeObsidianCli, make_settings, seed_vault


def test_client_flow_without_authentication(tmp_path: Path) -> None:
    _ = seed_vault(tmp_path)
    settings = make_settings(tmp_path)
    cli = FakeObsidianCli(settings)
    app = HandlerApplication(settings, cli=cli)
    mcp = create_mcp(app)

    async def run() -> None:
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            address = cast(tuple[str, int], sock.getsockname())
            port = address[1]

        server_task = asyncio.create_task(
            mcp.run_http_async(host="127.0.0.1", port=port, show_banner=False)
        )
        try:
            await asyncio.sleep(0.25)
            async with Client(f"http://127.0.0.1:{port}/mcp") as client:
                resources = await client.list_resources()
                tools = await client.list_tools()
                assert any(
                    str(resource.uri) == "obsidian://daily-standup"
                    for resource in resources
                )
                assert {tool.name for tool in tools} == {"append", "resolve"}
                briefing = await client.read_resource("obsidian://daily-standup")
                first = briefing[0]
                assert isinstance(first, TextResourceContents)
                assert first.mimeType == "text/markdown"
                assert "Daily Standup" in first.text
                append_result = await client.call_tool(
                    "append", {"target": "daily", "content": "- [ ] Test new task"}
                )
                appended = AppendResult.model_validate(cast(object, append_result.data))
                assert appended.success is True
                task_id = next(iter(appended.new_tasks))
                resolve_result = await client.call_tool(
                    "resolve", {"id": task_id, "resolution": "done"}
                )
                resolved = ResolveResult.model_validate(
                    cast(object, resolve_result.data)
                )
                assert resolved.resolution == "done"
        finally:
            _ = server_task.cancel()
            try:
                _ = await server_task
            except BaseException:
                pass

    asyncio.run(run())

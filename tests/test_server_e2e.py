from __future__ import annotations

import asyncio
import socket
from pathlib import Path
from typing import cast

import pytest
from fastmcp import Client
from fastmcp.client.client import CallToolResult
from mcp.shared.exceptions import McpError
from mcp.types import TextContent

from lmnop.handler.models import AppendResult, TaskStatusResult
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
                assert resources == []
                assert {tool.name for tool in tools} == {
                    "append_note",
                    "set_task_status",
                    "start_daily_standup",
                }
                append_tool = next(tool for tool in tools if tool.name == "append_note")
                input_schema = cast(dict[str, object], append_tool.inputSchema)
                properties = cast(dict[str, object], input_schema["properties"])
                assert properties.keys() == {"content"}
                resolve_tool = next(
                    tool for tool in tools if tool.name == "set_task_status"
                )
                resolve_schema = cast(dict[str, object], resolve_tool.inputSchema)
                resolve_properties = cast(
                    dict[str, object], resolve_schema["properties"]
                )
                assert resolve_properties.keys() == {"id", "status"}
                with pytest.raises(McpError, match="Unknown resource"):
                    _ = await client.read_resource("obsidian://daily-standup")
                standup: CallToolResult = await client.call_tool(
                    "start_daily_standup", {}
                )
                first_content = standup.content[0]
                assert isinstance(first_content, TextContent)
                assert "Daily Standup" in first_content.text
                append_result = await client.call_tool(
                    "append_note", {"content": "- [ ] Test new task"}
                )
                appended = AppendResult.model_validate(cast(object, append_result.data))
                assert appended.success is True
                task_id = next(iter(appended.new_tasks))
                resolve_result = await client.call_tool(
                    "set_task_status", {"id": task_id, "status": "x"}
                )
                resolved = TaskStatusResult.model_validate(
                    cast(object, resolve_result.data)
                )
                assert resolved.status == "x"
        finally:
            _ = server_task.cancel()
            try:
                _ = await server_task
            except BaseException:
                pass

    asyncio.run(run())

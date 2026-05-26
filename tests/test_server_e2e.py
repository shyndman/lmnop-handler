from __future__ import annotations

import asyncio
from datetime import date
import socket
from pathlib import Path
from typing import cast

import pytest
from fastmcp import Client
from fastmcp.client.client import CallToolResult
from mcp.shared.exceptions import McpError
from mcp.types import TextContent
from starlette.testclient import TestClient

from lmnop.handler.application import HandlerApplication
from lmnop.handler.mcp_api import build_http_middleware, create_mcp
from lmnop.handler.models import AppendResult, TaskStatusResult
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
                assert (
                    f"Current date: {date.today().isoformat()}." in first_content.text
                )
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


def test_http_app_allows_zrok_browser_cors_origin(tmp_path: Path) -> None:
    _ = seed_vault(tmp_path)
    settings = make_settings(tmp_path)
    cli = FakeObsidianCli(settings)
    app = HandlerApplication(settings, cli=cli)
    http_app = create_mcp(app).http_app(middleware=build_http_middleware(settings))

    with TestClient(http_app) as client:
        allowed = client.options(
            "/mcp",
            headers={
                "Origin": "https://debug.share.zrok.io",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": (
                    "mcp-protocol-version,mcp-session-id,authorization,content-type"
                ),
            },
        )
        assert allowed.status_code == 200
        assert (
            allowed.headers["access-control-allow-origin"]
            == "https://debug.share.zrok.io"
        )
        assert "mcp-session-id" in allowed.headers["access-control-allow-headers"]

        request = client.get("/mcp", headers={"Origin": "https://debug.share.zrok.io"})
        assert request.headers["access-control-allow-origin"] == (
            "https://debug.share.zrok.io"
        )
        assert request.headers["access-control-expose-headers"] == "mcp-session-id"
        assert request.headers["mcp-session-id"]

        rejected = client.options(
            "/mcp",
            headers={
                "Origin": "https://debug.example.com",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": (
                    "mcp-protocol-version,mcp-session-id,authorization,content-type"
                ),
            },
        )
        assert rejected.status_code == 400
        assert rejected.headers.get("access-control-allow-origin") is None

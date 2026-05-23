from __future__ import annotations

from collections.abc import Sequence
from contextvars import ContextVar
from typing import TYPE_CHECKING, override

from mcp.types import ToolAnnotations

from fastmcp.server.dependencies import get_context
from fastmcp.server.transforms import GetResourceNext, GetToolNext, Transform
from fastmcp.tools.base import Tool
from fastmcp.utilities.versions import VersionSpec

if TYPE_CHECKING:
    from fastmcp.resources.base import Resource

_TOOL_NAME = "start_daily_standup"
_ANNOTATIONS = ToolAnnotations(readOnlyHint=True, idempotentHint=True)
_ALLOW_STANDUP_RESOURCE_READ: ContextVar[bool] = ContextVar(
    "allow_standup_resource_read", default=False
)


class StandupTool(Transform):
    """Expose the daily-standup resource as a tool and hide the resource.

    Designed for tools-only MCP clients (ChatGPT, Claude.ai web) that do not
    support the resources protocol.
    """

    _resource_uri: str
    _resource_description: str

    def __init__(self, *, resource_uri: str, resource_description: str) -> None:
        self._resource_uri = resource_uri
        self._resource_description = resource_description

    # -- tools ----------------------------------------------------------------

    @override
    async def list_tools(self, tools: Sequence[Tool]) -> Sequence[Tool]:
        return [*tools, self._make_tool()]

    @override
    async def get_tool(
        self,
        name: str,
        call_next: GetToolNext,
        *,
        version: VersionSpec | None = None,
    ) -> Tool | None:
        if name == _TOOL_NAME:
            return self._make_tool()
        return await call_next(name, version=version)

    # -- resources (hidden) ---------------------------------------------------

    @override
    async def list_resources(self, resources: Sequence[Resource]) -> Sequence[Resource]:
        return []

    @override
    async def get_resource(
        self,
        uri: str,
        call_next: GetResourceNext,
        *,
        version: VersionSpec | None = None,
    ) -> Resource | None:
        if uri == self._resource_uri and not _ALLOW_STANDUP_RESOURCE_READ.get():
            return None
        return await call_next(uri, version=version)

    # -- internals ------------------------------------------------------------

    def _make_tool(self) -> Tool:
        async def start_daily_standup() -> str:
            ctx = get_context()
            token = _ALLOW_STANDUP_RESOURCE_READ.set(True)
            try:
                result = await ctx.fastmcp.read_resource(self._resource_uri)
            finally:
                _ALLOW_STANDUP_RESOURCE_READ.reset(token)
            content = result.contents[0].content
            if isinstance(content, bytes):
                return content.decode()
            return content

        start_daily_standup.__doc__ = self._resource_description

        return Tool.from_function(fn=start_daily_standup, annotations=_ANNOTATIONS)

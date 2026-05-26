from __future__ import annotations

from fastmcp import Context, FastMCP
from fastmcp.resources import ResourceContent, ResourceResult
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware

from .application import EnvironmentApplication, HandlerApplication
from .config import Settings

RESOURCE_URI = "obsidian://daily-standup"
RESOURCE_NAME = "Daily Standup"
RESOURCE_DESCRIPTION = " ".join(
    """
    The authoritative briefing for starting today's standup. Read this first when
    beginning the daily standup workflow. It contains the workflow guidance and the
    current vault data required to conduct the conversation: what matters now, what
    is coming soon, what still needs triage, what was recently resolved, and the
    recent note context needed to talk through it.
    """.split()
)
_APPEND_NOTE_DESCRIPTION = " ".join(
    """
    Append content to today's daily note. During standup, use this proactively to
    capture decisions, context, and new tasks as they arise; do not ask for
    confirmation first unless the content is ambiguous. Notes are stored as
    outliner bullets; plain lines are converted to bullets.
    """.split()
)
_CORS_ALLOW_METHODS = ("GET", "POST", "DELETE", "OPTIONS")
_CORS_ALLOW_HEADERS = (
    "mcp-protocol-version",
    "mcp-session-id",
    "Authorization",
    "Content-Type",
)
_CORS_EXPOSE_HEADERS = ("mcp-session-id",)


def build_http_middleware(settings: Settings) -> list[Middleware]:
    if settings.cors_allow_origin_regex is None:
        return []
    return [
        Middleware(
            CORSMiddleware,
            allow_origin_regex=settings.cors_allow_origin_regex,
            allow_methods=_CORS_ALLOW_METHODS,
            allow_headers=_CORS_ALLOW_HEADERS,
            expose_headers=_CORS_EXPOSE_HEADERS,
        )
    ]


def create_mcp(runtime: HandlerApplication | EnvironmentApplication) -> FastMCP:
    mcp = FastMCP("lmnop:handler")

    @mcp.resource(
        RESOURCE_URI,
        name=RESOURCE_NAME,
        description=RESOURCE_DESCRIPTION,
        mime_type="text/markdown",
        annotations={"readOnlyHint": True, "idempotentHint": True},
    )
    async def daily_standup_resource(ctx: Context) -> ResourceResult:
        payload = await runtime.daily_standup(ctx.client_id or "")
        return ResourceResult(
            contents=[ResourceContent(content=payload, mime_type="text/markdown")]
        )

    @mcp.tool(
        name="append_note",
        description=_APPEND_NOTE_DESCRIPTION,
        annotations={
            "destructiveHint": True,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )
    async def append_note_tool(content: str, ctx: Context) -> dict[str, object]:
        return (await runtime.append(ctx.client_id or "", content)).model_dump(
            mode="python"
        )

    @mcp.tool(
        name="set_task_status",
        annotations={
            "destructiveHint": True,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )
    async def set_task_status_tool(
        id: str, status: str, ctx: Context
    ) -> dict[str, object]:
        """Set a task checkbox status.

        Use the exact status character from the standup workflow: space for open,
        x for done, - for dropped/cancelled, > for carried forward, ! for attention,
        / for in progress, or ? for question. This only changes the existing task's
        checkbox status. It never edits task text and never creates replacement tasks;
        use append_note separately when the current task should be rewritten or copied.
        """
        return (
            await runtime.set_task_status(ctx.client_id or "", id, status)
        ).model_dump(mode="python")

    from .transforms import StandupTool

    _ = (daily_standup_resource, append_note_tool, set_task_status_tool)

    mcp.add_transform(
        StandupTool(
            resource_uri=RESOURCE_URI,
            resource_description=RESOURCE_DESCRIPTION,
        )
    )
    return mcp

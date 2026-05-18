# lmnop:handler

Obsidian-backed FastMCP server over Streamable HTTP.

## Run

Set the required environment first:

```bash
export LMNOP_HANDLER_VAULT_ROOT=/path/to/vault
export LMNOP_HANDLER_BEARER_TOKENS='{"claude":"secret-token"}'
```

Then start the server:

```bash
uv run lmnop-handler
```

The MCP endpoint is available at:

```text
http://127.0.0.1:8000/mcp
```

## Surface

- resource: `obsidian://daily-standup`
- tools: `append`, `resolve`

## Inspect the server

```bash
uv run fastmcp inspect src/lmnop/handler/__init__.py:mcp
```

## Call the server

```python
import asyncio
from fastmcp import Client


async def main() -> None:
    async with Client("http://127.0.0.1:8000/mcp", auth="secret-token") as client:
        briefing = await client.read_resource("obsidian://daily-standup")
        print(briefing[0].text)


asyncio.run(main())
```

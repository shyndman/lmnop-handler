# solo-daily

Hello-world FastMCP server over Streamable HTTP.

## Run

```bash
uv run solo-daily
```

The MCP endpoint will be available at:

```text
http://127.0.0.1:8000/mcp
```

Behind your edge terminator, point the consuming machine at the public HTTPS URL for that same path:

```text
https://your-host/mcp
```

## Inspect the server

```bash
uv run fastmcp inspect src/solo_daily/__init__.py:mcp
```

## Call the hello tool

```python
import asyncio
from fastmcp import Client


async def main() -> None:
    async with Client("http://127.0.0.1:8000/mcp") as client:
        result = await client.call_tool("hello", {"name": "Scott"})
        print(result)


asyncio.run(main())
```

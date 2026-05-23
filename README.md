# lmnop:handler

Obsidian-backed FastMCP server over Streamable HTTP.

## Run

Copy `config.yaml.sample` to `~/.config/lmnop-handler/config.yaml`:

```bash
mkdir -p ~/.config/lmnop-handler
cp config.yaml.sample ~/.config/lmnop-handler/config.yaml
```

Environment variables still override file values when needed:

```bash
export LMNOP_HANDLER_PORT=9000
```

Then start the server:

```bash
uv run lmnop-handler
```

## Docker

The container runs both `lmnop-handler` on port `8000` and the KasmVNC desktop on port `8080`.

Build it:

```bash
docker build -t lmnop-handler .
```

Run it:

```bash
mkdir -p ./lmnop-handler/{config,vaults}
docker run --rm \
  -p 8000:8000 \
  -p 8080:8080 \
  -v "$(pwd)/lmnop-handler/config:/config" \
  -v "$(pwd)/lmnop-handler/vaults:/vaults" \
  lmnop-handler
```

Or use Compose:

```bash
docker compose up
```

`compose.yml` pulls `ghcr.io/shyndman/lmnop-handler:latest`, publishes the handler on `8000` and the desktop on `8080`, and stores `/config` and `/vaults` in Docker-managed named volumes. Override the ports with `LMNOP_HANDLER_HTTP_PORT` and `LMNOP_HANDLER_DESKTOP_PORT` if those ports are already in use.

On first start the container seeds `/config/.config/lmnop-handler/config.yaml` from `config.yaml.sample`, rewrites `vault_root` to `/vaults`, copies the baked-in Obsidian app profile into `/config/.config/obsidian`, and seeds `/vaults/.obsidian` with the baked-in vault defaults.

That Obsidian profile is only copied when `/config/.config/obsidian/obsidian.json` is missing. After first boot, the persisted `/config` volume remains the source of truth for app-level Obsidian state.

The vault defaults are only copied when `/vaults/.obsidian` is missing. They reflect the baked-in clean base vault state, including Self-hosted LiveSync already installed and enabled, but without any LiveSync remote configuration.

Authentication is currently disabled. The server accepts unauthenticated MCP requests and ignores any configured bearer token settings.

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
    async with Client("http://127.0.0.1:8000/mcp") as client:
        briefing = await client.read_resource("obsidian://daily-standup")
        print(briefing[0].text)


asyncio.run(main())
```

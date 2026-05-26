from __future__ import annotations

from .application import EnvironmentApplication
from .mcp_api import build_http_middleware, create_mcp

DEFAULT_RUNTIME = EnvironmentApplication()
mcp = create_mcp(DEFAULT_RUNTIME)


def main() -> None:
    settings = DEFAULT_RUNTIME.settings()
    middleware = build_http_middleware(settings)
    print(DEFAULT_RUNTIME.startup_report())
    try:
        create_mcp(DEFAULT_RUNTIME).run(
            transport="http",
            host=settings.host,
            port=settings.port,
            middleware=middleware or None,
        )
    except KeyboardInterrupt:
        return

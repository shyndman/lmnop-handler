from __future__ import annotations

from .server import EnvironmentApplication, create_mcp

DEFAULT_RUNTIME = EnvironmentApplication()
mcp = create_mcp(DEFAULT_RUNTIME)


def main() -> None:
    settings = DEFAULT_RUNTIME.settings()
    print(DEFAULT_RUNTIME.startup_report())
    try:
        create_mcp(DEFAULT_RUNTIME).run(
            transport="http", host=settings.host, port=settings.port
        )
    except KeyboardInterrupt:
        return

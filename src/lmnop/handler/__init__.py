from fastmcp import FastMCP

DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 8000
STANDUP_TAG = "#standup"

mcp = FastMCP("lmnop:handler")


@mcp.tool
def hello(name: str = "world") -> str:
    return f"Hello, {name}!"


def main() -> None:
    mcp.run(transport="http", host=DEFAULT_HOST, port=DEFAULT_PORT)

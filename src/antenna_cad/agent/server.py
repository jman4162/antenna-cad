"""MCP server factory: one shared FastMCP instance, tools registered on first use.

Follows the APAB layout: the singleton is assigned **before** tool modules are
imported, so their module-level ``get_mcp()`` re-enters and receives the
partially-built instance instead of recursing.
"""

from __future__ import annotations

from typing import Any

#: The shared server instance; typed loosely because the class differs between MCP
#: SDK generations (FastMCP in 1.x, MCPServer in 2.x) with the same surface.
_server: Any = None


def _get_server() -> Any:
    global _server
    if _server is not None:
        return _server

    try:
        # SDK 1.x exposes FastMCP; SDK 2.x renamed it to MCPServer with the same
        # constructor and decorator surface.
        try:
            from mcp.server.fastmcp import FastMCP
        except ImportError:
            from mcp.server import MCPServer as FastMCP
    except ImportError as exc:  # pragma: no cover - exercised only without the extra
        raise ImportError(
            "the MCP server needs the 'mcp' extra: pip install antenna-cad[mcp]"
        ) from exc

    _server = FastMCP(
        name="antenna-cad",
        instructions=(
            "antenna-cad: compile antenna design intent into verified KiCad layouts. "
            "Tools cover spec templates, synthesis, board layout, KiCad DRC, openEMS "
            "simulation, the full verification report, and manufacturing export. "
            "Artifacts are returned as file paths, not payloads."
        ),
    )

    import antenna_cad.agent.tools  # noqa: F401  (registers @mcp.tool()s)

    return _server


def get_mcp() -> Any:
    """Return the shared MCP server instance (creating it if needed)."""
    return _get_server()


def run_server(transport: str = "stdio") -> None:
    """Start the MCP server (stdio transport by default)."""
    _get_server().run(transport=transport)

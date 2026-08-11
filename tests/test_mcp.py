"""Tests for the MCP layer (registry, tool behavior, path safety)."""

import asyncio

import pytest

pytest.importorskip("mcp", reason="mcp extra not installed")

from antenna_cad.agent import tools
from antenna_cad.agent.server import get_mcp

EXPECTED_TOOLS = {
    "spec_template",
    "design_synthesize",
    "design_layout",
    "design_drc",
    "design_simulate",
    "design_report",
    "design_export",
}


def test_all_tools_registered():
    server = get_mcp()
    registered = {tool.name for tool in asyncio.run(server.list_tools())}
    assert registered >= EXPECTED_TOOLS


def test_spec_template_and_synthesize(tmp_path):
    spec = tmp_path / "spec.yaml"
    result = asyncio.run(tools.spec_template(str(spec)))
    assert result["status"] == "written"
    result = asyncio.run(tools.design_synthesize(str(spec)))
    assert result["status"] == "ok"
    assert "patch_width" in result["parameters"]
    assert len(result["content_hash"]) == 64


def test_layout_produces_board(tmp_path):
    spec = tmp_path / "spec.yaml"
    asyncio.run(tools.spec_template(str(spec)))
    result = asyncio.run(tools.design_layout(str(spec), str(tmp_path / "out")))
    assert result["status"] == "ok"
    from pathlib import Path

    assert Path(result["board_path"]).exists()


def test_errors_returned_not_raised(tmp_path):
    result = asyncio.run(tools.design_synthesize(str(tmp_path / "missing.yaml")))
    assert result["status"] == "failed"
    assert "error" in result


def test_path_traversal_rejected():
    result = asyncio.run(tools.design_synthesize("../../etc/passwd"))
    assert result["status"] == "failed"
    assert "traversal" in result["error"]


@pytest.mark.kicad
def test_drc_tool(tmp_path):
    from antenna_cad.backends.kicad.cli import find_kicad_cli

    if find_kicad_cli() is None:
        pytest.skip("kicad-cli not installed")
    spec = tmp_path / "spec.yaml"
    asyncio.run(tools.spec_template(str(spec)))
    layout = asyncio.run(tools.design_layout(str(spec), str(tmp_path / "out")))
    result = asyncio.run(tools.design_drc(layout["board_path"]))
    assert result["status"] == "ok"
    assert result["ok"] is True
    assert result["errors"] == 0


def test_validate_path_within_blocks_absolute_escape(tmp_path):
    """Containment is the half traversal-rejection cannot do."""
    from antenna_cad.paths import validate_path_within

    inside = tmp_path / "runs" / "a.txt"
    assert validate_path_within(inside, tmp_path) == inside.resolve()

    with pytest.raises(ValueError, match="escapes root"):
        validate_path_within("/etc/passwd", tmp_path)

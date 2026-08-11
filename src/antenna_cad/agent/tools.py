"""MCP tools: thin wrappers over the deterministic pipeline.

Conventions (matching APAB): flat scalar parameters, every one annotated with a
description; heavy imports inside function bodies; plain dict returns with artifact
paths rather than payloads; errors returned as ``{"error", "status": "failed"}``,
never raised. Path arguments are checked for ``..`` traversal first.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Annotated, Any

from pydantic import Field

from antenna_cad.agent.server import get_mcp

# Shared with any future surface; antenna_cad.paths also carries the
# containment half of the convention, for callers that have a workspace root.
from antenna_cad.paths import reject_path_traversal as _reject_path_traversal

logger = logging.getLogger(__name__)
mcp = get_mcp()


SpecPath = Annotated[str, Field(description="Path to a design spec YAML file")]
OutDir = Annotated[str, Field(description="Output directory for artifacts")]


@mcp.tool()
async def spec_template(
    path: Annotated[str, Field(description="Where to write the starter spec YAML")],
) -> dict[str, Any]:
    """Write a starter design-spec file (single 10 GHz patch; edit to taste)."""
    try:
        from antenna_cad.designspec import write_template

        target = _reject_path_traversal(path)
        if target.exists():
            return {"error": f"{path} already exists", "status": "failed"}
        target.parent.mkdir(parents=True, exist_ok=True)
        write_template(target)
        return {"spec_path": str(target), "status": "written"}
    except Exception as e:
        logger.exception("spec_template failed")
        return {"error": str(e), "status": "failed"}


@mcp.tool()
async def design_synthesize(spec_path: SpecPath) -> dict[str, Any]:
    """Synthesize the design from a spec and report its dimensions and hash."""
    try:
        from antenna_cad.designspec import DesignSpec

        design = DesignSpec.load(_reject_path_traversal(spec_path)).synthesize()
        return {
            "name": design.name,
            "content_hash": design.content_hash(),
            "parameters": dict(design.parameters),
            "status": "ok",
        }
    except Exception as e:
        logger.exception("design_synthesize failed")
        return {"error": str(e), "status": "failed"}


@mcp.tool()
async def design_layout(spec_path: SpecPath, output_dir: OutDir = "build") -> dict[str, Any]:
    """Synthesize and emit the KiCad board plus serialized design IR."""
    try:
        from antenna_cad.backends.kicad.emitter import write_kicad_project
        from antenna_cad.designspec import DesignSpec

        out = _reject_path_traversal(output_dir)
        design = DesignSpec.load(_reject_path_traversal(spec_path)).synthesize()
        out.mkdir(parents=True, exist_ok=True)
        design.to_yaml(out / f"{design.name}.design.yaml")
        board = write_kicad_project(design, out)
        return {
            "board_path": str(board),
            "design_yaml": str(out / f"{design.name}.design.yaml"),
            "content_hash": design.content_hash(),
            "status": "ok",
        }
    except Exception as e:
        logger.exception("design_layout failed")
        return {"error": str(e), "status": "failed"}


@mcp.tool()
async def design_drc(
    board_path: Annotated[str, Field(description="Path to a .kicad_pcb file")],
) -> dict[str, Any]:
    """Run KiCad DRC on an emitted board (requires kicad-cli)."""
    try:
        from antenna_cad.backends.kicad.cli import KicadCli

        report = KicadCli().drc(_reject_path_traversal(board_path))
        return {
            "errors": report.error_count,
            "warnings": report.warning_count,
            "unconnected": len(report.unconnected_items),
            "ok": report.ok,
            "report_path": report.source,
            "status": "ok",
        }
    except Exception as e:
        logger.exception("design_drc failed")
        return {"error": str(e), "status": "failed"}


@mcp.tool()
async def design_simulate(
    spec_path: SpecPath,
    output_dir: OutDir = "build",
    mode: Annotated[str, Field(description="openEMS mode: auto|native|docker")] = "auto",
) -> dict[str, Any]:
    """Run the openEMS FDTD simulation (minutes for a patch, longer for arrays)."""
    try:
        from antenna_cad.designspec import DesignSpec
        from antenna_cad.solvers.openems import OpenEMS

        out = _reject_path_traversal(output_dir)
        design = DesignSpec.load(_reject_path_traversal(spec_path)).synthesize()
        solver = OpenEMS(workdir=out / "runs", mode=mode)  # type: ignore[arg-type]
        result = solver.simulate(design)
        return {"metrics": result.metrics, "solver": result.solver, "status": "ok"}
    except Exception as e:
        logger.exception("design_simulate failed")
        return {"error": str(e), "status": "failed"}


@mcp.tool()
async def design_report(
    spec_path: SpecPath,
    output_dir: OutDir = "build",
    solver_mode: Annotated[str, Field(description="openEMS mode: auto|native|docker|off")] = "auto",
) -> dict[str, Any]:
    """Run the full closed loop (geometry, DRC, simulation) and write report.md."""
    try:
        from antenna_cad.designspec import DesignSpec
        from antenna_cad.report import verify_design

        out = _reject_path_traversal(output_dir)
        design = DesignSpec.load(_reject_path_traversal(spec_path)).synthesize()
        solver = None
        if solver_mode != "off":
            from antenna_cad.solvers.openems import OpenEMS, OpenEMSNotAvailableError

            try:
                solver = OpenEMS(workdir=out / "runs", mode=solver_mode)  # type: ignore[arg-type]
            except OpenEMSNotAvailableError as exc:
                logger.info("simulation unavailable: %s", exc)
        report = verify_design(design, out, solver=solver)
        return {
            "ok": report.ok,
            "steps": {step.name: step.status for step in report.steps},
            "metrics": report.metrics,
            "artifacts": report.artifacts,
            "report_path": str(Path(out, "report.md")),
            "status": "ok",
        }
    except Exception as e:
        logger.exception("design_report failed")
        return {"error": str(e), "status": "failed"}


@mcp.tool()
async def design_export(
    board_path: Annotated[str, Field(description="Path to a .kicad_pcb file")],
    output_dir: OutDir = "build/fab",
    step: Annotated[bool, Field(description="Also export a STEP model")] = False,
) -> dict[str, Any]:
    """Export manufacturing artifacts (Gerbers + drill, optionally STEP)."""
    try:
        from antenna_cad.backends.kicad.cli import KicadCli

        board = _reject_path_traversal(board_path)
        out = _reject_path_traversal(output_dir)
        cli = KicadCli()
        gerber_dir = cli.export_gerbers(board, out / "gerbers")
        cli.export_drill(board, out / "gerbers")
        artifacts = {"gerbers": str(gerber_dir)}
        if step:
            artifacts["step"] = str(cli.export_step(board, out / f"{board.stem}.step"))
        return {"artifacts": artifacts, "status": "ok"}
    except Exception as e:
        logger.exception("design_export failed")
        return {"error": str(e), "status": "failed"}

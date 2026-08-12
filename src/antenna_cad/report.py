"""Verification orchestration and the objective report.

``verify_design`` runs the closed loop on a realized design — geometry checks, KiCad
DRC, EM simulation — and writes a markdown report with plots, the board render, and
provenance, comparing achieved metrics against the requirements.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

from antenna_cad.backends.kicad.cli import KicadCli, KicadCliNotFoundError
from antenna_cad.backends.kicad.emitter import write_kicad_project
from antenna_cad.core.units import to_ghz
from antenna_cad.designspec import AcceptanceCriteria
from antenna_cad.ir import PhysicalDesign
from antenna_cad.solvers.base import EMSolver, SimulationConfig, SimulationResult


class StepOutcome(BaseModel):
    """One verification step: what ran, what it found."""

    model_config = ConfigDict(frozen=True)

    name: str
    status: str  # "pass" | "fail" | "skipped"
    detail: str = ""


class VerificationReport(BaseModel):
    """Everything the closed loop learned about one design revision."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    design_name: str
    design_hash: str
    steps: tuple[StepOutcome, ...]
    metrics: dict[str, float] = {}
    artifacts: dict[str, str] = {}

    @property
    def ok(self) -> bool:
        """True when no step failed."""
        return all(step.status != "fail" for step in self.steps)


def _geometry_checks(design: PhysicalDesign) -> StepOutcome:
    problems: list[str] = []
    for index, shape in enumerate(design.shapes):
        if not shape.polygon.is_valid:
            problems.append(f"shape {index} invalid")
        if not design.board.outline.covers(shape.polygon):
            problems.append(f"shape {index} ({shape.role}) extends beyond the board")
    if problems:
        return StepOutcome(name="geometry", status="fail", detail="; ".join(problems))
    return StepOutcome(
        name="geometry", status="pass", detail=f"{len(design.shapes)} shapes inside outline"
    )


def plot_s11(result: SimulationResult, path: Path) -> None:
    """Write the |S11| sweep plot for a simulation result."""
    import matplotlib as mpl

    mpl.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    f = np.asarray(result.s_parameters["frequency"]) / 1e9
    s11_db = np.asarray(result.s11_db())
    fig, ax = plt.subplots(figsize=(6, 4))
    ax.plot(f, s11_db)
    ax.axhline(-10, color="gray", linestyle="--", linewidth=1)
    ax.set_xlabel("Frequency (GHz)")
    ax.set_ylabel("|S11| (dB)")
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def plot_pattern(result: SimulationResult, path: Path) -> None:
    """Write normalized far-field pattern cuts for a simulation result."""
    import matplotlib as mpl

    mpl.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    ff = result.far_field
    theta = np.asarray(ff["theta"])
    fig, ax = plt.subplots(figsize=(6, 4))
    for phi in np.asarray(ff["phi"]):
        e = np.asarray(ff["e_norm"].sel(phi=phi))
        e_db = 20 * np.log10(np.maximum(e, 1e-4))
        ax.plot(theta, e_db, label=f"phi = {phi:g} deg")
    ax.set_xlabel("Theta (deg)")
    ax.set_ylabel("Normalized pattern (dB)")
    ax.set_ylim(-40, 2)
    ax.legend()
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def verify_design(
    design: PhysicalDesign,
    output_dir: str | Path,
    drc: bool = True,
    solver: EMSolver | None = None,
    sim_config: SimulationConfig | None = None,
    acceptance: AcceptanceCriteria | None = None,
) -> VerificationReport:
    """Run the closed verification loop and write ``report.md`` plus artifacts.

    Steps that cannot run (missing kicad-cli, no solver given) are reported as
    skipped, never silently dropped.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    steps: list[StepOutcome] = [_geometry_checks(design)]
    metrics: dict[str, float] = {}
    artifacts: dict[str, str] = {}

    board_path = write_kicad_project(design, output_dir)
    artifacts["kicad_pcb"] = str(board_path)

    if drc:
        try:
            cli = KicadCli()
            drc_report = cli.drc(board_path)
            artifacts["drc_json"] = drc_report.source
            status = "pass" if drc_report.ok else "fail"
            steps.append(StepOutcome(name="kicad_drc", status=status, detail=drc_report.summary()))
            render_path = output_dir / "board_top.png"
            cli.render(board_path, render_path)
            artifacts["board_render"] = str(render_path)
        except KicadCliNotFoundError as exc:
            steps.append(StepOutcome(name="kicad_drc", status="skipped", detail=str(exc)))
    else:
        steps.append(StepOutcome(name="kicad_drc", status="skipped", detail="disabled"))

    if solver is not None:
        criteria = acceptance or AcceptanceCriteria()
        result = solver.simulate(design, sim_config)
        metrics.update(result.metrics)
        f0 = to_ghz(design.frequency)
        f_res = metrics.get("f_res_hz", 0.0) / 1e9
        error = abs(f_res - f0) / f0 if f0 else 1.0
        detail = (
            f"f_res = {f_res:.3f} GHz (target {f0:g} GHz, {error:.1%} off), "
            f"S11 min = {metrics.get('s11_min_db', 0):.1f} dB"
        )
        passed = (
            error < criteria.freq_tolerance and metrics.get("s11_min_db", 0) < criteria.s11_max_db
        )
        steps.append(
            StepOutcome(
                name="em_simulation",
                status="pass" if passed else "fail",
                detail=detail,
            )
        )
        s11_path = output_dir / "s11.png"
        plot_s11(result, s11_path)
        artifacts["s11_plot"] = str(s11_path)
        if result.far_field is not None:
            pattern_path = output_dir / "pattern.png"
            plot_pattern(result, pattern_path)
            artifacts["pattern_plot"] = str(pattern_path)
    else:
        steps.append(StepOutcome(name="em_simulation", status="skipped", detail="no solver"))

    report = VerificationReport(
        design_name=design.name,
        design_hash=design.content_hash(),
        steps=tuple(steps),
        metrics=metrics,
        artifacts=artifacts,
    )
    (output_dir / "report.md").write_text(render_markdown(report, design))
    return report


def render_markdown(report: VerificationReport, design: PhysicalDesign) -> str:
    """Render the verification report as markdown."""
    lines = [
        f"# Verification report: {report.design_name}",
        "",
        f"- design hash: `{report.design_hash[:16]}`",
        f"- center frequency: {to_ghz(design.frequency):g} GHz",
        f"- overall: **{'PASS' if report.ok else 'FAIL'}**",
        "",
        "## Steps",
        "",
        "| step | status | detail |",
        "|------|--------|--------|",
    ]
    lines += [f"| {s.name} | {s.status} | {s.detail} |" for s in report.steps]
    if report.metrics:
        lines += ["", "## Metrics", ""]
        lines += [f"- {key}: {value:.6g}" for key, value in sorted(report.metrics.items())]
    if report.artifacts:
        lines += ["", "## Artifacts", ""]
        lines += [f"- {name}: `{path}`" for name, path in sorted(report.artifacts.items())]
    params: dict[str, Any] = dict(design.parameters)
    if params:
        lines += ["", "## Synthesis parameters", ""]
        lines += [f"- {key}: {value}" for key, value in sorted(params.items())]
    lines += [""]
    return "\n".join(lines)

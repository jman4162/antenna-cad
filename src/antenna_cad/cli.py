"""Command line interface: spec file in, verified board out."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

app = typer.Typer(
    name="antenna-cad",
    help="Compile antenna design intent into verified KiCad layouts.",
    no_args_is_help=True,
    pretty_exceptions_show_locals=False,
)

SpecArg = Annotated[Path, typer.Argument(help="Design spec YAML file")]
OutOpt = Annotated[Path, typer.Option("--output", "-o", help="Output directory")]


@app.command()
def new(path: Annotated[Path, typer.Argument(help="Spec file to create")]) -> None:
    """Write a starter design spec."""
    from antenna_cad.designspec import write_template

    if path.exists():
        typer.echo(f"refusing to overwrite existing {path}", err=True)
        raise typer.Exit(1)
    write_template(path)
    typer.echo(f"wrote {path}")


@app.command()
def synthesize(spec: SpecArg, output: OutOpt = Path("build")) -> None:
    """Synthesize the design and write the serialized IR (design.yaml)."""
    from antenna_cad.designspec import DesignSpec

    design = DesignSpec.load(spec).synthesize()
    output.mkdir(parents=True, exist_ok=True)
    out_path = output / f"{design.name}.design.yaml"
    design.to_yaml(out_path)
    typer.echo(f"synthesized {design.name} (hash {design.content_hash()[:12]}) -> {out_path}")
    for key, value in sorted(design.parameters.items()):
        typer.echo(f"  {key}: {value}")


@app.command()
def layout(spec: SpecArg, output: OutOpt = Path("build")) -> None:
    """Synthesize and emit the KiCad board (plus IR)."""
    from antenna_cad.backends.kicad.emitter import write_kicad_project
    from antenna_cad.designspec import DesignSpec

    design = DesignSpec.load(spec).synthesize()
    output.mkdir(parents=True, exist_ok=True)
    design.to_yaml(output / f"{design.name}.design.yaml")
    board = write_kicad_project(design, output)
    typer.echo(f"wrote {board}")


@app.command()
def drc(board: Annotated[Path, typer.Argument(help="A .kicad_pcb file")]) -> None:
    """Run KiCad DRC on an emitted board."""
    from antenna_cad.backends.kicad.cli import KicadCli

    report = KicadCli().drc(board)
    typer.echo(report.summary())
    raise typer.Exit(0 if report.ok else 1)


@app.command()
def simulate(
    spec: SpecArg,
    output: OutOpt = Path("build"),
    mode: Annotated[str, typer.Option(help="openEMS mode: auto|native|docker")] = "auto",
) -> None:
    """Synthesize and run the openEMS simulation."""
    from antenna_cad.designspec import DesignSpec
    from antenna_cad.solvers.openems import OpenEMS

    design = DesignSpec.load(spec).synthesize()
    solver = OpenEMS(workdir=output / "runs", mode=mode)  # type: ignore[arg-type]
    result = solver.simulate(design)
    for key, value in sorted(result.metrics.items()):
        typer.echo(f"{key}: {value:.6g}")


@app.command()
def report(
    spec: SpecArg,
    output: OutOpt = Path("build"),
    solver_mode: Annotated[str, typer.Option(help="openEMS mode: auto|native|docker|off")] = "auto",
) -> None:
    """Run the full closed loop: synthesize, DRC, simulate, report."""
    from antenna_cad.designspec import DesignSpec
    from antenna_cad.report import verify_design

    design = DesignSpec.load(spec).synthesize()
    solver = None
    if solver_mode != "off":
        from antenna_cad.solvers.openems import OpenEMS, OpenEMSNotAvailableError

        try:
            solver = OpenEMS(workdir=output / "runs", mode=solver_mode)  # type: ignore[arg-type]
        except OpenEMSNotAvailableError as exc:
            typer.echo(f"simulation skipped: {exc}", err=True)
    design.to_yaml(output / f"{design.name}.design.yaml")
    result = verify_design(design, output, solver=solver)
    typer.echo(Path(output, "report.md").read_text())
    raise typer.Exit(0 if result.ok else 1)


@app.command()
def export(
    board: Annotated[Path, typer.Argument(help="A .kicad_pcb file")],
    output: OutOpt = Path("build/fab"),
    gerbers: Annotated[bool, typer.Option(help="Export Gerbers + drill")] = True,
    step: Annotated[bool, typer.Option(help="Export STEP model")] = False,
) -> None:
    """Export manufacturing artifacts from an emitted board."""
    from antenna_cad.backends.kicad.cli import KicadCli

    cli = KicadCli()
    if gerbers:
        cli.export_gerbers(board, output / "gerbers")
        cli.export_drill(board, output / "gerbers")
        typer.echo(f"gerbers + drill -> {output / 'gerbers'}")
    if step:
        cli.export_step(board, output / f"{board.stem}.step")
        typer.echo(f"step -> {output / f'{board.stem}.step'}")


if __name__ == "__main__":
    app()

#!/usr/bin/env python
"""Regenerate the README and documentation figures.

    uv run python figures/make_figures.py            # write PNGs into docs/images/
    uv run python figures/make_figures.py --check    # verify they still build

Every figure is real output from the public API rather than a mock-up: board images
come from synthesizing the example specs and rendering the emitted KiCad boards with
``kicad-cli render``, and the S11/pattern plots are replotted from committed
simulation data in ``figures/data/*.npz`` (one verified openEMS run each, kept in
the repo so the plots rebuild without a solver install).

Renders need a local kicad-cli; when it is missing the script keeps the committed
board images and says so. matplotlib output is deterministic on one machine but not
across platforms (freetype rasterization differs), so ``--check`` verifies figures
build and are non-trivial rather than byte-comparing.
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "images"
DATA = ROOT / "figures" / "data"

SPECS = {
    "patch": ROOT / "examples" / "patch_10ghz" / "spec.yaml",
    "array_2x2": ROOT / "examples" / "array_2x2_10ghz" / "spec.yaml",
    "array_4x4": ROOT / "examples" / "array_4x4_10ghz" / "spec.yaml",
}


def make_renders(check: bool) -> list[str]:
    """Render each example board to ``<name>_top.png`` via kicad-cli."""
    from antenna_cad.backends.kicad.cli import KicadCli, KicadCliNotFoundError
    from antenna_cad.backends.kicad.emitter import write_kicad_project
    from antenna_cad.designspec import DesignSpec

    problems: list[str] = []
    try:
        cli = KicadCli()
    except KicadCliNotFoundError:
        message = "kicad-cli not found: board renders not regenerated"
        print(f"  [skip] {message}")
        if check:
            problems.append(message)
        return problems

    for name, spec in SPECS.items():
        design = DesignSpec.load(spec).synthesize()
        with tempfile.TemporaryDirectory() as tmp:
            board = write_kicad_project(design, tmp)
            target = OUT / f"{name}_top.png"
            cli.render(board, target)
            print(f"  wrote {target.relative_to(ROOT)}")
    return problems


def make_plots() -> None:
    """Replot S11 and pattern figures from the committed run data."""
    from antenna_cad.report import plot_pattern, plot_s11
    from antenna_cad.solvers.openems.solver import result_from_npz

    for name in SPECS:
        npz = DATA / f"{name}_results.npz"
        if not npz.exists():
            raise SystemExit(f"missing committed run data: {npz}")
        result = result_from_npz(npz)
        plot_s11(result, OUT / f"{name}_s11.png")
        plot_pattern(result, OUT / f"{name}_pattern.png")
        print(f"  wrote {name}_s11.png, {name}_pattern.png (docs/images/)")


def main() -> int:
    """Build all figures; with --check, fail on empty or missing output."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="verify figures build")
    args = parser.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    problems = make_renders(check=args.check)
    make_plots()

    if args.check:
        for png in sorted(OUT.glob("*.png")):
            if png.stat().st_size < 1000:
                problems.append(f"{png} is suspiciously small")
        if problems:
            print("FAIL:", "; ".join(problems))
            return 1
        print("all figures build")
    return 0


if __name__ == "__main__":
    sys.exit(main())

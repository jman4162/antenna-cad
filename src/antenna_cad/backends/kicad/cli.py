"""Wrappers around ``kicad-cli`` for headless DRC and manufacturing export.

Every method shells out to the KiCad 8+ command line tool; nothing here needs the
KiCad GUI. When ``kicad-cli`` is missing the constructor raises with install
guidance, so callers can degrade gracefully (tests skip, ``verify()`` reports the
step as skipped).
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

#: Locations searched after PATH, covering macOS app bundle installs (system and
#: per-user Applications folders).
_EXTRA_PATHS = (
    "/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli",
    str(Path.home() / "Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli"),
    "/usr/local/bin/kicad-cli",
)


class KicadCliNotFoundError(RuntimeError):
    """``kicad-cli`` is not installed or not on PATH."""

    def __init__(self) -> None:
        super().__init__(
            "kicad-cli not found. Install KiCad 8+ (macOS: `brew install --cask kicad`; "
            "Linux: distribution package `kicad`) or add kicad-cli to PATH."
        )


def find_kicad_cli() -> str | None:
    """Locate the ``kicad-cli`` executable, or return ``None``."""
    found = shutil.which("kicad-cli")
    if found:
        return found
    for candidate in _EXTRA_PATHS:
        if Path(candidate).is_file():
            return candidate
    return None


@dataclass(frozen=True)
class DrcReport:
    """Parsed result of ``kicad-cli pcb drc --format json``."""

    violations: list[dict[str, object]] = field(default_factory=list)
    unconnected_items: list[dict[str, object]] = field(default_factory=list)
    source: str = ""

    @property
    def error_count(self) -> int:
        """Number of violations with error severity."""
        return sum(1 for v in self.violations if v.get("severity") == "error")

    @property
    def warning_count(self) -> int:
        """Number of violations with warning severity."""
        return sum(1 for v in self.violations if v.get("severity") == "warning")

    @property
    def ok(self) -> bool:
        """True when there are no errors and nothing is unconnected."""
        return self.error_count == 0 and not self.unconnected_items

    def summary(self) -> str:
        """One-line human summary."""
        return (
            f"DRC: {self.error_count} error(s), {self.warning_count} warning(s), "
            f"{len(self.unconnected_items)} unconnected item(s)"
        )


class KicadCli:
    """Thin wrapper over one located ``kicad-cli`` executable."""

    def __init__(self, executable: str | None = None) -> None:
        exe = executable or find_kicad_cli()
        if exe is None:
            raise KicadCliNotFoundError
        self.executable = exe

    def _run(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run([self.executable, *args], capture_output=True, text=True, check=False)

    def version(self) -> str:
        """KiCad version string."""
        return self._run("version").stdout.strip()

    def drc(self, board: str | Path, report_path: str | Path | None = None) -> DrcReport:
        """Run design-rule checks on a board file and parse the JSON report."""
        board = Path(board)
        report_file = Path(report_path) if report_path else board.with_suffix(".drc.json")
        result = self._run(
            "pcb",
            "drc",
            "--format",
            "json",
            "--output",
            str(report_file),
            "--severity-all",
            str(board),
        )
        if not report_file.exists():
            raise RuntimeError(
                f"kicad-cli drc produced no report (exit {result.returncode}): "
                f"{result.stderr.strip() or result.stdout.strip()}"
            )
        data = json.loads(report_file.read_text())
        return DrcReport(
            violations=data.get("violations", []),
            unconnected_items=data.get("unconnected_items", []),
            source=str(report_file),
        )

    def export_gerbers(self, board: str | Path, directory: str | Path) -> Path:
        """Export Gerbers (all used layers) into ``directory``."""
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        result = self._run("pcb", "export", "gerbers", "--output", f"{directory}/", str(board))
        if result.returncode != 0:
            raise RuntimeError(f"gerber export failed: {result.stderr.strip()}")
        return directory

    def export_drill(self, board: str | Path, directory: str | Path) -> Path:
        """Export Excellon drill files into ``directory``."""
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        result = self._run("pcb", "export", "drill", "--output", f"{directory}/", str(board))
        if result.returncode != 0:
            raise RuntimeError(f"drill export failed: {result.stderr.strip()}")
        return directory

    def export_step(self, board: str | Path, output: str | Path) -> Path:
        """Export a STEP model of the board."""
        result = self._run("pcb", "export", "step", "--force", "--output", str(output), str(board))
        if result.returncode != 0:
            raise RuntimeError(f"step export failed: {result.stderr.strip()}")
        return Path(output)

    def render(self, board: str | Path, output: str | Path, side: str = "top") -> Path:
        """Render a raytraced PNG image of the board."""
        result = self._run("pcb", "render", "--side", side, "--output", str(output), str(board))
        if result.returncode != 0:
            raise RuntimeError(f"render failed: {result.stderr.strip()}")
        return Path(output)

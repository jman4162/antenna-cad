"""The openEMS solver backend: spec out, runner in, results back as xarray.

Execution modes (``mode="auto"`` picks the first available):

- **native**: the openEMS Python bindings are importable in this interpreter,
- **docker**: the ``antenna-cad-openems`` image runs the same runner script with the
  run directory bind-mounted.

Install notes live in ``docker/Dockerfile``; there is no pip package for openEMS.
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Literal

from antenna_cad.ir import PhysicalDesign
from antenna_cad.solvers.base import SimulationConfig, SimulationResult
from antenna_cad.solvers.openems.spec import build_spec

DOCKER_IMAGE = "antenna-cad-openems"


class OpenEMSNotAvailableError(RuntimeError):
    """Neither native openEMS bindings nor the Docker runner image is available."""

    def __init__(self) -> None:
        super().__init__(
            "openEMS is not available. Either install the Python bindings natively "
            "(https://docs.openems.de/python/install.html; macOS: vinn-ie/openems tap) "
            "or build the Docker runner: docker build -t antenna-cad-openems docker/"
        )


def _native_available() -> bool:
    return (
        importlib.util.find_spec("openEMS") is not None
        and importlib.util.find_spec("CSXCAD") is not None
    )


def _docker_available() -> bool:
    docker = shutil.which("docker")
    if docker is None:
        return False
    # `docker image ls` rather than `image inspect`: some daemons (containerd image
    # store) reject inspect-by-name for locally built images.
    probe = subprocess.run(
        [docker, "image", "ls", DOCKER_IMAGE, "--format", "{{.Repository}}"],
        capture_output=True,
        text=True,
        check=False,
    )
    return probe.returncode == 0 and DOCKER_IMAGE in probe.stdout


class OpenEMS:
    """FDTD simulation of a design via openEMS."""

    def __init__(
        self,
        workdir: str | Path = "runs",
        mode: Literal["auto", "native", "docker"] = "auto",
    ) -> None:
        self.workdir = Path(workdir)
        if mode == "auto":
            if _native_available():
                mode = "native"
            elif _docker_available():
                mode = "docker"
            else:
                raise OpenEMSNotAvailableError
        self.mode: Literal["native", "docker"] = mode

    def prepare(self, design: PhysicalDesign, config: SimulationConfig) -> Path:
        """Write spec + runner into a fresh run directory; return that directory."""
        run_dir = self.workdir / f"{design.name}-{design.content_hash()[:12]}"
        run_dir.mkdir(parents=True, exist_ok=True)
        spec = build_spec(design, config)
        (run_dir / "spec.json").write_text(json.dumps(spec, indent=2))
        runner_src = Path(__file__).with_name("_runner.py")
        shutil.copyfile(runner_src, run_dir / "run_openems.py")
        return run_dir

    def _execute(self, run_dir: Path) -> None:
        if self.mode == "native":
            command = [sys.executable, "run_openems.py", "spec.json"]
        else:
            command = [
                "docker",
                "run",
                "--rm",
                "-v",
                f"{run_dir.resolve()}:/sim",
                DOCKER_IMAGE,
                "run_openems.py",
                "spec.json",
            ]
        result = subprocess.run(command, cwd=run_dir, capture_output=True, text=True, check=False)
        (run_dir / "run.log").write_text(result.stdout + "\n" + result.stderr)
        if result.returncode != 0:
            tail = "\n".join((result.stderr or result.stdout).splitlines()[-15:])
            raise RuntimeError(
                f"openEMS run failed (exit {result.returncode}, mode={self.mode}); "
                f"log: {run_dir / 'run.log'}\n{tail}"
            )

    def simulate(
        self, design: PhysicalDesign, config: SimulationConfig | None = None
    ) -> SimulationResult:
        """Run the FDTD simulation and package results."""
        config = config or SimulationConfig()
        run_dir = self.prepare(design, config)
        self._execute(run_dir)
        return self.load_results(run_dir)

    def load_results(self, run_dir: str | Path) -> SimulationResult:
        """Parse a completed run directory into a :class:`SimulationResult`."""
        import numpy as np
        import xarray as xr

        data = np.load(Path(run_dir) / "results.npz")
        f = data["f"]
        s11 = data["s11"]
        s_parameters = xr.Dataset(
            {"s11": ("frequency", s11), "zin": ("frequency", data["zin"])},
            coords={"frequency": f},
        )

        s11_db = 20 * np.log10(np.abs(s11))
        idx = int(np.argmin(s11_db))
        metrics: dict[str, float] = {
            "f_res_hz": float(data["f_res"]),
            "s11_min_db": float(s11_db[idx]),
        }
        below = f[s11_db <= -10.0]
        if below.size:
            metrics["bandwidth_10db_hz"] = float(below.max() - below.min())

        far_field = None
        if "e_norm" in data:
            far_field = xr.Dataset(
                {"e_norm": (("theta", "phi"), data["e_norm"])},
                coords={"theta": data["theta_deg"], "phi": data["phi_deg"]},
                attrs={"Dmax": float(data["dmax"]), "Prad": float(data["prad"])},
            )
            dmax = float(data["dmax"])
            metrics["directivity_dbi"] = float(10 * np.log10(dmax))
            if "p_acc" in data and data["prad"] > 0:
                efficiency = float(data["prad"]) / float(data["p_acc"])
                # Numerical noise can push efficiency epsilon over 1 for lossless models.
                efficiency = min(efficiency, 1.0)
                metrics["gain_dbi"] = float(10 * np.log10(dmax * efficiency))

        return SimulationResult(
            s_parameters=s_parameters,
            far_field=far_field,
            metrics=metrics,
            solver={"name": "openEMS", "mode": self.mode},
        )

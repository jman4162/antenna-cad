"""Measured-data solver: bench data flowing through the verify/report path.

A ``MeasuredSolver`` satisfies the :class:`~antenna_cad.solvers.base.EMSolver`
protocol but reads a Touchstone file instead of running a field solver, so a
measured board flows through exactly the same ``verify_design`` gate as a
simulation. The file must satisfy the measurement artifact contract: a
``<name>.meta.yaml`` provenance sidecar (instrument, date, calibration
state, uncertainty, operator, synthetic) is required and is carried into
``SimulationResult.solver``.

Touchstone parsing uses scikit-rf (already a project dependency), imported
lazily so plain ``import antenna_cad`` stays light.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from antenna_cad.solvers.base import SimulationConfig, SimulationResult

if TYPE_CHECKING:
    from antenna_cad.ir import PhysicalDesign

_REQUIRED_SIDECAR_KEYS = (
    "instrument",
    "date",
    "calibration_state",
    "uncertainty",
    "operator",
    "synthetic",
)


class MeasurementContractError(ValueError):
    """The dataset does not satisfy the measurement artifact contract."""


def load_sidecar(data_path: str | Path) -> dict[str, Any]:
    """Load and validate the ``<name>.meta.yaml`` provenance sidecar."""
    import yaml

    data_path = Path(data_path)
    sidecar = data_path.with_name(data_path.stem + ".meta.yaml")
    if not sidecar.exists():
        raise MeasurementContractError(
            f"no provenance sidecar {sidecar.name} next to {data_path.name}; "
            "measured datasets require one (see the measurement artifact contract)"
        )
    raw = yaml.safe_load(sidecar.read_text()) or {}
    missing = [k for k in _REQUIRED_SIDECAR_KEYS if k not in raw]
    if missing:
        raise MeasurementContractError(
            f"{sidecar.name} is missing required provenance keys: {missing}"
        )
    if not isinstance(raw["synthetic"], bool):
        raise MeasurementContractError(f"{sidecar.name}: 'synthetic' must be a boolean")
    return dict(raw)


class MeasuredSolver:
    """EMSolver backed by a measured (or synthetic) Touchstone file.

    The design and simulation config are accepted for protocol
    compatibility and ignored: the data is whatever the bench produced.
    Pair it with ``verify_design`` to score a fabricated board against
    the same acceptance criteria a simulation faces. Tuning against a
    MeasuredSolver is meaningless (the data cannot change) and the CLI
    refuses the combination.
    """

    def __init__(self, touchstone: str | Path) -> None:
        self._path = Path(touchstone)
        if not self._path.exists():
            raise FileNotFoundError(self._path)
        self.provenance = load_sidecar(self._path)

    def simulate(
        self,
        design: PhysicalDesign,  # noqa: ARG002 - protocol arg; data is fixed
        config: SimulationConfig | None = None,  # noqa: ARG002
    ) -> SimulationResult:
        """Load the measured S-parameters as a :class:`SimulationResult`."""
        import numpy as np
        import skrf
        import xarray as xr

        network = skrf.Network(str(self._path))
        f = np.asarray(network.f, dtype=float)
        s11 = network.s[:, 0, 0]
        zin = network.z[:, 0, 0]

        s_parameters = xr.Dataset(
            {"s11": ("frequency", s11), "zin": ("frequency", zin)},
            coords={"frequency": f},
        )

        s11_db = 20 * np.log10(np.maximum(np.abs(s11), 1e-10))
        res_idx = int(np.argmin(s11_db))
        metrics: dict[str, float] = {
            "f_res_hz": float(f[res_idx]),
            "s11_min_db": float(s11_db[res_idx]),
        }
        below = s11_db <= -10.0
        if below[res_idx]:
            lo = res_idx
            while lo > 0 and below[lo - 1]:
                lo -= 1
            hi = res_idx
            while hi < len(f) - 1 and below[hi + 1]:
                hi += 1
            metrics["bandwidth_10db_hz"] = float(f[hi] - f[lo])

        solver_info = {
            "name": "measured",
            "source": str(self._path),
            "synthetic": str(self.provenance["synthetic"]).lower(),
            "instrument": str(self.provenance["instrument"]),
            "date": str(self.provenance["date"]),
        }
        return SimulationResult(
            s_parameters=s_parameters,
            far_field=None,
            metrics=metrics,
            solver=solver_info,
        )

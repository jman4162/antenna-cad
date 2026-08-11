"""Solver-neutral simulation interface.

Any full-wave backend (openEMS today; EdgeFEM, Palace later) implements
:class:`EMSolver`: a design and a config in, a :class:`SimulationResult` out.
Results use xarray so dimensions (frequency, angle) stay labeled end to end.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict

if TYPE_CHECKING:
    import xarray as xr

    from antenna_cad.ir import PhysicalDesign


class SimulationConfig(BaseModel):
    """Common simulation controls; backends may interpret or extend them.

    Frequencies are in hertz (floats, since this crosses a JSON boundary); ``None``
    for the sweep edges means 0.6/1.4 times the design frequency.
    """

    model_config = ConfigDict(frozen=True)

    f_start: float | None = None
    f_stop: float | None = None
    n_freq: int = 401
    end_criteria: float = 1e-4
    max_timesteps: int = 40000
    boundaries: tuple[str, str, str, str, str, str] = ("MUR",) * 6
    threads: int = 0  # 0 = solver default
    theta_step_deg: float = 2.0
    phi_cuts_deg: tuple[float, ...] = (0.0, 90.0)


class SimulationResult(BaseModel):
    """Uniform result container returned by every solver backend."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    #: ``s11`` over ``frequency`` (complex), as an xarray Dataset.
    s_parameters: Any
    #: Normalized far-field magnitude over ``theta``/``phi`` at the resonant
    #: frequency, with ``Dmax``/``Prad`` attributes; ``None`` if not computed.
    far_field: Any = None
    #: Scalar summary metrics (f_res_hz, s11_min_db, bandwidth_hz, directivity_dbi, ...).
    metrics: dict[str, float] = {}
    #: Backend name and version information.
    solver: dict[str, str] = {}

    def s11_db(self) -> xr.DataArray:
        """Return |S11| in dB over frequency."""
        import numpy as np

        s11 = self.s_parameters["s11"]
        return 20 * np.log10(abs(s11))  # type: ignore[no-any-return]


@runtime_checkable
class EMSolver(Protocol):
    """The one protocol every solver backend satisfies."""

    def simulate(
        self, design: PhysicalDesign, config: SimulationConfig | None = None
    ) -> SimulationResult:
        """Run a full simulation of the design and return uniform results."""
        ...

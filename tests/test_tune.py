"""Unit tests for the simulation-feedback tuning step (no solver required)."""

import numpy as np
import xarray as xr

from antenna_cad import DesignProblem
from antenna_cad.core.units import to_mm
from antenna_cad.elements import RectangularPatch
from antenna_cad.solvers.base import SimulationResult
from antenna_cad.tune import _corrected


def _fake_result(f_res_hz: float, r_at_res: float) -> SimulationResult:
    f = np.linspace(6e9, 14e9, 401)
    zin = np.full_like(f, r_at_res, dtype=complex)
    s11 = np.full_like(f, 0.5, dtype=complex)
    ds = xr.Dataset(
        {"s11": ("frequency", s11), "zin": ("frequency", zin)},
        coords={"frequency": f},
    )
    return SimulationResult(
        s_parameters=ds,
        metrics={"f_res_hz": f_res_hz, "s11_min_db": -5.0},
    )


def test_low_resonance_shrinks_length():
    patch = RectangularPatch.synthesize(DesignProblem(center_frequency="10 GHz"))
    corrected = _corrected(patch, _fake_result(9.5e9, 50.0))
    assert to_mm(corrected.length) < to_mm(patch.length)
    assert to_mm(corrected.length) / to_mm(patch.length) == 0.95


def test_low_resistance_shrinks_inset():
    patch = RectangularPatch.synthesize(DesignProblem(center_frequency="10 GHz"))
    corrected = _corrected(patch, _fake_result(10e9, 15.0))
    # Measured R below 50 means the taper cut too deep; the inset must retreat.
    assert to_mm(corrected.inset) < to_mm(patch.inset)


def test_corrected_design_still_validates():
    patch = RectangularPatch.synthesize(DesignProblem(center_frequency="10 GHz"))
    corrected = _corrected(patch, _fake_result(9.6e9, 20.0))
    design = corrected.to_design()
    assert design.content_hash()

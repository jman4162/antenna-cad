"""Simulation-feedback tuning: close the loop between analytic synthesis and FDTD.

Analytic patch models land within a few percent on resonance and within tens of ohms
on input resistance. One or two corrective iterations against the real solver close
that gap deterministically:

- resonance scales with patch length, so ``L' = L * (f_res / f_target)``;
- the measured input resistance at resonance recalibrates the effective edge
  resistance of the inset taper, giving a corrected inset depth.

No general optimizer here — that comes later; this is the minimal engine-grounded
correction the closed loop supports.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, ConfigDict

from antenna_cad.core.units import Quantity, to_hz, to_mm, to_ohm
from antenna_cad.elements.patch import RectangularPatch
from antenna_cad.solvers.base import EMSolver, SimulationConfig, SimulationResult


class TuneStep(BaseModel):
    """Record of one tuning iteration."""

    model_config = ConfigDict(frozen=True)

    iteration: int
    f_res_hz: float
    s11_min_db: float
    patch_length_mm: float
    inset_mm: float


class TuneOutcome(BaseModel):
    """Final tuned patch plus the iteration history."""

    model_config = ConfigDict(frozen=True)

    patch: RectangularPatch
    result: SimulationResult
    steps: tuple[TuneStep, ...]

    @property
    def converged(self) -> bool:
        """True when the last step met the frequency and match targets."""
        last = self.steps[-1]
        target = to_hz(self.patch.problem.center_frequency)
        return abs(last.f_res_hz - target) / target < 0.02 and last.s11_min_db < -10


def _corrected(
    patch: RectangularPatch, result: SimulationResult, adjust_inset: bool = True
) -> RectangularPatch:
    """One corrective step from measured resonance and (optionally) input resistance.

    ``adjust_inset=False`` limits the correction to frequency scaling — right for
    arrays, where the port sees the feed network rather than the raw patch
    resistance.
    """
    import numpy as np

    problem = patch.problem
    f_target = to_hz(problem.center_frequency)
    f_res = result.metrics["f_res_hz"]

    # Damped correction: clip the per-iteration scale so one misidentified dip
    # cannot fling the geometry far from the analytic starting point.
    scale = min(max(f_res / f_target, 0.95), 1.05)
    length_mm = to_mm(patch.length) * scale
    inset_mm = to_mm(patch.inset) * scale  # keep relative position first

    if not adjust_inset:
        return patch.model_copy(
            update={
                "length": Quantity(length_mm, "mm"),
                "inset": Quantity(inset_mm, "mm"),
            }
        )

    zin = result.s_parameters["zin"]
    freq = result.s_parameters["frequency"]
    r_meas = float(np.real(np.asarray(zin)[int(np.argmin(np.abs(np.asarray(freq) - f_res)))]))
    taper = math.cos(math.pi * inset_mm / length_mm) ** 4
    if r_meas > 1 and taper > 1e-3:
        r_edge_eff = r_meas / taper
        target_r = to_ohm(problem.impedance)
        if target_r < r_edge_eff:
            ratio = (target_r / r_edge_eff) ** 0.25
            inset_mm = length_mm / math.pi * math.acos(ratio)

    return patch.model_copy(
        update={
            "length": Quantity(length_mm, "mm"),
            "inset": Quantity(inset_mm, "mm"),
        }
    )


def tune_patch(
    patch: RectangularPatch,
    solver: EMSolver,
    config: SimulationConfig | None = None,
    max_iterations: int = 3,
    realize: Callable[[RectangularPatch], Any] | None = None,
    adjust_inset: bool = True,
) -> TuneOutcome:
    """Iterate simulate-and-correct until the design meets frequency and match targets.

    ``realize`` maps the patch to the design under test (defaults to the single-patch
    board); pass an array builder to tune a whole array by uniform element scaling,
    with ``adjust_inset=False``.
    """
    config = config or SimulationConfig()
    if realize is None:
        realize = lambda p: p.to_design()
    steps: list[TuneStep] = []
    current = patch
    result = solver.simulate(realize(current), config)
    # Ranked (unmatched?, frequency error): a matched iterate always beats an
    # unmatched one, then closer-to-target wins.
    best: tuple[tuple[bool, float], RectangularPatch, SimulationResult] = (
        (True, float("inf")),
        current,
        result,
    )
    while True:
        steps.append(
            TuneStep(
                iteration=len(steps),
                f_res_hz=result.metrics["f_res_hz"],
                s11_min_db=result.metrics["s11_min_db"],
                patch_length_mm=to_mm(current.length),
                inset_mm=to_mm(current.inset),
            )
        )
        f_target = to_hz(current.problem.center_frequency)
        error = abs(result.metrics["f_res_hz"] - f_target) / f_target
        matched = result.metrics["s11_min_db"] < -10
        score = (not matched, error)
        if score < best[0]:
            best = (score, current, result)
        if (error < 0.02 and matched) or len(steps) > max_iterations:
            break
        if len(steps) >= 2:
            previous_error = abs(steps[-2].f_res_hz - f_target) / f_target
            if error >= previous_error:
                break  # correction is not converging; keep the best iterate
        current = _corrected(current, result, adjust_inset=adjust_inset)
        result = solver.simulate(realize(current), config)

    _, best_patch, best_result = best
    return TuneOutcome(patch=best_patch, result=best_result, steps=tuple(steps))

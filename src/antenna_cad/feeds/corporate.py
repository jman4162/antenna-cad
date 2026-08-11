"""Corporate (T-junction) feed-tree synthesis for rectangular patch arrays.

Topology: a 50-ohm trunk enters from the board's bottom edge and reaches the array
center, then splits recursively with **alternating axes** (columns, then rows, then
columns, ...) so every run stays in a lattice gap — an x-split junction always sits
in a row gap and a y-split trunk always travels in a column gap. Every junction is a
reactive T preceded by a quarter-wave transformer at Z = sqrt(50 x 25) ~ 70.7 ohm,
which restores the 25-ohm parallel point back to the system impedance, so all
routing stays at 50 ohm.

Phase: the final y-split feeds one element from below (patch feed edge faces -y,
"normal") and one from above (patch mirrored, radiated field 180 degrees out of
phase). The mirrored arm gets a trombone detour exactly half a guided wavelength
long, restoring co-phase radiation at the design frequency. The array-level FDTD
gate verifies this: a phase error splits the broadside beam.

Supported lattices: nx, ny in {1, 2, 4} (recursive halving). Wilkinson dividers
(isolation resistors) arrive with component modeling in a later phase.
"""

from __future__ import annotations

import math
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict
from shapely.ops import unary_union

from antenna_cad.core.units import to_hz, to_mm, to_ohm
from antenna_cad.elements.patch import RectangularPatch
from antenna_cad.integrations.phased_array import ArrayLattice
from antenna_cad.transmission_lines.cells import TraceRun, quarter_wave_length
from antenna_cad.transmission_lines.microstrip import synthesize_width


class FeedSynthesisError(ValueError):
    """The requested feed tree cannot be synthesized for this lattice/geometry."""


class FeedArm(BaseModel):
    """Bookkeeping for one root-to-element path."""

    model_config = ConfigDict(frozen=True)

    grid: tuple[int, int]
    mirrored: bool
    electrical_length_mm: float


class CorporateFeed(BaseModel):
    """A synthesized feed tree: copper, per-element arms, and element orientations."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    polygon: Any
    arms: tuple[FeedArm, ...]
    #: (ix, iy) -> element is mirrored (feed edge faces +y).
    mirrored: dict[tuple[int, int], bool]
    trunk_width_mm: float
    port_xy: tuple[float, float]


class _TreeBuilder:
    """Recursive alternating-axis H-tree in array-centered coordinates (mm, y-up)."""

    def __init__(
        self,
        patch: RectangularPatch,
        lattice: ArrayLattice,
        y_bottom: float,
        phase_compensation: bool = True,
    ) -> None:
        problem = patch.problem
        self.phase_compensation = phase_compensation
        self.patch = patch
        self.lattice = lattice
        self.y_bottom = y_bottom
        self.h = to_mm(problem.substrate_height)
        self.eps_r = problem.substrate_obj.eps_r
        self.f0 = to_hz(problem.center_frequency)
        z0 = to_ohm(problem.impedance)
        self.w50 = synthesize_width(z0, self.h, self.eps_r)
        self.w_match = synthesize_width(math.sqrt(z0 * z0 / 2), self.h, self.eps_r)
        self.quarter_match = quarter_wave_length(self.f0, self.w_match, self.h, self.eps_r)
        #: Trombone jog: a quarter guided wavelength on the 50-ohm line; the U-detour
        #: adds two jogs = half a guided wavelength of physical path.
        self.jog_50 = quarter_wave_length(self.f0, self.w50, self.h, self.eps_r)
        #: Base jog carried by BOTH final arms so their corner counts match.
        self.jog_base = 2 * self.w50
        self.runs: list[TraceRun] = []
        self.mirrored: dict[tuple[int, int], bool] = {}
        self.arm_lengths: dict[tuple[int, int], float] = {}

    # ------------------------------------------------------------------ helpers
    def _run(self, points: list[tuple[float, float]], width: float) -> float:
        run = TraceRun(points, width)
        self.runs.append(run)
        return run.electrical_length(self.h, self.eps_r)

    def _approach(self, start: tuple[float, float], end: tuple[float, float]) -> float:
        """Lay a straight 50-ohm run whose final quarter-wave is the transformer."""
        (x0, y0), (x1, y1) = start, end
        span = abs(x1 - x0) + abs(y1 - y0)
        if span <= self.quarter_match + 1e-9:
            raise FeedSynthesisError(
                f"approach {start} -> {end} ({span:.2f} mm) is shorter than the "
                f"quarter-wave transformer ({self.quarter_match:.2f} mm); increase "
                "element spacing or lower the frequency"
            )
        ux = (x1 - x0) / span if abs(x1 - x0) > 1e-9 else 0.0
        uy = (y1 - y0) / span if abs(y1 - y0) > 1e-9 else 0.0
        xm = x1 - ux * self.quarter_match
        ym = y1 - uy * self.quarter_match
        total = self._run([start, (xm, ym)], self.w50)
        total += self._run([(xm, ym), end], self.w_match)
        return total

    def _element_arm(self, junction: tuple[float, float], col: int, row: int) -> None:
        """Plain 50-ohm arm from a junction to the element's feed edge."""
        x, y = junction
        element = self.lattice.element_at(col, row)
        ex, ey = element.position
        if abs(ex - x) > 1e-6:
            raise FeedSynthesisError(
                f"junction x={x:.3f} does not line up with element {col, row} at x={ex:.3f}"
            )
        edge = self.patch.feed_edge_offset()
        mirrored = ey <= y
        y_to = ey + edge if mirrored else ey - edge
        span = abs(y - y_to)
        if not self.phase_compensation or self.lattice.ny == 1:
            # No mirrored counterpart to phase-match: plain straight arm.
            length = self._run([(x, y), (x, y_to)], self.w50)
        else:
            # Both arms carry an identical four-corner jog structure so that the
            # corner discontinuities (which shorten the effective electrical path)
            # cancel in the arm-length DIFFERENCE; only the jog width differs, by
            # exactly a quarter guided wavelength, making the mirrored arm's extra
            # electrical length exactly half a wave. A bare trombone on one arm
            # left a measurable residual row-phase error in FDTD.
            jog = self.jog_base + (self.jog_50 if mirrored else 0.0)
            if span <= self.w50 * 4:
                raise FeedSynthesisError(
                    f"no room for the phase jog between y={y:.2f} and the "
                    f"element edge at y={y_to:.2f}"
                )
            direction = -1.0 if mirrored else 1.0
            y_mid1 = y + direction * span * 0.35
            y_mid2 = y + direction * span * 0.65
            length = self._run(
                [
                    (x, y),
                    (x, y_mid1),
                    (x + jog, y_mid1),
                    (x + jog, y_mid2),
                    (x, y_mid2),
                    (x, y_to),
                ],
                self.w50,
            )
        self.mirrored[(col, row)] = mirrored
        self.arm_lengths[(col, row)] = length

    def _finish_arm(self, grid: tuple[int, int], upstream: float) -> None:
        self.arm_lengths[grid] = self.arm_lengths[grid] + upstream

    # ----------------------------------------------------------------- recursion
    def build(self) -> tuple[float, float]:
        """Build the whole tree; return the port (x, y) in array coordinates."""
        nx, ny = self.lattice.nx, self.lattice.ny
        if nx not in (1, 2, 4) or ny not in (1, 2, 4):
            raise FeedSynthesisError(f"corporate feed supports nx, ny in (1, 2, 4); got {nx}x{ny}")
        port = (0.0, self.y_bottom)
        cols, rows = list(range(nx)), list(range(ny))
        if nx == 1 and ny == 1:
            element = self.lattice.element_at(0, 0)
            y_feed = element.position[1] - self.patch.feed_edge_offset()
            self.mirrored[(0, 0)] = False
            self.arm_lengths[(0, 0)] = self._run([(0.0, self.y_bottom), (0.0, y_feed)], self.w50)
            return port
        if nx == 1:
            raise FeedSynthesisError(
                "single-column arrays taller than one row are not supported: the "
                "bottom-entry trunk would cross the lower patches (rotate the "
                "lattice so nx > 1)"
            )
        if ny > nx:
            raise FeedSynthesisError(
                f"lattices taller than wide ({nx}x{ny}) route row trunks through "
                "patch columns; rotate the lattice so nx >= ny"
            )
        # For a single row there is no row gap: the distribution line runs between
        # the board edge and the patches' feed edges. Otherwise the first junction
        # sits at the array center, in the central row gap.
        y_first = -(self.patch.feed_edge_offset() + 2 * self.w50) if ny == 1 else 0.0
        # Trunk (50 ohm + transformer) from the board edge to the first junction.
        trunk = self._approach((0.0, self.y_bottom), (0.0, y_first))
        self._split((0.0, y_first), trunk, cols, rows, axis="x")
        return port

    def _split(
        self,
        junction: tuple[float, float],
        upstream: float,
        cols: list[int],
        rows: list[int],
        axis: Literal["x", "y"],
    ) -> None:
        x, y = junction
        if len(cols) == 1 and len(rows) == 1:
            self._element_arm(junction, cols[0], rows[0])
            self._finish_arm((cols[0], rows[0]), upstream)
            return
        if axis == "x":
            if len(cols) == 1:
                self._split(junction, upstream, cols, rows, axis="y")
                return
            half = len(cols) // 2
            for group in (cols[:half], cols[half:]):
                gx = self._cols_center(group)
                arm = self._approach(junction, (gx, y))
                self._split((gx, y), upstream + arm, group, rows, axis="y")
        else:
            if len(rows) == 1:
                self._split(junction, upstream, cols, rows, axis="x")
                return
            half = len(rows) // 2
            lower, upper = rows[:half], rows[half:]
            if len(lower) == 1:
                if len(cols) > 1:
                    # A pair of rows splits only once the column is singled out:
                    # otherwise the x-distribution would run along a patch row
                    # instead of the row gap this junction sits in.
                    self._split(junction, upstream, cols, rows, axis="x")
                    return
                # Final level: connect both elements straight from this junction.
                for row in (upper[0], lower[0]):
                    self._element_arm(junction, cols[0], row)
                    self._finish_arm((cols[0], row), upstream)
                return
            for group in (upper, lower):
                gy = self._rows_center(group)
                arm = self._approach(junction, (x, gy))
                self._split((x, gy), upstream + arm, cols, group, axis="x")

    def _cols_center(self, cols: list[int]) -> float:
        xs = [self.lattice.element_at(c, 0).position[0] for c in cols]
        return sum(xs) / len(xs)

    def _rows_center(self, rows: list[int]) -> float:
        ys = [self.lattice.element_at(0, r).position[1] for r in rows]
        return sum(ys) / len(ys)


def build_corporate_feed(
    patch: RectangularPatch,
    lattice: ArrayLattice,
    y_bottom: float,
    phase_compensation: bool = True,
) -> CorporateFeed:
    """Synthesize the corporate feed for ``lattice`` in array-centered coordinates.

    ``y_bottom`` is the board's bottom edge (where the input port sits) in the same
    coordinates. Raises :class:`FeedSynthesisError` when the lattice is unsupported
    or the geometry does not fit.
    """
    builder = _TreeBuilder(patch, lattice, y_bottom, phase_compensation)
    port = builder.build()

    missing = [
        element.grid for element in lattice.elements if element.grid not in builder.arm_lengths
    ]
    if missing:
        raise FeedSynthesisError(f"feed tree failed to reach elements: {missing}")

    polygon = unary_union([run.polygon() for run in builder.runs])
    if polygon.geom_type != "Polygon":
        raise FeedSynthesisError(
            f"feed copper is not a single connected polygon ({polygon.geom_type})"
        )

    arms = tuple(
        FeedArm(grid=grid, mirrored=builder.mirrored[grid], electrical_length_mm=length)
        for grid, length in sorted(builder.arm_lengths.items())
    )
    return CorporateFeed(
        polygon=polygon,
        arms=arms,
        mirrored=builder.mirrored,
        trunk_width_mm=builder.w50,
        port_xy=port,
    )

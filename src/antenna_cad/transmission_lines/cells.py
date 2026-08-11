"""Rectilinear microstrip trace geometry with electrical-length bookkeeping.

A :class:`TraceRun` is an axis-aligned polyline at constant width; its polygon is the
union of segment rectangles (square corner joins — corner miters are a planned
refinement, and the array simulation gate quantifies whether they are needed).
Electrical length uses the quasi-static effective permittivity for the run's width,
so feed arms can be compared and phase-compensated in free-space-equivalent
millimeters.
"""

from __future__ import annotations

import itertools
import math
from typing import Any

from shapely.geometry import box
from shapely.ops import unary_union

from antenna_cad.transmission_lines.microstrip import effective_permittivity


class TraceError(ValueError):
    """The trace geometry is not representable (non-rectilinear, degenerate)."""


def _segments(points: list[tuple[float, float]]) -> list[tuple[float, float, float, float]]:
    if len(points) < 2:
        raise TraceError("a trace needs at least two points")
    segments = []
    for (x0, y0), (x1, y1) in itertools.pairwise(points):
        if abs(x1 - x0) > 1e-9 and abs(y1 - y0) > 1e-9:
            raise TraceError(f"trace segments must be axis-aligned, got {x0, y0} -> {x1, y1}")
        if abs(x1 - x0) < 1e-9 and abs(y1 - y0) < 1e-9:
            raise TraceError(f"zero-length trace segment at {x0, y0}")
        segments.append((x0, y0, x1, y1))
    return segments


class TraceRun:
    """An axis-aligned constant-width microstrip trace."""

    def __init__(self, points: list[tuple[float, float]], width_mm: float) -> None:
        if width_mm <= 0:
            raise TraceError(f"trace width must be positive, got {width_mm}")
        self.points = [(float(x), float(y)) for x, y in points]
        self.width = float(width_mm)
        self._segments = _segments(self.points)

    def length(self) -> float:
        """Centerline length in millimeters."""
        return sum(abs(x1 - x0) + abs(y1 - y0) for x0, y0, x1, y1 in self._segments)

    def electrical_length(self, height_mm: float, eps_r: float) -> float:
        """Length in free-space-equivalent millimeters (physical x sqrt(eps_eff))."""
        eps_eff = effective_permittivity(self.width, height_mm, eps_r)
        return self.length() * math.sqrt(eps_eff)

    def polygon(self) -> Any:
        """Copper polygon: union of per-segment rectangles (square corner joins)."""
        half = self.width / 2
        rects = []
        for x0, y0, x1, y1 in self._segments:
            if abs(x1 - x0) > 1e-9:  # horizontal
                rects.append(box(min(x0, x1), y0 - half, max(x0, x1), y0 + half))
            else:  # vertical
                rects.append(box(x0 - half, min(y0, y1), x0 + half, max(y0, y1)))
        # Fill each interior vertex with a full-width square: segment rectangles stop
        # at their centerline endpoints, which leaves the outer corner quadrant open.
        for x, y in self.points[1:-1]:
            rects.append(box(x - half, y - half, x + half, y + half))
        merged = unary_union(rects)
        if merged.geom_type != "Polygon":
            raise TraceError("trace polygon is not simply connected (self-crossing run?)")
        return merged


def quarter_wave_length(
    frequency_hz: float, width_mm: float, height_mm: float, eps_r: float
) -> float:
    """Physical length in mm of a quarter guided wavelength for this line geometry."""
    from antenna_cad.transmission_lines.microstrip import SPEED_OF_LIGHT

    eps_eff = effective_permittivity(width_mm, height_mm, eps_r)
    return SPEED_OF_LIGHT / (4 * frequency_hz * math.sqrt(eps_eff)) * 1000

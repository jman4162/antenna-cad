"""Rectangular microstrip patch: analytic synthesis and IR geometry.

The transmission-line model (Balanis, *Antenna Theory*, ch. 14) sizes the radiator:
width from the standard efficiency formula, length from the effective permittivity and
fringing extension, and the inset-feed depth from the slot-conductance edge resistance
with the cos^2 inset taper. These values land within a few percent of full-wave
results on thin substrates; the simulation loop closes the rest.
"""

from __future__ import annotations

import math

import numpy as np
from pydantic import BaseModel, ConfigDict
from scipy.special import j0
from shapely.geometry import box
from shapely.ops import unary_union

from antenna_cad.core.units import LengthQ, Quantity, to_ghz, to_hz, to_mm, to_ohm
from antenna_cad.ir import BoardDefinition, Net, PhysicalDesign, PlanarShape, Port, Stackup
from antenna_cad.problem import DesignProblem
from antenna_cad.transmission_lines.microstrip import (
    SPEED_OF_LIGHT,
    effective_permittivity,
    synthesize_width,
)

FEED_NET = "antenna/feed"
GROUND_NET = "gnd"


def patch_width(frequency_hz: float, eps_r: float) -> float:
    """Radiating width in meters: ``c / (2 f) * sqrt(2 / (eps_r + 1))``."""
    return SPEED_OF_LIGHT / (2 * frequency_hz) * math.sqrt(2 / (eps_r + 1))


def length_extension(width_m: float, height_m: float, eps_eff: float) -> float:
    """Fringing-field length extension ΔL in meters (Hammerstad)."""
    u = width_m / height_m
    return 0.412 * height_m * (eps_eff + 0.3) * (u + 0.264) / ((eps_eff - 0.258) * (u + 0.8))


def patch_length(frequency_hz: float, width_m: float, height_m: float, eps_r: float) -> float:
    """Resonant length in meters: half a guided wavelength minus twice ΔL."""
    eps_eff = effective_permittivity(width_m, height_m, eps_r)
    half_wave = SPEED_OF_LIGHT / (2 * frequency_hz * math.sqrt(eps_eff))
    return half_wave - 2 * length_extension(width_m, height_m, eps_eff)


def edge_resistance(frequency_hz: float, width_m: float, length_m: float) -> float:
    """Input resistance in ohms at the radiating edge.

    Computed from the two-slot model with mutual coupling:
    ``R = 1 / (2 (G1 + G12))``, where both conductances come from the standard
    radiation integrals (Balanis eq. 14-12/14-18a), evaluated by fixed-grid
    quadrature.
    """
    k0 = 2 * math.pi * frequency_hz / SPEED_OF_LIGHT
    theta = np.linspace(1e-6, math.pi - 1e-6, 2001)
    cos_t, sin_t = np.cos(theta), np.sin(theta)
    # sin(k0 W/2 cosθ)/cosθ has a removable singularity at θ = π/2; the grid
    # excludes the exact point and the expression is well-behaved beside it.
    slot = np.sin(k0 * width_m / 2 * cos_t) / cos_t
    integrand_g1 = slot**2 * sin_t**3
    g1 = float(np.trapezoid(integrand_g1, theta)) / (120 * math.pi**2)
    integrand_g12 = slot**2 * j0(k0 * length_m * sin_t) * sin_t**3
    g12 = float(np.trapezoid(integrand_g12, theta)) / (120 * math.pi**2)
    return 1 / (2 * (g1 + g12))


def inset_depth(length_m: float, edge_r: float, target_r: float) -> float:
    """Inset distance in meters where the cos^2-tapered resistance equals ``target_r``."""
    if target_r >= edge_r:
        return 0.0
    return length_m / math.pi * math.acos(math.sqrt(target_r / edge_r))


class RectangularPatch(BaseModel):
    """A synthesized inset-fed rectangular patch, ready to realize as a design.

    All lengths are canonical-unit Quantities (mm). Instances come from
    :meth:`synthesize`; construct directly only to bypass synthesis deliberately.
    """

    model_config = ConfigDict(frozen=True)

    problem: DesignProblem
    width: LengthQ
    length: LengthQ
    inset: LengthQ
    inset_gap: LengthQ
    feed_width: LengthQ
    eps_eff: float
    edge_resistance_ohm: float

    @classmethod
    def synthesize(cls, problem: DesignProblem) -> RectangularPatch:
        """Size a patch for the problem's frequency, substrate, and feed impedance.

        Examples
        --------
        >>> from antenna_cad import DesignProblem
        >>> from antenna_cad.elements import RectangularPatch
        >>> patch = RectangularPatch.synthesize(DesignProblem(center_frequency="10 GHz"))
        >>> 8.0 < patch.width.magnitude < 10.5  # mm, X-band on RO4350B
        True
        """
        f_hz = to_hz(problem.center_frequency)
        eps_r = problem.substrate_obj.eps_r
        h_m = to_mm(problem.substrate_height) / 1000.0

        w_m = patch_width(f_hz, eps_r)
        l_m = patch_length(f_hz, w_m, h_m, eps_r)
        r_edge = edge_resistance(f_hz, w_m, l_m)
        y0_m = inset_depth(l_m, r_edge, to_ohm(problem.impedance))
        feed_w_m = synthesize_width(to_ohm(problem.impedance), h_m, eps_r)

        return cls(
            problem=problem,
            width=Quantity(w_m * 1000, "mm"),
            length=Quantity(l_m * 1000, "mm"),
            inset=Quantity(y0_m * 1000, "mm"),
            # Notch clearance each side of the feed line; a common starting heuristic,
            # refined in simulation.
            inset_gap=Quantity(feed_w_m / 2 * 1000, "mm"),
            feed_width=Quantity(feed_w_m * 1000, "mm"),
            eps_eff=effective_permittivity(w_m, h_m, eps_r),
            edge_resistance_ohm=r_edge,
        )

    def to_design(self, name: str = "patch") -> PhysicalDesign:
        """Realize the patch as a two-layer board with ground plane and edge port.

        Geometry (mm, origin at the board's lower-left): patch centered, resonant
        length along y, inset notch and feed line toward the y=0 edge, where the
        port sits.
        """
        w = to_mm(self.width)
        length = to_mm(self.length)
        y0 = to_mm(self.inset)
        gap = to_mm(self.inset_gap)
        feed_w = to_mm(self.feed_width)
        h = to_mm(self.problem.substrate_height)
        lambda0_mm = SPEED_OF_LIGHT / to_hz(self.problem.center_frequency) * 1000

        # Ground and substrate extend at least 6h, and a quarter wavelength, beyond
        # the patch on every side.
        margin = max(6 * h, lambda0_mm / 4)
        board_w = w + 2 * margin
        board_h = length + 2 * margin
        x0 = (board_w - w) / 2  # patch lower-left
        y0_board = (board_h - length) / 2

        patch_poly = box(x0, y0_board, x0 + w, y0_board + length)
        x_feed = board_w / 2
        notch = box(
            x_feed - feed_w / 2 - gap,
            y0_board - 1e-3,  # overlap slightly so the difference is clean
            x_feed + feed_w / 2 + gap,
            y0_board + y0,
        )
        feed = box(x_feed - feed_w / 2, 0.0, x_feed + feed_w / 2, y0_board + y0)
        copper = unary_union([patch_poly.difference(notch), feed])

        return PhysicalDesign(
            name=name,
            frequency=self.problem.center_frequency,
            stackup=Stackup.two_layer(self.problem.substrate_obj, self.problem.substrate_height),
            board=BoardDefinition(outline=box(0, 0, board_w, board_h)),
            nets=(Net(name=FEED_NET), Net(name=GROUND_NET, kind="ground")),
            shapes=(
                PlanarShape(layer="top", polygon=copper, net=FEED_NET, role="radiator"),
                PlanarShape(
                    layer="bottom",
                    polygon=box(0, 0, board_w, board_h),
                    net=GROUND_NET,
                    role="ground",
                ),
            ),
            ports=(
                Port(
                    name="p1",
                    net=FEED_NET,
                    position=(x_feed, 0.0),
                    layer="top",
                    reference_layer="bottom",
                    z0=self.problem.impedance,
                ),
            ),
            parameters={
                "patch_width": f"{to_mm(self.width)!r} mm",
                "patch_length": f"{to_mm(self.length)!r} mm",
                "inset_depth": f"{to_mm(self.inset)!r} mm",
                "inset_gap": f"{to_mm(self.inset_gap)!r} mm",
                "feed_width": f"{to_mm(self.feed_width)!r} mm",
                "eps_eff": self.eps_eff,
                "edge_resistance_ohm": self.edge_resistance_ohm,
                "center_frequency": f"{to_ghz(self.problem.center_frequency)!r} GHz",
                "substrate": self.problem.substrate,
            },
        )

"""Patch synthesis tests against Balanis, Antenna Theory, Example 14.1.

The reference design: f0 = 10 GHz, eps_r = 2.2, h = 0.1588 cm gives
W = 1.186 cm, L = 0.906 cm, and a 50-ohm inset at y0 = 0.3126 cm.
"""

import pytest
from shapely.geometry import Point

from antenna_cad import DesignProblem
from antenna_cad.elements import RectangularPatch
from antenna_cad.elements.patch import (
    edge_resistance,
    inset_depth,
    patch_length,
    patch_width,
)


class TestBalanisExample14_1:
    F0 = 10e9
    EPS_R = 2.2
    H = 0.1588e-2  # m

    def test_width(self):
        assert patch_width(self.F0, self.EPS_R) == pytest.approx(1.186e-2, rel=0.01)

    def test_length(self):
        w = patch_width(self.F0, self.EPS_R)
        assert patch_length(self.F0, w, self.H, self.EPS_R) == pytest.approx(0.906e-2, rel=0.01)

    def test_edge_resistance(self):
        # Balanis: G1 = 0.00157 S, G12 = 6.1683e-4 S -> Rin = 228.35 ohm.
        w, length = 1.186e-2, 0.906e-2
        assert edge_resistance(self.F0, w, length) == pytest.approx(228.35, rel=0.02)

    def test_inset_depth(self):
        y0 = inset_depth(0.906e-2, 228.35, 50.0)
        assert y0 == pytest.approx(0.3126e-2, rel=0.02)


class TestSynthesizedPatch:
    @pytest.fixture
    def patch(self) -> RectangularPatch:
        return RectangularPatch.synthesize(DesignProblem(center_frequency="10 GHz"))

    def test_dimensions_are_plausible(self, patch):
        # X-band patch on RO4350B (eps_r 3.66): roughly 8-10 mm wide, 7-9 mm long.
        assert 8.0 < patch.width.magnitude < 10.5
        assert 6.5 < patch.length.magnitude < 9.0
        assert patch.length.magnitude < patch.width.magnitude

    def test_inset_inside_patch(self, patch):
        assert 0 < patch.inset.magnitude < patch.length.magnitude / 2

    def test_design_realizes_and_validates(self, patch):
        design = patch.to_design()
        assert design.content_hash()  # validators all passed
        top = design.shapes[0]
        assert top.polygon.is_valid
        assert design.board.outline.contains(top.polygon)

    def test_port_sits_on_feed_copper(self, patch):
        design = patch.to_design()
        port = design.ports[0]
        # The port is at the board edge; a point just inside must be on copper.
        probe = Point(port.position[0], port.position[1] + 0.05)
        assert design.shapes[0].polygon.covers(probe)

    def test_synthesis_is_deterministic(self, patch):
        again = RectangularPatch.synthesize(DesignProblem(center_frequency="10 GHz"))
        assert again.to_design().content_hash() == patch.to_design().content_hash()

    def test_frequency_scales_size_down(self):
        low = RectangularPatch.synthesize(DesignProblem(center_frequency="5 GHz"))
        high = RectangularPatch.synthesize(DesignProblem(center_frequency="28 GHz"))
        assert high.width.magnitude < low.width.magnitude

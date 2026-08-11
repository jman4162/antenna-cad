"""Tests for feed cells, corporate-tree synthesis, and array realization."""

import pytest

from antenna_cad import DesignProblem
from antenna_cad.elements import RectangularPatch
from antenna_cad.feeds.corporate import FeedSynthesisError, build_corporate_feed
from antenna_cad.integrations.phased_array import rectangular_lattice
from antenna_cad.transmission_lines.cells import TraceError, TraceRun


@pytest.fixture
def patch():
    return RectangularPatch.synthesize(DesignProblem(center_frequency="10 GHz"))


def spacing_mm():
    return 0.6 * 29.9792458  # 0.6 lambda at 10 GHz


class TestTraceRun:
    def test_length(self):
        run = TraceRun([(0, 0), (10, 0), (10, 5)], 1.0)
        assert run.length() == pytest.approx(15.0)

    def test_polygon_covers_corner(self):
        from shapely.geometry import Point

        run = TraceRun([(0, 0), (10, 0), (10, 5)], 1.0)
        poly = run.polygon()
        assert poly.is_valid
        # The outer corner quadrant must be filled.
        assert poly.covers(Point(10.4, -0.4))

    def test_diagonal_rejected(self):
        with pytest.raises(TraceError, match="axis-aligned"):
            TraceRun([(0, 0), (5, 5)], 1.0)

    def test_electrical_longer_than_physical(self):
        run = TraceRun([(0, 0), (10, 0)], 1.1)
        assert run.electrical_length(0.508, 3.66) > run.length()


class TestCorporateFeed:
    @pytest.mark.parametrize(("nx", "ny"), [(2, 2), (4, 4), (2, 1), (4, 2)])
    def test_tree_builds(self, patch, nx, ny):
        lattice = rectangular_lattice(nx, ny, spacing_mm(), spacing_mm())
        feed = build_corporate_feed(patch, lattice, y_bottom=-30.0)
        assert len(feed.arms) == nx * ny
        assert feed.polygon.is_valid

    def test_normal_arms_length_matched(self, patch):
        lattice = rectangular_lattice(2, 2, spacing_mm(), spacing_mm())
        feed = build_corporate_feed(patch, lattice, y_bottom=-30.0)
        normal = [a.electrical_length_mm for a in feed.arms if not a.mirrored]
        mirrored = [a.electrical_length_mm for a in feed.arms if a.mirrored]
        assert len(normal) == len(mirrored) == 2
        assert max(normal) - min(normal) < 1e-6
        assert max(mirrored) - min(mirrored) < 1e-6

    def test_mirrored_arms_offset_by_half_wave(self, patch):
        lattice = rectangular_lattice(2, 2, spacing_mm(), spacing_mm())
        feed = build_corporate_feed(patch, lattice, y_bottom=-30.0)
        normal = next(a.electrical_length_mm for a in feed.arms if not a.mirrored)
        mirrored = next(a.electrical_length_mm for a in feed.arms if a.mirrored)
        # The trombone adds half a free-space wavelength of electrical length.
        assert mirrored - normal == pytest.approx(29.9792458 / 2, rel=0.02)

    def test_lower_rows_are_mirrored(self, patch):
        lattice = rectangular_lattice(2, 2, spacing_mm(), spacing_mm())
        feed = build_corporate_feed(patch, lattice, y_bottom=-30.0)
        assert feed.mirrored[(0, 0)] is True  # lower row, fed from above
        assert feed.mirrored[(0, 1)] is False  # upper row, fed from below

    def test_single_column_rejected(self, patch):
        lattice = rectangular_lattice(1, 2, spacing_mm(), spacing_mm())
        with pytest.raises(FeedSynthesisError, match="single-column"):
            build_corporate_feed(patch, lattice, y_bottom=-30.0)

    def test_unsupported_size_rejected(self, patch):
        lattice = rectangular_lattice(3, 2, spacing_mm(), spacing_mm())
        with pytest.raises(FeedSynthesisError, match=r"\(1, 2, 4\)"):
            build_corporate_feed(patch, lattice, y_bottom=-30.0)

    def test_too_tight_spacing_fails_loudly(self, patch):
        lattice = rectangular_lattice(2, 2, 6.0, 6.0)  # 0.2 lambda: no room
        with pytest.raises(FeedSynthesisError):
            build_corporate_feed(patch, lattice, y_bottom=-10.0)


class TestRealizeArray:
    @pytest.mark.parametrize(("nx", "ny"), [(2, 2), (4, 4)])
    def test_design_builds_and_validates(self, patch, nx, ny):
        from antenna_cad.arrays.layout import realize_array

        lattice = rectangular_lattice(nx, ny, spacing_mm(), spacing_mm())
        design = realize_array(patch, lattice, name=f"array{nx}x{ny}")
        assert design.content_hash()
        top = design.shapes[0]
        assert top.polygon.is_valid
        assert not list(top.polygon.interiors)
        assert design.board.outline.covers(top.polygon)
        assert design.parameters["n_elements"] == nx * ny

    def test_port_on_bottom_edge_on_copper(self, patch):
        from shapely.geometry import Point

        from antenna_cad.arrays.layout import realize_array

        lattice = rectangular_lattice(2, 2, spacing_mm(), spacing_mm())
        design = realize_array(patch, lattice)
        port = design.ports[0]
        assert port.position[1] == 0.0
        assert design.shapes[0].polygon.covers(Point(port.position[0], 0.05))

    def test_deterministic(self, patch):
        from antenna_cad.arrays.layout import realize_array

        lattice = rectangular_lattice(2, 2, spacing_mm(), spacing_mm())
        a = realize_array(patch, lattice).content_hash()
        b = realize_array(patch, lattice).content_hash()
        assert a == b

    def test_spec_dispatches_array(self, tmp_path):
        from antenna_cad.designspec import DesignSpec

        spec = tmp_path / "spec.yaml"
        spec.write_text(
            "design:\n  name: arr\nrequirements:\n  center_frequency: 10 GHz\n"
            "element:\n  type: rectangular_patch\narray:\n  nx: 2\n  ny: 2\n"
            "  spacing: 0.6 lambda\n"
        )
        design = DesignSpec.load(spec).synthesize()
        assert design.parameters["n_elements"] == 4

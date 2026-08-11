"""Tests for the array lattice adapter (PAM-compatible ordering and positions)."""

import pytest

from antenna_cad.designspec import ArraySection
from antenna_cad.integrations.phased_array import (
    ArrayLattice,
    ElementPlacement,
    element_net,
    from_phased_array,
    rectangular_lattice,
)


@pytest.fixture
def pam():
    return pytest.importorskip("phased_array", reason="phased-array-modeling not installed")


class TestRectangularLattice:
    def test_ordering_is_x_slow(self):
        lattice = rectangular_lattice(2, 3, 10.0, 12.0)
        assert lattice.elements[0].grid == (0, 0)
        assert lattice.elements[1].grid == (0, 1)
        assert lattice.elements[3].grid == (1, 0)
        assert lattice.element_at(1, 2).index == 1 * 3 + 2

    def test_even_grid_centering(self):
        lattice = rectangular_lattice(2, 2, 10.0, 10.0)
        xs = sorted({e.position[0] for e in lattice.elements})
        assert xs == [-5.0, 5.0]

    def test_odd_grid_centering(self):
        lattice = rectangular_lattice(3, 1, 10.0, 10.0)
        xs = [e.position[0] for e in lattice.elements]
        assert xs == [-10.0, 0.0, 10.0]

    def test_net_names(self):
        lattice = rectangular_lattice(2, 2, 10.0, 10.0)
        assert lattice.element_at(0, 1).net == "array0/e0_1/feed"
        assert element_net(3, 4) == "array0/e3_4/feed"

    def test_index_mismatch_rejected(self):
        good = rectangular_lattice(1, 2, 10.0, 10.0)
        elements = (good.elements[1].model_copy(update={"index": 0}), good.elements[0])
        with pytest.raises(ValueError, match="PAM flat ordering"):
            ArrayLattice(nx=1, ny=2, dx_mm=10.0, dy_mm=10.0, elements=elements)


class TestAgainstPam:
    """The built-in lattice must reproduce phased_array's factory positions exactly."""

    @pytest.mark.parametrize(("nx", "ny"), [(2, 2), (4, 4), (3, 5), (1, 4)])
    def test_positions_match_factory(self, pam, nx, ny):
        wavelength = 0.0299792458  # 10 GHz, meters
        dx_wl, dy_wl = 0.6, 0.55
        geometry = pam.create_rectangular_array(nx, ny, dx_wl, dy_wl, wavelength=wavelength)
        ours = rectangular_lattice(nx, ny, dx_wl * wavelength * 1000, dy_wl * wavelength * 1000)
        for element, gx, gy in zip(ours.elements, geometry.x, geometry.y, strict=True):
            assert element.position[0] == pytest.approx(float(gx) * 1000, abs=1e-9)
            assert element.position[1] == pytest.approx(float(gy) * 1000, abs=1e-9)

    def test_from_phased_array_wraps_geometry(self, pam):
        wavelength = 0.0299792458
        geometry = pam.create_rectangular_array(2, 2, 0.6, 0.6, wavelength=wavelength)
        lattice = from_phased_array(geometry, 2, 2)
        assert lattice.nx == 2
        assert lattice.dx_mm == pytest.approx(0.6 * wavelength * 1000)
        assert lattice.element_at(1, 1).position[0] > 0

    def test_wrong_count_rejected(self, pam):
        geometry = pam.create_rectangular_array(2, 2, 0.5, 0.5, wavelength=0.03)
        with pytest.raises(ValueError, match="elements"):
            from_phased_array(geometry, 2, 3)


class TestArraySection:
    def test_lambda_spacing(self):
        section = ArraySection(nx=2, ny=2, spacing="0.6 lambda")
        dx, dy = section.spacing_mm(10e9)
        assert dx == pytest.approx(0.6 * 29.9792458)
        assert dy == dx

    def test_metric_spacing(self):
        section = ArraySection(nx=2, ny=2, spacing="18 mm", spacing_y="20 mm")
        assert section.spacing_mm(10e9) == (pytest.approx(18.0), pytest.approx(20.0))

    def test_bad_spacing_rejected(self):
        with pytest.raises(ValueError, match="quantity|magnitude"):
            ArraySection(nx=2, ny=2, spacing="wide")


def test_placement_is_frozen():
    placement = ElementPlacement(index=0, grid=(0, 0), position=(0.0, 0.0), net="array0/e0_0/feed")
    with pytest.raises(Exception, match="frozen"):
        placement.index = 1  # type: ignore[misc]

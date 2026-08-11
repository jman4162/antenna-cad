"""Microstrip model tests against published values (Pozar, Microwave Engineering)."""

import pytest

from antenna_cad.transmission_lines import (
    characteristic_impedance,
    effective_permittivity,
    guided_wavelength,
    synthesize_width,
)


class TestPozarExample3_7:
    """50-ohm line on eps_r=2.20, d=0.127 cm: W/d = 3.081, eps_eff about 1.87."""

    def test_synthesis(self):
        width = synthesize_width(50.0, 0.127, 2.20)
        assert width / 0.127 == pytest.approx(3.081, rel=0.02)

    def test_effective_permittivity(self):
        assert effective_permittivity(3.081 * 0.127, 0.127, 2.20) == pytest.approx(1.87, rel=0.02)


class TestSelfConsistency:
    @pytest.mark.parametrize("z0", [30.0, 50.0, 75.0, 100.0])
    @pytest.mark.parametrize("eps_r", [2.2, 3.66, 4.4, 10.2])
    def test_synthesize_then_analyze(self, z0, eps_r):
        width = synthesize_width(z0, 0.508, eps_r)
        assert characteristic_impedance(width, 0.508, eps_r) == pytest.approx(z0, rel=0.02)

    def test_wider_line_is_lower_impedance(self):
        z_narrow = characteristic_impedance(0.3, 0.508, 3.66)
        z_wide = characteristic_impedance(3.0, 0.508, 3.66)
        assert z_wide < z_narrow


def test_guided_wavelength_between_air_and_dielectric():
    lam = guided_wavelength(10e9, 1.1e-3, 0.508e-3, 3.66)
    lam0 = 299792458.0 / 10e9
    assert lam0 / 3.66**0.5 < lam < lam0


def test_nonpositive_geometry_rejected():
    with pytest.raises(ValueError, match="positive"):
        effective_permittivity(0.0, 0.508, 3.66)

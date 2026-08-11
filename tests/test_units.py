"""Tests for unit handling."""

import pytest

from antenna_cad.core.units import Quantity, as_quantity, format_quantity, to_ghz, to_mm


def test_parse_string():
    q = as_quantity("10 GHz", "frequency")
    assert q.magnitude == 10.0
    assert str(q.units) == "gigahertz"


def test_normalizes_units():
    assert as_quantity("0.001 m", "length").magnitude == pytest.approx(1.0)
    assert as_quantity(Quantity(2.5e9, "Hz"), "frequency").magnitude == pytest.approx(2.5)


def test_tuple_input():
    assert as_quantity((50, "ohm"), "impedance").magnitude == 50.0


def test_wrong_dimension_rejected():
    with pytest.raises(ValueError, match="incompatible"):
        as_quantity("10 GHz", "length")


def test_bare_number_rejected_for_dimensional():
    with pytest.raises(ValueError, match="include a unit"):
        as_quantity(10.0, "frequency")


def test_bare_unit_string_rejected():
    with pytest.raises(ValueError, match="could not parse"):
        as_quantity("mm", "length")


def test_unknown_kind_rejected():
    with pytest.raises(ValueError, match="unknown quantity kind"):
        as_quantity("1 mm", "voltage")


def test_format_round_trips():
    q = as_quantity("8.42 mm", "length")
    assert as_quantity(format_quantity(q), "length") == q


def test_converters():
    assert to_mm(Quantity(0.0254, "m")) == pytest.approx(25.4)
    assert to_ghz(Quantity(1e10, "Hz")) == pytest.approx(10.0)

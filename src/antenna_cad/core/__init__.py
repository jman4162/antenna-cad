"""Shared foundations: unit handling, material data."""

from antenna_cad.core.materials import SUBSTRATES, Substrate, get_substrate
from antenna_cad.core.units import Quantity, as_quantity, to_ghz, to_hz, to_mm, to_ohm, ureg

__all__ = [
    "SUBSTRATES",
    "Quantity",
    "Substrate",
    "as_quantity",
    "get_substrate",
    "to_ghz",
    "to_hz",
    "to_mm",
    "to_ohm",
    "ureg",
]

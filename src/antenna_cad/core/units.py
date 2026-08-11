"""Unit handling for physical quantities.

Every physical quantity in the public API carries a unit, backed by a single shared
:mod:`pint` registry. Values enter as strings (``"10 GHz"``), ``(value, unit)`` tuples,
or ``pint.Quantity`` objects, and are normalized to one canonical unit per kind so that
serialized designs are stable and hashable. Bare floats cross into backends (KiCad
millimeters, openEMS SI) only through the explicit ``to_*`` converters here.
"""

from __future__ import annotations

from typing import Annotated, Any

import pint
from pydantic import GetPydanticSchema
from pydantic_core import core_schema

# Typed as Any: pint's UnitRegistry is generic over magnitude type in recent stubs, and
# quantities here are always float-magnitude scalars.
ureg: Any = pint.UnitRegistry()
Quantity = ureg.Quantity

#: Canonical storage unit per quantity kind. Chosen for readable serialized designs:
#: PCB geometry reads naturally in mm, RF frequencies in GHz.
CANONICAL_UNITS = {
    "length": "mm",
    "frequency": "GHz",
    "impedance": "ohm",
    "angle": "degree",
    "dimensionless": "dimensionless",
}


def as_quantity(value: Any, kind: str) -> Any:
    """Coerce ``value`` to a float-magnitude Quantity in the canonical unit for ``kind``.

    Parameters
    ----------
    value
        A quantity as a string (``"8.42 mm"``), a ``pint.Quantity``, a
        ``(magnitude, unit)`` tuple, or, for dimensionless kinds only, a number.
    kind
        One of the keys of :data:`CANONICAL_UNITS`.

    Returns
    -------
    pint.Quantity
        The value converted to the canonical unit, with a float magnitude.

    Raises
    ------
    ValueError
        If the value cannot be parsed or has an incompatible dimension.

    Examples
    --------
    >>> from antenna_cad.core.units import as_quantity
    >>> as_quantity("10 GHz", "frequency")
    <Quantity(10.0, 'gigahertz')>
    >>> as_quantity(("8.42", "mm"), "length")
    <Quantity(8.42, 'millimeter')>
    """
    if kind not in CANONICAL_UNITS:
        raise ValueError(
            f"unknown quantity kind {kind!r}; expected one of {sorted(CANONICAL_UNITS)}"
        )
    target = CANONICAL_UNITS[kind]

    if isinstance(value, tuple) and len(value) == 2:
        quantity = Quantity(float(value[0]), str(value[1]))
    elif isinstance(value, str):
        if not any(ch.isdigit() for ch in value):
            # pint parses a bare unit like "mm" as 1 mm; that is almost always a
            # caller mistake, so require an explicit magnitude.
            raise ValueError(f"could not parse {value!r} as a quantity: no magnitude")
        quantity = ureg(value)
        if not isinstance(quantity, pint.Quantity):
            raise ValueError(f"could not parse {value!r} as a quantity")
    elif isinstance(value, pint.Quantity):
        quantity = value
    elif isinstance(value, int | float) and kind == "dimensionless":
        quantity = Quantity(float(value), "")
    else:
        raise ValueError(f"cannot interpret {value!r} as a {kind} quantity; include a unit")

    if not quantity.is_compatible_with(target):
        raise ValueError(f"{value!r} has dimension incompatible with {kind} ({target})")
    converted = quantity.to(target)
    return Quantity(float(converted.magnitude), target)


def format_quantity(quantity: Any) -> str:
    """Format a Quantity compactly and reparseably, e.g. ``'8.42 mm'``.

    Examples
    --------
    >>> from antenna_cad.core.units import Quantity, format_quantity
    >>> format_quantity(Quantity(8.42, "mm"))
    '8.42 mm'
    """
    return f"{quantity.magnitude!r} {quantity.units:~}"


def to_mm(quantity: Any) -> float:
    """Return the bare magnitude of a length in millimeters."""
    return float(quantity.to("mm").magnitude)


def to_m(quantity: Any) -> float:
    """Return the bare magnitude of a length in meters."""
    return float(quantity.to("m").magnitude)


def to_hz(quantity: Any) -> float:
    """Return the bare magnitude of a frequency in hertz."""
    return float(quantity.to("Hz").magnitude)


def to_ghz(quantity: Any) -> float:
    """Return the bare magnitude of a frequency in gigahertz."""
    return float(quantity.to("GHz").magnitude)


def to_ohm(quantity: Any) -> float:
    """Return the bare magnitude of an impedance in ohms."""
    return float(quantity.to("ohm").magnitude)


def _quantity_type(kind: str) -> Any:
    """Build an Annotated pydantic field type validating a quantity of ``kind``."""

    def validate(value: Any) -> Any:
        return as_quantity(value, kind)

    schema = core_schema.no_info_plain_validator_function(
        validate,
        serialization=core_schema.plain_serializer_function_ser_schema(
            format_quantity, when_used="json-unless-none"
        ),
    )
    return Annotated[Any, GetPydanticSchema(lambda _tp, _handler: schema)]


#: Pydantic field types. Fields declared with these accept "8.42 mm"-style strings and
#: store canonical-unit Quantities; JSON serialization emits the same string form.
LengthQ = _quantity_type("length")
FrequencyQ = _quantity_type("frequency")
ImpedanceQ = _quantity_type("impedance")
AngleQ = _quantity_type("angle")

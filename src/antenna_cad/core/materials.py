"""Substrate material data.

A small built-in table covers the MVP; a fuller material database (loss vs. frequency,
vendor stackup kits) can replace it without changing the model.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class Substrate(BaseModel):
    """Dielectric substrate material.

    Parameters
    ----------
    name
        Vendor or common name, e.g. ``"RO4350B"``.
    eps_r
        Relative permittivity (design value at the datasheet reference frequency).
    tan_delta
        Loss tangent at the datasheet reference frequency.
    """

    model_config = ConfigDict(frozen=True)

    name: str
    eps_r: float = Field(gt=1.0)
    tan_delta: float = Field(ge=0.0)


RO4350B = Substrate(name="RO4350B", eps_r=3.66, tan_delta=0.0037)
FR4 = Substrate(name="FR4", eps_r=4.4, tan_delta=0.02)
AIR = Substrate(name="air", eps_r=1.0006, tan_delta=0.0)

SUBSTRATES: dict[str, Substrate] = {s.name: s for s in (RO4350B, FR4, AIR)}


def get_substrate(name: str) -> Substrate:
    """Look up a built-in substrate by name (case-insensitive).

    Examples
    --------
    >>> from antenna_cad.core.materials import get_substrate
    >>> get_substrate("RO4350B").eps_r
    3.66
    """
    for key, substrate in SUBSTRATES.items():
        if key.lower() == name.lower():
            return substrate
    raise KeyError(f"unknown substrate {name!r}; known: {sorted(SUBSTRATES)}")

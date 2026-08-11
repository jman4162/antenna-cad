"""PCB stackup: ordered copper and dielectric layers.

Layers are listed top to bottom. Copper layer names are the reference vocabulary for
all shapes, vias, and ports in a design.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator

from antenna_cad.core.materials import Substrate
from antenna_cad.core.units import LengthQ, Quantity


class CopperLayer(BaseModel):
    """A copper foil layer."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["copper"] = "copper"
    name: str
    thickness: LengthQ = Quantity(0.035, "mm")


class DielectricLayer(BaseModel):
    """A dielectric core or prepreg layer."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["dielectric"] = "dielectric"
    name: str
    material: Substrate
    thickness: LengthQ


class Stackup(BaseModel):
    """Ordered layer stack, top to bottom.

    Examples
    --------
    >>> from antenna_cad.core.materials import RO4350B
    >>> stackup = Stackup.two_layer(RO4350B, "0.508 mm")
    >>> [layer.name for layer in stackup.layers]
    ['top', 'core', 'bottom']
    """

    model_config = ConfigDict(frozen=True)

    layers: tuple[CopperLayer | DielectricLayer, ...]

    @model_validator(mode="after")
    def _check(self) -> Stackup:
        names = [layer.name for layer in self.layers]
        if len(names) != len(set(names)):
            raise ValueError(f"duplicate layer names in stackup: {names}")
        if not any(layer.kind == "copper" for layer in self.layers):
            raise ValueError("stackup has no copper layer")
        for first, second in zip(self.layers, self.layers[1:], strict=False):
            if first.kind == second.kind:
                raise ValueError(
                    f"adjacent layers {first.name!r} and {second.name!r} are both {first.kind}"
                )
        return self

    @property
    def copper_layers(self) -> tuple[CopperLayer, ...]:
        """Copper layers, top to bottom."""
        return tuple(layer for layer in self.layers if isinstance(layer, CopperLayer))

    @property
    def copper_names(self) -> tuple[str, ...]:
        """Names of the copper layers, top to bottom."""
        return tuple(layer.name for layer in self.copper_layers)

    def dielectric_between(self, upper: str, lower: str) -> DielectricLayer:
        """Return the single dielectric layer between two adjacent copper layers."""
        names = [layer.name for layer in self.layers]
        try:
            i, j = names.index(upper), names.index(lower)
        except ValueError as exc:
            raise KeyError(f"unknown layer in ({upper!r}, {lower!r}); stackup has {names}") from exc
        between = [
            layer for layer in self.layers[min(i, j) + 1 : max(i, j)] if layer.kind == "dielectric"
        ]
        if len(between) != 1:
            raise ValueError(
                f"expected exactly one dielectric between {upper!r} and {lower!r}, "
                f"found {[layer.name for layer in between]}"
            )
        assert isinstance(between[0], DielectricLayer)
        return between[0]

    @classmethod
    def two_layer(cls, substrate: Substrate, height: object, name: str = "core") -> Stackup:
        """Build the common two-copper-layer stackup on a single core.

        Parameters
        ----------
        substrate
            Core dielectric material.
        height
            Core thickness (any length quantity, e.g. ``"0.508 mm"``).
        name
            Name for the dielectric layer.
        """
        return cls(
            layers=(
                CopperLayer(name="top"),
                DielectricLayer(name=name, material=substrate, thickness=height),
                CopperLayer(name="bottom"),
            )
        )

"""The top-level physical design model.

``PhysicalDesign`` is the compiler's source of truth: geometry, stackup, nets, and
ports with enough semantics for backends to emit KiCad boards and solver models. It
round-trips through JSON/YAML and hashes deterministically, so revisions can be
compared and reproduced.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, model_validator

from antenna_cad.core.units import FrequencyQ, ImpedanceQ, Quantity
from antenna_cad.ir.geometry import BoardDefinition, PlanarShape, Via
from antenna_cad.ir.stackup import Stackup


class Net(BaseModel):
    """An electrical net.

    Names follow the slash-delimited path convention used across the stack
    (e.g. ``"array0/elem3/feed"``), so element identity survives into layout,
    simulation, and diagnosis tooling.
    """

    model_config = ConfigDict(frozen=True)

    name: str
    kind: Literal["rf", "ground", "power", "other"] = "rf"


class Port(BaseModel):
    """An excitation/measurement port on the board.

    ``position`` is in millimeters. ``layer`` carries the signal conductor;
    ``reference_layer`` is the return path (typically the ground plane under it).
    """

    model_config = ConfigDict(frozen=True)

    name: str
    net: str
    position: tuple[float, float]
    layer: str
    reference_layer: str
    z0: ImpedanceQ = Quantity(50.0, "ohm")


class PhysicalDesign(BaseModel):
    """A complete physical design: the unit all transforms and backends operate on."""

    model_config = ConfigDict(frozen=True)

    name: str
    frequency: FrequencyQ
    stackup: Stackup
    board: BoardDefinition
    nets: tuple[Net, ...] = ()
    shapes: tuple[PlanarShape, ...] = ()
    vias: tuple[Via, ...] = ()
    ports: tuple[Port, ...] = ()
    #: Synthesis parameters that produced this design (quantities as strings), kept for
    #: provenance and reports.
    parameters: dict[str, str | float | int] = {}

    @model_validator(mode="after")
    def _check_references(self) -> PhysicalDesign:
        copper = set(self.stackup.copper_names)
        net_names = {net.name for net in self.nets}
        for shape in self.shapes:
            if shape.layer not in copper:
                raise ValueError(f"shape on unknown copper layer {shape.layer!r}; have {copper}")
            if shape.net is not None and shape.net not in net_names:
                raise ValueError(f"shape references undeclared net {shape.net!r}")
        for via in self.vias:
            for layer in via.layers:
                if layer not in copper:
                    raise ValueError(f"via touches unknown copper layer {layer!r}")
            if via.net is not None and via.net not in net_names:
                raise ValueError(f"via references undeclared net {via.net!r}")
        for port in self.ports:
            if port.net not in net_names:
                raise ValueError(f"port {port.name!r} references undeclared net {port.net!r}")
            for layer in (port.layer, port.reference_layer):
                if layer not in copper:
                    raise ValueError(f"port {port.name!r} on unknown copper layer {layer!r}")
        return self

    # ------------------------------------------------------------- serialization
    def to_dict(self) -> dict[str, Any]:
        """Dump to plain JSON-compatible types (quantities and polygons as strings)."""
        result = self.model_dump(mode="json")
        assert isinstance(result, dict)
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PhysicalDesign:
        """Reconstruct a design from :meth:`to_dict` output."""
        return cls.model_validate(data)

    def to_yaml(self, path: str | Path | None = None) -> str:
        """Serialize to YAML; optionally also write it to ``path``."""
        text = yaml.safe_dump(self.to_dict(), sort_keys=True, allow_unicode=True)
        if path is not None:
            Path(path).write_text(text)
        return text

    @classmethod
    def from_yaml(cls, source: str | Path) -> PhysicalDesign:
        """Load a design from a YAML string or file path."""
        path = Path(source) if isinstance(source, Path) else None
        if path is None and isinstance(source, str) and "\n" not in source:
            candidate = Path(source)
            if candidate.exists():
                path = candidate
        text = path.read_text() if path is not None else str(source)
        return cls.from_dict(yaml.safe_load(text))

    def content_hash(self) -> str:
        """SHA-256 over the canonical serialized form.

        Identical designs hash identically regardless of construction order or the
        units their quantities were entered in (validation normalizes both).
        """
        canonical = json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode()).hexdigest()

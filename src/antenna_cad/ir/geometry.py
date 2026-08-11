"""Planar geometry primitives of the physical-design IR.

Coordinates are floats in **millimeters** in the board's XY plane; this is the IR's
single canonical geometry unit (unit-aware quantities appear at the API surface and
are converted on the way in). Polygons are :mod:`shapely` geometries; they validate on
construction and serialize as WKT with fixed precision so designs hash stably.
"""

from __future__ import annotations

from typing import Annotated, Any

import shapely
import shapely.wkt
from pydantic import BaseModel, ConfigDict, Field, GetPydanticSchema
from pydantic_core import core_schema
from shapely.geometry import Polygon
from shapely.geometry.polygon import orient

from antenna_cad.core.units import LengthQ

#: Digits after the decimal in serialized WKT: 1e-6 mm resolution (a nanometer),
#: far below fabrication tolerance, comfortably above float noise.
WKT_PRECISION = 6


def _validate_polygon(value: Any) -> Any:
    if isinstance(value, str):
        value = shapely.wkt.loads(value)
    if not isinstance(value, Polygon):
        # ValueError, not TypeError: pydantic only converts ValueError into a
        # ValidationError; a TypeError would escape model construction raw.
        raise ValueError(  # noqa: TRY004
            f"expected a Polygon or WKT string, got {type(value).__name__}"
        )
    if value.is_empty:
        raise ValueError("polygon is empty")
    if not value.is_valid:
        raise ValueError(f"invalid polygon: {shapely.is_valid_reason(value)}")
    # Canonical orientation (CCW exterior, CW holes) keeps WKT, and therefore content
    # hashes, independent of how the polygon was constructed.
    return orient(value)


def _polygon_wkt(value: Any) -> str:
    return str(shapely.wkt.dumps(value, rounding_precision=WKT_PRECISION, trim=True))


_polygon_schema = core_schema.no_info_plain_validator_function(
    _validate_polygon,
    serialization=core_schema.plain_serializer_function_ser_schema(
        _polygon_wkt, when_used="json-unless-none"
    ),
)

#: Pydantic field type for shapely polygons; accepts Polygon objects or WKT strings.
PolygonField = Annotated[Any, GetPydanticSchema(lambda _tp, _handler: _polygon_schema)]


class PlanarShape(BaseModel):
    """A polygon of copper (or keepout) on one layer, optionally bound to a net.

    Parameters
    ----------
    layer
        Name of a copper layer defined in the design's stackup.
    polygon
        Shape outline in millimeters.
    net
        Net name this copper belongs to, or ``None`` for unconnected geometry.
    role
        What the shape is, e.g. ``"radiator"``, ``"feed"``, ``"ground"``. Backends use
        it to choose representation (zone vs. pad) and reports use it for labeling.
    """

    model_config = ConfigDict(frozen=True)

    layer: str
    polygon: PolygonField
    net: str | None = None
    role: str = "copper"


class Via(BaseModel):
    """A plated through-hole connecting two copper layers.

    Position and sizes are in millimeters; ``drill`` must be smaller than ``diameter``.
    """

    model_config = ConfigDict(frozen=True)

    position: tuple[float, float]
    drill: LengthQ
    diameter: LengthQ
    layers: tuple[str, str]
    net: str | None = None

    def model_post_init(self, context: Any, /) -> None:
        """Check drill against pad diameter."""
        del context
        if self.drill.magnitude >= self.diameter.magnitude:
            raise ValueError(
                f"via drill {self.drill} must be smaller than its diameter {self.diameter}"
            )


class BoardDefinition(BaseModel):
    """Board outline (millimeters). Holes in the polygon become routed cutouts."""

    model_config = ConfigDict(frozen=True)

    outline: PolygonField
    name: str = Field(default="board")

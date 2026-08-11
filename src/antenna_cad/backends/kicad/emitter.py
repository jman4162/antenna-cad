"""Compile a ``PhysicalDesign`` into a KiCad board file (plus minimal project file).

Emission strategy, per the project plan:

- **Pinned format version** (KiCad 8-era, ``20240108``): KiCad reads older formats
  forward, so files open cleanly in KiCad 8/9/10, and ``kicad-cli pcb drc`` in CI
  doubles as a parse check against format drift.
- **Copper carries real nets.** Each connected shape becomes a footprint with a custom
  polygon pad bound to its net, so DRC and connectivity are meaningful (unlike bare
  ``gr_poly`` graphics). Ground planes become filled zones with the fill polygon
  precomputed from the IR.
- **Deterministic output**: UUIDs are derived from the design name and object path, so
  identical designs produce byte-identical files.

Coordinate note: the IR is y-up with origin at the board's lower-left; KiCad is y-down.
The emitter flips y about the board height.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from antenna_cad.backends.kicad.sexpr import SExpr, Sym, dumps
from antenna_cad.core.units import to_mm
from antenna_cad.ir import PhysicalDesign, PlanarShape, Stackup, Via

#: KiCad 8.0 board format stamp; KiCad 8/9/10 all read it.
FORMAT_VERSION = 20240108

#: Copper pullback from the routed board edge, applied only in KiCad emission.
#: KiCad flags copper coincident with Edge.Cuts even at zero edge clearance, and
#: fabricators want pullback from routed edges anyway; 10 um is far below any RF
#: effect at the frequencies this targets. The IR (and the solver geometry built
#: from it) keeps copper flush to the edge.
EDGE_PULLBACK_MM = 0.01

_UUID_NS = uuid.uuid5(uuid.NAMESPACE_URL, "https://github.com/jman4162/antenna-cad")

#: Fixed KiCad layer table entries used by every emitted board (2-layer MVP).
_LAYER_TABLE: list[tuple[int, str, str]] = [
    (0, "F.Cu", "signal"),
    (31, "B.Cu", "signal"),
    (36, "B.SilkS", "user"),
    (37, "F.SilkS", "user"),
    (38, "B.Mask", "user"),
    (39, "F.Mask", "user"),
    (44, "Edge.Cuts", "user"),
    (46, "B.CrtYd", "user"),
    (47, "F.CrtYd", "user"),
    (48, "B.Fab", "user"),
    (49, "F.Fab", "user"),
]


class KicadEmitError(ValueError):
    """The design uses a feature the KiCad emitter does not support yet."""


def _uid(design: PhysicalDesign, path: str) -> str:
    return str(uuid.uuid5(_UUID_NS, f"{design.name}/{path}"))


def _copper_layer_map(stackup: Stackup) -> dict[str, str]:
    names = stackup.copper_names
    if len(names) != 2:
        raise KicadEmitError(
            f"only 2-layer boards are supported for now, stackup has {len(names)} copper layers"
        )
    return {names[0]: "F.Cu", names[-1]: "B.Cu"}


def _xy(x: float, y: float) -> SExpr:
    return [Sym("xy"), float(x), float(y)]


def _pts(coords: list[tuple[float, float]]) -> SExpr:
    # Shapely rings repeat the first point at the end; KiCad point lists do not.
    if len(coords) > 1 and coords[0] == coords[-1]:
        coords = coords[:-1]
    return [Sym("pts"), *[_xy(x, y) for x, y in coords]]


class _Flip:
    """y-up IR coordinates -> y-down KiCad coordinates."""

    def __init__(self, board_height: float) -> None:
        self.h = board_height

    def __call__(self, coords: Any) -> list[tuple[float, float]]:
        return [(float(x), self.h - float(y)) for x, y in coords]

    def point(self, x: float, y: float) -> tuple[float, float]:
        return float(x), self.h - float(y)


def _pull_back(polygon: Any, board_outline: Any) -> Any:
    """Clip copper to the board outline eroded by :data:`EDGE_PULLBACK_MM`."""
    clipped = polygon.intersection(board_outline.buffer(-EDGE_PULLBACK_MM))
    if clipped.is_empty or clipped.geom_type != "Polygon":
        raise KicadEmitError(
            f"copper shape degenerated to {clipped.geom_type or 'nothing'} after edge pullback"
        )
    return clipped


def _net_table(design: PhysicalDesign) -> dict[str, int]:
    return {net.name: index for index, net in enumerate(design.nets, start=1)}


def _shape_footprint(
    design: PhysicalDesign,
    index: int,
    shape: PlanarShape,
    kicad_layer: str,
    net_number: int,
    flip: _Flip,
) -> SExpr:
    """Emit a connected copper polygon as a footprint with one custom-shaped pad.

    The pad anchors at the polygon's representative point (guaranteed interior);
    primitive coordinates are relative to that anchor.
    """
    polygon = _pull_back(shape.polygon, design.board.outline)
    anchor = polygon.representative_point()
    ax, ay = flip.point(anchor.x, anchor.y)

    def relative(coords: Any) -> list[tuple[float, float]]:
        return [(x - ax, y - ay) for x, y in flip(coords)]

    if list(polygon.interiors):
        raise KicadEmitError("copper polygons with holes are not supported yet")
    outline = relative(polygon.exterior.coords)

    pad: list[SExpr] = [
        Sym("pad"),
        "1",
        Sym("smd"),
        Sym("custom"),
        [Sym("at"), 0.0, 0.0],
        [Sym("size"), 0.1, 0.1],
        [Sym("layers"), kicad_layer],
        [Sym("net"), net_number, shape.net or ""],
        [Sym("uuid"), _uid(design, f"shape{index}/pad")],
        [Sym("options"), [Sym("clearance"), Sym("outline")], [Sym("anchor"), Sym("rect")]],
        [
            Sym("primitives"),
            [Sym("gr_poly"), _pts(outline), [Sym("width"), 0.0], [Sym("fill"), Sym("yes")]],
        ],
    ]
    return [
        Sym("footprint"),
        f"antenna_cad:{shape.role}_{index}",
        [Sym("layer"), kicad_layer],
        [Sym("uuid"), _uid(design, f"shape{index}/footprint")],
        [Sym("at"), ax, ay],
        [
            Sym("attr"),
            Sym("smd"),
            Sym("board_only"),
            Sym("exclude_from_pos_files"),
            Sym("exclude_from_bom"),
            Sym("allow_missing_courtyard"),
        ],
        pad,
    ]


def _ground_zone(
    design: PhysicalDesign,
    index: int,
    shape: PlanarShape,
    kicad_layer: str,
    net_number: int,
    flip: _Flip,
) -> SExpr:
    """Emit a ground plane as a filled zone whose fill is precomputed from the IR."""
    outline = flip(_pull_back(shape.polygon, design.board.outline).exterior.coords)
    return [
        Sym("zone"),
        [Sym("net"), net_number],
        [Sym("net_name"), shape.net or ""],
        [Sym("layer"), kicad_layer],
        [Sym("uuid"), _uid(design, f"shape{index}/zone")],
        [Sym("hatch"), Sym("edge"), 0.5],
        [Sym("connect_pads"), Sym("yes"), [Sym("clearance"), 0.0]],
        [Sym("min_thickness"), 0.25],
        [Sym("filled_areas_thickness"), Sym("no")],
        [Sym("fill"), Sym("yes"), [Sym("thermal_gap"), 0.5], [Sym("thermal_bridge_width"), 0.5]],
        [Sym("polygon"), _pts(outline)],
        [Sym("filled_polygon"), [Sym("layer"), kicad_layer], _pts(outline)],
    ]


def _via_expr(
    design: PhysicalDesign, index: int, via: Via, nets: dict[str, int], flip: _Flip
) -> SExpr:
    x, y = flip.point(*via.position)
    return [
        Sym("via"),
        [Sym("at"), x, y],
        [Sym("size"), to_mm(via.diameter)],
        [Sym("drill"), to_mm(via.drill)],
        [Sym("layers"), "F.Cu", "B.Cu"],
        [Sym("net"), nets.get(via.net or "", 0)],
        [Sym("uuid"), _uid(design, f"via{index}")],
    ]


def _edge_cuts(design: PhysicalDesign, flip: _Flip) -> SExpr:
    outline = flip(design.board.outline.exterior.coords)
    if list(design.board.outline.interiors):
        raise KicadEmitError("board outlines with cutouts are not supported yet")
    return [
        Sym("gr_poly"),
        _pts(outline),
        [Sym("stroke"), [Sym("width"), 0.05], [Sym("type"), Sym("default")]],
        [Sym("fill"), Sym("none")],
        [Sym("layer"), "Edge.Cuts"],
        [Sym("uuid"), _uid(design, "edge_cuts")],
    ]


def board_sexpr(design: PhysicalDesign) -> SExpr:
    """Build the full ``kicad_pcb`` expression tree for a design."""
    from antenna_cad._version import __version__

    layer_map = _copper_layer_map(design.stackup)
    nets = _net_table(design)
    _, _, _, maxy = design.board.outline.bounds
    minx, miny = design.board.outline.bounds[:2]
    if (minx, miny) != (0.0, 0.0):
        raise KicadEmitError("board outline must sit at origin (lower-left at 0,0)")
    flip = _Flip(maxy)

    total = sum(to_mm(layer.thickness) for layer in design.stackup.layers)

    layer_rows: list[SExpr] = [[Sym(str(num)), name, Sym(kind)] for num, name, kind in _LAYER_TABLE]
    net_rows: list[SExpr] = [[Sym("net"), number, name] for name, number in nets.items()]
    board: list[SExpr] = [
        Sym("kicad_pcb"),
        [Sym("version"), FORMAT_VERSION],
        [Sym("generator"), "antenna_cad"],
        [Sym("generator_version"), __version__.split("+")[0]],
        [Sym("general"), [Sym("thickness"), total], [Sym("legacy_teardrops"), Sym("no")]],
        [Sym("paper"), "A4"],
        [Sym("layers"), *layer_rows],
        [Sym("setup"), [Sym("pad_to_mask_clearance"), 0.0]],
        [Sym("net"), 0, ""],
        *net_rows,
    ]

    for index, shape in enumerate(design.shapes):
        kicad_layer = layer_map[shape.layer]
        net_number = nets.get(shape.net or "", 0)
        if shape.role == "ground":
            board.append(_ground_zone(design, index, shape, kicad_layer, net_number, flip))
        else:
            board.append(_shape_footprint(design, index, shape, kicad_layer, net_number, flip))

    board.extend(_via_expr(design, index, via, nets, flip) for index, via in enumerate(design.vias))
    board.append(_edge_cuts(design, flip))
    return board


#: Minimal project-file content. Two DRC severities are structural to this board
#: style and downgraded to ignore: ``isolated_copper`` (the ground plane has no via
#: or pad connection in the netlist; the RF launch connects it physically) and
#: ``lib_footprint_issues`` (board-embedded footprints have no library). Everything
#: else stays at KiCad defaults, so DRC still catches real problems.
_PROJECT_SETTINGS: dict[str, Any] = {
    "board": {
        "design_settings": {
            "rules": {"min_copper_edge_clearance": 0.0},
            "rule_severities": {
                "isolated_copper": "ignore",
                "lib_footprint_issues": "ignore",
            },
        }
    },
    "meta": {"filename": "", "version": 3},
}


def write_kicad_project(design: PhysicalDesign, directory: str | Path) -> Path:
    """Write ``<design.name>.kicad_pcb`` (and a minimal ``.kicad_pro``) into ``directory``.

    Returns the board file path.
    """
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    board_path = directory / f"{design.name}.kicad_pcb"
    board_path.write_text(dumps(board_sexpr(design)) + "\n")

    project = dict(_PROJECT_SETTINGS)
    project["meta"] = {"filename": f"{design.name}.kicad_pro", "version": 3}
    (directory / f"{design.name}.kicad_pro").write_text(json.dumps(project, indent=2) + "\n")
    return board_path

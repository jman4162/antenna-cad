"""Realize a patch array + corporate feed as a complete ``PhysicalDesign``.

Places patch cells on the lattice (mirroring rows the feed tree serves from above),
synthesizes the corporate feed between them, and merges everything into one
net-bound copper polygon over a full ground plane — the same IR shape the single
patch produces, so the KiCad emitter, DRC flow, and openEMS spec builder apply
unchanged.
"""

from __future__ import annotations

from shapely.affinity import translate as shapely_translate
from shapely.geometry import box
from shapely.ops import unary_union

from antenna_cad.core.units import to_hz, to_mm
from antenna_cad.elements.patch import GROUND_NET, RectangularPatch
from antenna_cad.feeds.corporate import FeedSynthesisError, build_corporate_feed
from antenna_cad.integrations.phased_array import ArrayLattice
from antenna_cad.ir import BoardDefinition, Net, PhysicalDesign, PlanarShape, Port, Stackup
from antenna_cad.transmission_lines.microstrip import SPEED_OF_LIGHT

ARRAY_NET = "array0/feed"


def realize_array(
    patch: RectangularPatch, lattice: ArrayLattice, name: str = "array"
) -> PhysicalDesign:
    """Build the full array design: placed patches, feed tree, ground, edge port."""
    problem = patch.problem
    h = to_mm(problem.substrate_height)
    lambda0_mm = SPEED_OF_LIGHT / to_hz(problem.center_frequency) * 1000
    margin = max(6 * h, lambda0_mm / 4)
    # The bottom margin also hosts the trunk: reserve room for the quarter-wave
    # transformer plus a usable 50-ohm run for the MSL simulation port.
    from antenna_cad.transmission_lines.cells import quarter_wave_length
    from antenna_cad.transmission_lines.microstrip import synthesize_width

    z0 = float(problem.impedance.magnitude)
    w_match = synthesize_width((z0 * z0 / 2) ** 0.5, h, problem.substrate_obj.eps_r)
    trunk_reserve = quarter_wave_length(
        to_hz(problem.center_frequency), w_match, h, problem.substrate_obj.eps_r
    ) + max(6 * h, 3.0)

    # Array extent in centered coordinates.
    half_w = to_mm(patch.width) / 2
    half_l = to_mm(patch.length) / 2
    min_x = min(e.position[0] for e in lattice.elements) - half_w
    max_x = max(e.position[0] for e in lattice.elements) + half_w
    min_y = min(e.position[1] for e in lattice.elements) - half_l
    max_y = max(e.position[1] for e in lattice.elements) + half_l

    y_bottom = min_y - margin - trunk_reserve
    feed = build_corporate_feed(patch, lattice, y_bottom)

    cells = [
        patch.cell_copper(element.position, mirrored=feed.mirrored[element.grid])
        for element in lattice.elements
    ]
    copper = unary_union([*cells, feed.polygon])
    if copper.geom_type != "Polygon":
        raise FeedSynthesisError(
            f"array copper did not merge into one polygon ({copper.geom_type}); "
            "feed arms are probably not reaching the patch edges"
        )
    if list(copper.interiors):
        raise FeedSynthesisError(
            "array copper contains holes, which backends do not support; check feed/patch overlaps"
        )

    # Shift to board coordinates: origin at lower-left, feed port on the y=0 edge.
    board_min_x = min(min_x, copper.bounds[0]) - margin
    board_max_x = max(max_x, copper.bounds[2]) + margin
    shift_x = -board_min_x
    shift_y = -y_bottom
    copper = shapely_translate(copper, xoff=shift_x, yoff=shift_y)
    board_w = board_max_x - board_min_x
    board_h = (max_y + margin) - y_bottom
    port_x = feed.port_xy[0] + shift_x

    # Electrical-length audit: normal arms equal; mirrored arms offset by the
    # half-wave compensation (which cancels the patch mirror in radiated phase).
    normal = sorted(a.electrical_length_mm for a in feed.arms if not a.mirrored)
    mirrored = sorted(a.electrical_length_mm for a in feed.arms if a.mirrored)
    for group, label in ((normal, "normal"), (mirrored, "mirrored")):
        if group and max(group) - min(group) > 0.05:
            raise FeedSynthesisError(
                f"{label} feed arms are not length-matched: spread "
                f"{max(group) - min(group):.3f} mm exceeds 0.05 mm"
            )

    return PhysicalDesign(
        name=name,
        frequency=problem.center_frequency,
        stackup=Stackup.two_layer(problem.substrate_obj, problem.substrate_height),
        board=BoardDefinition(outline=box(0, 0, board_w, board_h)),
        nets=(Net(name=ARRAY_NET), Net(name=GROUND_NET, kind="ground")),
        shapes=(
            PlanarShape(layer="top", polygon=copper, net=ARRAY_NET, role="radiator"),
            PlanarShape(
                layer="bottom", polygon=box(0, 0, board_w, board_h), net=GROUND_NET, role="ground"
            ),
        ),
        ports=(
            Port(
                name="p1",
                net=ARRAY_NET,
                position=(port_x, 0.0),
                layer="top",
                reference_layer="bottom",
                z0=problem.impedance,
            ),
        ),
        parameters={
            "array_nx": lattice.nx,
            "array_ny": lattice.ny,
            "array_dx": f"{lattice.dx_mm!r} mm",
            "array_dy": f"{lattice.dy_mm!r} mm",
            "patch_width": f"{to_mm(patch.width)!r} mm",
            "patch_length": f"{to_mm(patch.length)!r} mm",
            "inset_depth": f"{to_mm(patch.inset)!r} mm",
            "feed_width": f"{to_mm(patch.feed_width)!r} mm",
            "trunk_width": f"{feed.trunk_width_mm!r} mm",
            "n_elements": lattice.nx * lattice.ny,
        },
    )

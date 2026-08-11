"""Build a solver-independent simulation spec from a ``PhysicalDesign``.

The spec is plain JSON: geometry (copper polygons with z-heights, substrate block),
one excitation port, fixed mesh lines, frequency sweep, and far-field request. The
standalone runner (:mod:`antenna_cad.solvers.openems._runner`) consumes it inside the
openEMS environment (native or Docker) without importing antenna-cad, which keeps the
container image independent of this package.

Geometry mapping (units: millimeters, y-up, matching the IR):

- bottom copper sits at ``z = 0`` (zero-thickness PEC sheet),
- the substrate occupies ``0 <= z <= h``,
- top copper sits at ``z = h``,
- the air box pads the board laterally and vertically for radiation.
"""

from __future__ import annotations

import math
from typing import Any

from antenna_cad.core.units import to_hz, to_mm
from antenna_cad.ir import PhysicalDesign
from antenna_cad.solvers.base import SimulationConfig
from antenna_cad.transmission_lines.microstrip import SPEED_OF_LIGHT


class OpenEMSSpecError(ValueError):
    """The design cannot be expressed in the openEMS spec yet."""


def _mesh_thirds(edges: list[float], polygons: list[Any], axis: int, res: float) -> list[float]:
    """Third-rule mesh lines around metal edges.

    For each metal edge coordinate, one line goes ``res/3`` inside the metal and one
    ``2 res/3`` outside, the standard FDTD treatment for microstrip edge fields.
    ``axis`` is 0 for x-edges, 1 for y-edges.
    """
    from shapely.geometry import Point

    lines: list[float] = []
    probe = res / 10
    for edge in edges:
        for polygon in polygons:
            minx, miny, maxx, maxy = polygon.bounds
            mid = ((minx + maxx) / 2, (miny + maxy) / 2)
            inside_pt = Point(edge - probe, mid[1]) if axis == 0 else Point(mid[0], edge - probe)
            outside_pt = Point(edge + probe, mid[1]) if axis == 0 else Point(mid[0], edge + probe)
            covers_in = polygon.covers(inside_pt)
            covers_out = polygon.covers(outside_pt)
            if covers_in == covers_out:
                continue  # not an edge of this polygon at the sampled height
            sign = -1.0 if covers_in else 1.0  # direction pointing into the metal
            lines.append(edge + sign * res / 3)
            lines.append(edge - sign * 2 * res / 3)
            break
    return lines


#: Mesh lines closer than this (mm) merge into one. Two nearly-coincident lines make
#: the FDTD timestep collapse (dt scales with the smallest cell), so exact-value
#: dedupe is not enough.
MESH_MERGE_TOL_MM = 1e-3


def _merge_close(lines: list[float], tol: float = MESH_MERGE_TOL_MM) -> list[float]:
    """Sort mesh lines and merge groups closer than ``tol`` (keeping the first)."""
    merged: list[float] = []
    for line in sorted(lines):
        if not merged or line - merged[-1] > tol:
            merged.append(line)
    return merged


def _copper_entries(design: PhysicalDesign, h_mm: float) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    top_name = design.stackup.copper_names[0]
    for index, shape in enumerate(design.shapes):
        z = h_mm if shape.layer == top_name else 0.0
        if list(shape.polygon.interiors):
            raise OpenEMSSpecError("copper polygons with holes are not supported yet")
        entries.append(
            {
                "name": f"{shape.role}_{index}",
                "z": z,
                "polygon": [[float(x), float(y)] for x, y in shape.polygon.exterior.coords],
            }
        )
    return entries


def _msl_port_entry(
    design: PhysicalDesign, px: float, py: float, h_mm: float, resistance: float
) -> dict[str, Any]:
    """Build a microstrip-line port along the feed trace starting at the board edge.

    Measures the feed cross-section just inside the board to get the strip width and
    center, then extends the port along +y until the copper widens (the patch edge).
    The measurement plane sits halfway along that run, exciting the true microstrip
    mode instead of approximating the launch with a vertical lumped element.
    """
    from shapely.geometry import LineString

    miny = design.board.outline.bounds[1]
    if abs(py - miny) > 1e-6:
        raise OpenEMSSpecError(
            "the msl port model currently requires the port on the board's y=0 edge; "
            "use port_model='lumped' for other placements"
        )
    top_name = design.stackup.copper_names[0]
    feed_shapes = [s.polygon for s in design.shapes if s.layer == top_name]

    def cross_section(y: float) -> tuple[float, float] | None:
        minx, _, maxx, _ = design.board.outline.bounds
        cut = LineString([(minx - 1, y), (maxx + 1, y)])
        for poly in feed_shapes:
            seg = poly.intersection(cut)
            if not seg.is_empty and seg.geom_type == "LineString":
                x0, x1 = seg.bounds[0], seg.bounds[2]
                if x0 <= px <= x1:
                    return (x1 - x0), (x0 + x1) / 2
        return None

    probe = cross_section(py + 0.05)
    if probe is None:
        raise OpenEMSSpecError(f"no feed copper found at the port position ({px}, {py})")
    width, center = probe

    # Walk up the feed until the cross-section widens: that is the patch edge.
    step = 0.1
    y_end = py + step
    board_maxy = design.board.outline.bounds[3]
    while y_end < board_maxy:
        section = cross_section(y_end + step)
        if section is None or section[0] > 1.5 * width:
            break
        y_end += step

    length = y_end - py
    if length < 4 * h_mm:
        raise OpenEMSSpecError(
            f"feed line too short for an msl port ({length:.2f} mm); use port_model='lumped'"
        )
    return {
        "type": "msl",
        "resistance": resistance,
        "width": width,
        "center_x": center,
        "prop_span": [py, y_end],
        "z_top": h_mm,
        "feed_shift": min(2.0, length / 4),
        "meas_shift": length / 2,
    }


def build_spec(design: PhysicalDesign, config: SimulationConfig) -> dict[str, Any]:
    """Translate a design + config into the JSON simulation spec."""
    if len(design.ports) != 1:
        raise OpenEMSSpecError(f"exactly one port is supported, design has {len(design.ports)}")
    if len(design.stackup.copper_names) != 2:
        raise OpenEMSSpecError("only 2-layer designs are supported")

    f0 = to_hz(design.frequency)
    f_start = config.f_start or 0.6 * f0
    f_stop = config.f_stop or 1.4 * f0
    lambda0_mm = SPEED_OF_LIGHT / f0 * 1000

    core = design.stackup.dielectric_between(*design.stackup.copper_names)
    h_mm = to_mm(core.thickness)
    eps_r = core.material.eps_r
    # tan_delta -> conductivity at f0: kappa = 2 pi f eps0 eps_r tan_delta.
    kappa = 2 * math.pi * f0 * 8.8541878128e-12 * eps_r * core.material.tan_delta

    minx, miny, maxx, maxy = design.board.outline.bounds
    pad_xy = lambda0_mm / 8
    air_top = lambda0_mm / 4
    air_bottom = lambda0_mm / 8
    box = {
        "x": [minx - pad_xy, maxx + pad_xy],
        "y": [miny - pad_xy, maxy + pad_xy],
        "z": [-air_bottom, h_mm + air_top],
    }

    port = design.ports[0]
    px, py = port.position
    if config.port_model == "msl":
        port_entry = _msl_port_entry(design, px, py, h_mm, float(port.z0.magnitude))
    else:
        port_entry = {
            "type": "lumped",
            "resistance": float(port.z0.magnitude),
            "start": [px, py, 0.0],
            "stop": [px, py, h_mm],
            "direction": "z",
        }

    # Fixed mesh lines; the runner smooths between them in-engine.
    top_polys = [
        shape.polygon for shape in design.shapes if shape.layer == design.stackup.copper_names[0]
    ]
    edge_res = h_mm / 2
    x_edges = sorted({round(float(x), 6) for poly in top_polys for x, _ in poly.exterior.coords})
    y_edges = sorted({round(float(y), 6) for poly in top_polys for _, y in poly.exterior.coords})
    port_lines_x: list[float] = []
    port_lines_y: list[float] = []
    if port_entry["type"] == "msl":
        center, width = port_entry["center_x"], port_entry["width"]
        port_lines_x = [center - width / 4, center, center + width / 4]
        port_lines_y = [
            port_entry["prop_span"][0] + port_entry["feed_shift"],
            port_entry["prop_span"][0] + port_entry["meas_shift"],
            port_entry["prop_span"][1],
        ]
    mesh_x = _merge_close(
        [
            box["x"][0],
            minx,
            maxx,
            box["x"][1],
            px,
            *port_lines_x,
            *x_edges,
            *_mesh_thirds(x_edges, top_polys, 0, edge_res),
        ]
    )
    mesh_y = _merge_close(
        [
            box["y"][0],
            miny,
            maxy,
            box["y"][1],
            py,
            *port_lines_y,
            *y_edges,
            *_mesh_thirds(y_edges, top_polys, 1, edge_res),
        ]
    )
    substrate_z = [i * h_mm / 4 for i in range(5)]
    mesh_z = _merge_close([box["z"][0], *substrate_z, box["z"][1]])

    # Background resolution: lambda/20 in the dielectric at the top of the sweep.
    max_res = SPEED_OF_LIGHT / f_stop / math.sqrt(eps_r) * 1000 / 20

    return {
        "name": design.name,
        "unit": 1e-3,
        "frequency": {
            "f0": (f_start + f_stop) / 2,
            "fc": (f_stop - f_start) / 2,
            "f_start": f_start,
            "f_stop": f_stop,
            "n_freq": config.n_freq,
        },
        "end_criteria": config.end_criteria,
        "max_timesteps": config.max_timesteps,
        "boundaries": list(config.boundaries),
        "threads": config.threads,
        "box": box,
        "substrate": {
            "eps_r": eps_r,
            "kappa": kappa,
            "x": [minx, maxx],
            "y": [miny, maxy],
            "z": [0.0, h_mm],
        },
        "copper": _copper_entries(design, h_mm),
        "port": port_entry,
        "mesh": {"x": mesh_x, "y": mesh_y, "z": mesh_z, "max_res": max_res, "ratio": 1.4},
        "nf2ff": {
            "theta_deg": [
                -180 + i * config.theta_step_deg
                for i in range(int(360 / config.theta_step_deg) + 1)
            ],
            "phi_deg": list(config.phi_cuts_deg),
        },
    }

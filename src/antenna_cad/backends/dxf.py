"""DXF export of copper geometry (optional, ``pip install antenna-cad[dxf]``).

Writes each copper layer's polygons as closed lightweight polylines on a DXF layer of
the same name, plus the board outline on ``EDGE``. Useful for mechanical CAD handoff
and for photolithography/milling flows that skip Gerbers.
"""

from __future__ import annotations

from pathlib import Path

from antenna_cad.ir import PhysicalDesign


def write_dxf(design: PhysicalDesign, path: str | Path) -> Path:
    """Write the design's copper and outline to a DXF file (millimeters)."""
    try:
        import ezdxf
    except ImportError as exc:  # pragma: no cover - exercised only without the extra
        raise ImportError("DXF export needs the 'dxf' extra: pip install antenna-cad[dxf]") from exc

    doc = ezdxf.new("R2010", units=ezdxf.units.MM)  # type: ignore[attr-defined]
    msp = doc.modelspace()

    for name in ("EDGE", *design.stackup.copper_names):
        doc.layers.add(name.upper())

    msp.add_lwpolyline(
        list(design.board.outline.exterior.coords),
        close=True,
        dxfattribs={"layer": "EDGE"},
    )
    for shape in design.shapes:
        msp.add_lwpolyline(
            list(shape.polygon.exterior.coords),
            close=True,
            dxfattribs={"layer": shape.layer.upper()},
        )
        for interior in shape.polygon.interiors:
            msp.add_lwpolyline(
                list(interior.coords), close=True, dxfattribs={"layer": shape.layer.upper()}
            )

    path = Path(path)
    doc.saveas(path)
    return path

"""Array lattices, natively and from ``phased-array-modeling`` (PAM).

The physical-design layer consumes element positions as an :class:`ArrayLattice` —
positions in millimeters with explicit grid shape and flat-index ordering. Two ways
to build one:

- :func:`rectangular_lattice`: built-in, dependency-free. Reproduces PAM's
  ``create_rectangular_array`` positions exactly (mean-centering, ``indexing='ij'``
  ravel order: flat index ``i = ix * ny + iy``, x slowest) so taper and excitation
  vectors computed by PAM map one-to-one by flat index.
- :func:`from_phased_array`: wrap an existing ``phased_array.ArrayGeometry``
  (positions in **meters**; install via the ``pam`` extra). Note PAM factory spacing
  arguments are in wavelengths scaled by their ``wavelength`` keyword — pass
  ``wavelength=c/f`` explicitly there, since it defaults to 1.0.

Net names follow the arrayfault ``NodeId`` convention: slash-delimited paths like
``array0/e0_1/feed``.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, model_validator


def element_net(ix: int, iy: int, array: str = "array0") -> str:
    """Net name for the element at grid position (ix, iy).

    Examples
    --------
    >>> from antenna_cad.integrations.phased_array import element_net
    >>> element_net(0, 1)
    'array0/e0_1/feed'
    """
    return f"{array}/e{ix}_{iy}/feed"


class ElementPlacement(BaseModel):
    """One radiating element's spot on the lattice.

    ``position`` is (x, y) in millimeters relative to the array centroid; the array
    builder translates into board coordinates. ``index`` is the flat PAM-compatible
    index (``ix * ny + iy``).
    """

    model_config = ConfigDict(frozen=True)

    index: int
    grid: tuple[int, int]
    position: tuple[float, float]
    net: str


class ArrayLattice(BaseModel):
    """A rectangular element lattice with explicit grid metadata.

    PAM's ``ArrayGeometry`` intentionally drops grid shape (flat arrays only); this
    type carries ``(nx, ny)`` because feed-tree synthesis needs it.
    """

    model_config = ConfigDict(frozen=True)

    nx: int
    ny: int
    dx_mm: float
    dy_mm: float
    elements: tuple[ElementPlacement, ...]

    @model_validator(mode="after")
    def _check(self) -> ArrayLattice:
        if self.nx < 1 or self.ny < 1:
            raise ValueError(f"lattice must be at least 1x1, got {self.nx}x{self.ny}")
        if len(self.elements) != self.nx * self.ny:
            raise ValueError(f"expected {self.nx * self.ny} elements, got {len(self.elements)}")
        for element in self.elements:
            ix, iy = element.grid
            if element.index != ix * self.ny + iy:
                raise ValueError(
                    f"element {element.grid} has index {element.index}, "
                    f"expected {ix * self.ny + iy} (PAM flat ordering)"
                )
        return self

    def element_at(self, ix: int, iy: int) -> ElementPlacement:
        """Return the element at grid position (ix, iy)."""
        return self.elements[ix * self.ny + iy]


def rectangular_lattice(
    nx: int, ny: int, dx_mm: float, dy_mm: float, center: bool = True, array: str = "array0"
) -> ArrayLattice:
    """Build a rectangular lattice, position-identical to PAM's factory.

    Mirrors ``phased_array.create_rectangular_array``: positions on a grid with
    spacing (``dx_mm``, ``dy_mm``), mean-centered when ``center`` is true, flat
    ordering ``i = ix * ny + iy``.
    """
    xs = [i * dx_mm for i in range(nx)]
    ys = [j * dy_mm for j in range(ny)]
    if center:
        x_mean = sum(xs) / nx
        y_mean = sum(ys) / ny
        xs = [x - x_mean for x in xs]
        ys = [y - y_mean for y in ys]
    elements = tuple(
        ElementPlacement(
            index=ix * ny + iy,
            grid=(ix, iy),
            position=(xs[ix], ys[iy]),
            net=element_net(ix, iy, array),
        )
        for ix in range(nx)
        for iy in range(ny)
    )
    return ArrayLattice(nx=nx, ny=ny, dx_mm=dx_mm, dy_mm=dy_mm, elements=elements)


def from_phased_array(geometry: Any, nx: int, ny: int, array: str = "array0") -> ArrayLattice:
    """Wrap a ``phased_array.ArrayGeometry`` (positions in meters) as an ArrayLattice.

    The grid shape must be supplied because ``ArrayGeometry`` stores only flat
    coordinate arrays. Requires a planar, unthinned rectangular geometry whose
    ordering matches PAM's factory (x slowest); anything else is rejected rather
    than silently misassigned.
    """
    n = int(geometry.n_elements)
    if n != nx * ny:
        raise ValueError(f"geometry has {n} elements, expected {nx}*{ny}={nx * ny}")
    if not bool(geometry.is_planar):
        raise ValueError("conformal/3D geometries are not supported yet")

    x_mm = [float(v) * 1000.0 for v in geometry.x]
    y_mm = [float(v) * 1000.0 for v in geometry.y]

    # Verify PAM factory ordering (x slowest): y must repeat every ny elements and
    # x must be constant within each block of ny.
    for ix in range(nx):
        block = slice(ix * ny, (ix + 1) * ny)
        if max(x_mm[block]) - min(x_mm[block]) > 1e-9:
            raise ValueError(
                "element ordering does not match PAM rectangular-factory layout "
                "(x varies within a column block); thinned or reordered geometries "
                "are not supported yet"
            )

    dx_mm = x_mm[ny] - x_mm[0] if nx > 1 else 0.0
    dy_mm = y_mm[1] - y_mm[0] if ny > 1 else 0.0
    elements = tuple(
        ElementPlacement(
            index=ix * ny + iy,
            grid=(ix, iy),
            position=(x_mm[ix * ny + iy], y_mm[ix * ny + iy]),
            net=element_net(ix, iy, array),
        )
        for ix in range(nx)
        for iy in range(ny)
    )
    return ArrayLattice(nx=nx, ny=ny, dx_mm=dx_mm, dy_mm=dy_mm, elements=elements)

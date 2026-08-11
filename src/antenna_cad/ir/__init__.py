"""Physical-design intermediate representation."""

from antenna_cad.ir.design import Net, PhysicalDesign, Port
from antenna_cad.ir.geometry import BoardDefinition, PlanarShape, Via
from antenna_cad.ir.provenance import DesignRevision
from antenna_cad.ir.stackup import CopperLayer, DielectricLayer, Stackup

__all__ = [
    "BoardDefinition",
    "CopperLayer",
    "DesignRevision",
    "DielectricLayer",
    "Net",
    "PhysicalDesign",
    "PlanarShape",
    "Port",
    "Stackup",
    "Via",
]

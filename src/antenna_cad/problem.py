"""Design requirements: the entry point of the compiler.

A ``DesignProblem`` states what the antenna must do; synthesis turns it into a
``PhysicalDesign``. Every downstream artifact traces back to one of these.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from antenna_cad.core.materials import Substrate, get_substrate
from antenna_cad.core.units import FrequencyQ, ImpedanceQ, LengthQ, Quantity


class DesignProblem(BaseModel):
    """Requirements for a single-antenna design.

    Examples
    --------
    >>> from antenna_cad import DesignProblem
    >>> problem = DesignProblem(center_frequency="10 GHz")
    >>> problem.substrate_obj.name
    'RO4350B'
    """

    model_config = ConfigDict(frozen=True)

    center_frequency: FrequencyQ
    impedance: ImpedanceQ = Quantity(50.0, "ohm")
    substrate: str = "RO4350B"
    substrate_height: LengthQ = Quantity(0.508, "mm")
    polarization: str = "linear"

    @property
    def substrate_obj(self) -> Substrate:
        """The resolved substrate material."""
        return get_substrate(self.substrate)

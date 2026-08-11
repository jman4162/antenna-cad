"""Human-readable YAML design specs: the Git-friendly front door to the compiler.

Example spec:

.. code-block:: yaml

    design:
      name: x_band_patch
    requirements:
      center_frequency: 10 GHz
      impedance: 50 ohm
      substrate: RO4350B
      substrate_height: 0.508 mm
    element:
      type: rectangular_patch

Generated KiCad/Gerber/solver files are build artifacts; this spec (or the serialized
IR) is what belongs in version control.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import yaml
from pydantic import BaseModel, ConfigDict

from antenna_cad.problem import DesignProblem

if TYPE_CHECKING:
    from antenna_cad.ir import PhysicalDesign

TEMPLATE = """\
design:
  name: x_band_patch

requirements:
  center_frequency: 10 GHz
  impedance: 50 ohm
  substrate: RO4350B
  substrate_height: 0.508 mm
  polarization: linear

element:
  type: rectangular_patch
"""


class DesignSpec(BaseModel):
    """A parsed spec file: a named problem plus the element type to synthesize."""

    model_config = ConfigDict(frozen=True)

    name: str
    problem: DesignProblem
    element_type: str = "rectangular_patch"

    @classmethod
    def load(cls, path: str | Path) -> DesignSpec:
        """Load and validate a YAML spec file."""
        data = yaml.safe_load(Path(path).read_text())
        if not isinstance(data, dict) or "requirements" not in data:
            raise ValueError(f"{path}: expected a mapping with a 'requirements' section")
        name = str(data.get("design", {}).get("name", Path(path).stem))
        element = data.get("element", {})
        element_type = str(element.get("type", "rectangular_patch"))
        if element_type != "rectangular_patch":
            raise ValueError(
                f"{path}: element type {element_type!r} is not supported yet "
                "(only rectangular_patch)"
            )
        problem = DesignProblem.model_validate(data["requirements"])
        return cls(name=name, problem=problem, element_type=element_type)

    def synthesize(self) -> PhysicalDesign:
        """Synthesize the element and return the realized ``PhysicalDesign``."""
        from antenna_cad.elements import RectangularPatch

        return RectangularPatch.synthesize(self.problem).to_design(name=self.name)


def write_template(path: str | Path) -> Path:
    """Write a starter spec file."""
    path = Path(path)
    path.write_text(TEMPLATE)
    return path

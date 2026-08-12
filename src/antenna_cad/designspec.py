"""Human-readable YAML design specs: the Git-friendly front door to the compiler.

Example spec (single element; add an ``array:`` section for a corporate-fed array):

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
    array:            # optional
      nx: 2
      ny: 2
      spacing: 0.6 lambda

Generated KiCad/Gerber/solver files are build artifacts; this spec (or the serialized
IR) is what belongs in version control.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

from antenna_cad.core.units import as_quantity, to_hz, to_mm
from antenna_cad.problem import DesignProblem
from antenna_cad.transmission_lines.microstrip import SPEED_OF_LIGHT

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

_LAMBDA_SPACING = re.compile(r"^\s*([0-9.]+)\s*(?:lambda|λ)\s*$")


class ArraySection(BaseModel):
    """The ``array:`` section: rectangular lattice shape and element spacing.

    ``spacing`` accepts a length (``"18 mm"``) or a free-space-wavelength multiple
    (``"0.6 lambda"``), resolved against the design's center frequency. One value
    applies to both axes; give ``spacing_y`` to differ.
    """

    model_config = ConfigDict(frozen=True)

    nx: int = Field(ge=1)
    ny: int = Field(ge=1)
    spacing: str = "0.6 lambda"
    spacing_y: str | None = None

    @field_validator("spacing", "spacing_y")
    @classmethod
    def _parseable(cls, value: str | None) -> str | None:
        if value is not None:
            _resolve_spacing(value, 1e9)  # any frequency; validates the format
        return value

    def spacing_mm(self, frequency_hz: float) -> tuple[float, float]:
        """Resolve (dx, dy) in millimeters at the given frequency."""
        dx = _resolve_spacing(self.spacing, frequency_hz)
        dy = _resolve_spacing(self.spacing_y or self.spacing, frequency_hz)
        return dx, dy


def _resolve_spacing(text: str, frequency_hz: float) -> float:
    match = _LAMBDA_SPACING.match(text)
    if match:
        lambda0_mm = SPEED_OF_LIGHT / frequency_hz * 1000
        return float(match.group(1)) * lambda0_mm
    return to_mm(as_quantity(text, "length"))


class AcceptanceCriteria(BaseModel):
    """Pass/fail thresholds for verification and tuning.

    Defaults reproduce the previously hardcoded values: 5% resonance
    offset and -10 dB match for the report gate, 2% for tune convergence.
    """

    model_config = ConfigDict(frozen=True)

    #: Max fractional resonance offset |f_res - f0| / f0 for a report pass.
    freq_tolerance: float = 0.05
    #: Required S11 minimum (dB); the design must match at least this well.
    s11_max_db: float = -10.0
    #: Tighter fractional offset the tune loop iterates toward.
    tune_freq_tolerance: float = 0.02


class DesignSpec(BaseModel):
    """A parsed spec file: a named problem, element type, and optional array."""

    model_config = ConfigDict(frozen=True)

    name: str
    problem: DesignProblem
    element_type: str = "rectangular_patch"
    array: ArraySection | None = None
    acceptance: AcceptanceCriteria = AcceptanceCriteria()

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
        array = ArraySection.model_validate(data["array"]) if "array" in data else None
        acceptance = (
            AcceptanceCriteria.model_validate(data["acceptance"])
            if "acceptance" in data
            else AcceptanceCriteria()
        )
        return cls(
            name=name,
            problem=problem,
            element_type=element_type,
            array=array,
            acceptance=acceptance,
        )

    def synthesize(self) -> PhysicalDesign:
        """Synthesize and return the realized ``PhysicalDesign`` (element or array)."""
        from antenna_cad.elements import RectangularPatch

        patch = RectangularPatch.synthesize(self.problem)
        if self.array is None:
            return patch.to_design(name=self.name)

        from antenna_cad.arrays.layout import realize_array
        from antenna_cad.integrations.phased_array import rectangular_lattice

        dx, dy = self.array.spacing_mm(to_hz(self.problem.center_frequency))
        lattice = rectangular_lattice(self.array.nx, self.array.ny, dx, dy)
        return realize_array(patch, lattice, name=self.name)


def write_template(path: str | Path) -> Path:
    """Write a starter spec file."""
    path = Path(path)
    path.write_text(TEMPLATE)
    return path

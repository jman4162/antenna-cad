"""Compile antenna and phased-array design intent into simulation-ready KiCad PCB layouts."""

from antenna_cad._version import __version__
from antenna_cad.problem import DesignProblem

__all__ = ["DesignProblem", "__version__"]

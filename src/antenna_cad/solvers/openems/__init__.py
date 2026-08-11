"""openEMS (FDTD) solver backend."""

from antenna_cad.solvers.openems.solver import OpenEMS, OpenEMSNotAvailableError

__all__ = ["OpenEMS", "OpenEMSNotAvailableError"]

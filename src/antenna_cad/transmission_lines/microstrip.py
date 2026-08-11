"""Microstrip line analysis and synthesis.

Closed-form models: Hammerstad's effective-permittivity and impedance formulas for
analysis, and the Wheeler/Pozar formulas for width synthesis (Pozar, *Microwave
Engineering*, ch. 3). Accuracy is a few percent over the usual 0.1 < W/h < 10 range,
which is sufficient for first-pass geometry; full-wave simulation refines it.

These are pure functions on floats. ``width`` and ``height`` must share one length
unit (their ratio is what matters); frequencies are in hertz.
"""

from __future__ import annotations

import math

SPEED_OF_LIGHT = 299_792_458.0  # m/s


def effective_permittivity(width: float, height: float, eps_r: float) -> float:
    """Quasi-static effective permittivity of a microstrip line (Hammerstad).

    Examples
    --------
    >>> from antenna_cad.transmission_lines import effective_permittivity
    >>> round(effective_permittivity(3.0, 1.0, 2.2), 3)
    1.868
    """
    u = width / height
    if u <= 0:
        raise ValueError(f"width/height must be positive, got {u}")
    eps = (eps_r + 1) / 2 + (eps_r - 1) / 2 / math.sqrt(1 + 12 / u)
    if u < 1:
        eps += (eps_r - 1) / 2 * 0.04 * (1 - u) ** 2
    return eps


def characteristic_impedance(width: float, height: float, eps_r: float) -> float:
    """Characteristic impedance in ohms of a microstrip line (Hammerstad)."""
    u = width / height
    if u <= 0:
        raise ValueError(f"width/height must be positive, got {u}")
    eps = effective_permittivity(width, height, eps_r)
    if u <= 1:
        return 60 / math.sqrt(eps) * math.log(8 / u + u / 4)
    return 120 * math.pi / (math.sqrt(eps) * (u + 1.393 + 0.667 * math.log(u + 1.444)))


def synthesize_width(z0: float, height: float, eps_r: float) -> float:
    """Width (in the unit of ``height``) giving characteristic impedance ``z0`` ohms.

    Uses the closed-form synthesis formulas (Pozar eq. 3.197), then one check that the
    result lands in the branch it was computed for.
    """
    a = z0 / 60 * math.sqrt((eps_r + 1) / 2) + (eps_r - 1) / (eps_r + 1) * (0.23 + 0.11 / eps_r)
    u_narrow = 8 * math.exp(a) / (math.exp(2 * a) - 2)
    if u_narrow < 2:
        return u_narrow * height
    b = 377 * math.pi / (2 * z0 * math.sqrt(eps_r))
    u_wide = (
        2
        / math.pi
        * (
            b
            - 1
            - math.log(2 * b - 1)
            + (eps_r - 1) / (2 * eps_r) * (math.log(b - 1) + 0.39 - 0.61 / eps_r)
        )
    )
    return u_wide * height


def guided_wavelength(frequency_hz: float, width: float, height: float, eps_r: float) -> float:
    """Guided wavelength in meters at ``frequency_hz``."""
    eps = effective_permittivity(width, height, eps_r)
    return SPEED_OF_LIGHT / (frequency_hz * math.sqrt(eps))

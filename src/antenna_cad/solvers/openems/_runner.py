"""Standalone openEMS runner: executes a spec.json produced by ``spec.build_spec``.

This file is copied verbatim into each run directory and executed where the openEMS
Python bindings live (native install or the antenna-cad-openems Docker image). It
deliberately imports only the standard library, numpy, and openEMS/CSXCAD — never
antenna-cad — so the Docker image stays decoupled from the package.

Usage: ``python run_openems.py spec.json``. Results land next to the spec:
``results.npz`` (S-parameters, far field) and ``run.log``.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import numpy as np


def main(spec_path: str) -> int:
    """Build the CSXCAD model from the spec, run FDTD, and write results.npz."""
    from CSXCAD import ContinuousStructure
    from openEMS import openEMS

    spec = json.loads(Path(spec_path).read_text())
    sim_dir = Path(spec_path).resolve().parent
    freq = spec["frequency"]

    fdtd = openEMS(NrTS=spec["max_timesteps"], EndCriteria=spec["end_criteria"])
    fdtd.SetGaussExcite(freq["f0"], freq["fc"])
    fdtd.SetBoundaryCond(spec["boundaries"])

    csx = ContinuousStructure()
    fdtd.SetCSX(csx)
    mesh = csx.GetGrid()
    mesh.SetDeltaUnit(spec["unit"])

    sub = spec["substrate"]
    substrate = csx.AddMaterial("substrate", epsilon=sub["eps_r"], kappa=sub["kappa"])
    substrate.AddBox(
        priority=0,
        start=[sub["x"][0], sub["y"][0], sub["z"][0]],
        stop=[sub["x"][1], sub["y"][1], sub["z"][1]],
    )

    for entry in spec["copper"]:
        metal = csx.AddMetal(entry["name"])
        points = np.array(entry["polygon"]).T  # -> [[xs], [ys]]
        metal.AddPolygon(points, "z", entry["z"], priority=10)

    for axis in ("x", "y", "z"):
        lines = spec["mesh"][axis]
        gaps = np.diff(np.sort(np.asarray(lines, dtype=float)))
        if gaps.size and float(gaps.min()) < 5e-3:
            # A near-degenerate cell collapses the FDTD timestep (CFL) and the
            # excitation never completes; fail loudly instead of producing garbage.
            raise RuntimeError(
                f"degenerate {axis}-mesh: minimum line gap {gaps.min():.6f} mm; "
                "the spec builder should have merged these"
            )
        mesh.AddLine(axis, lines)
    mesh.SmoothMeshLines("all", spec["mesh"]["max_res"], spec["mesh"]["ratio"])

    port_spec = spec["port"]
    if port_spec["type"] == "msl":
        pec = csx.AddMetal("msl_port")
        half_w = port_spec["width"] / 2
        cx = port_spec["center_x"]
        y0, y1 = port_spec["prop_span"]
        # z runs top-of-substrate -> ground, exciting E downward (excite=-1), matching
        # the upstream MSL tutorial convention.
        start = [cx - half_w, y0, port_spec["z_top"]]
        stop = [cx + half_w, y1, 0.0]
        msl_kwargs = {
            "FeedShift": port_spec["feed_shift"],
            "MeasPlaneShift": port_spec["meas_shift"],
            "priority": 5,
        }
        try:
            port = fdtd.AddMSLPort(
                1,
                pec,
                start,
                stop,
                "y",
                "z",
                excite=-1,
                Feed_R=port_spec["resistance"],
                **msl_kwargs,
            )
        except TypeError:
            # Older bindings without Feed_R support.
            port = fdtd.AddMSLPort(1, pec, start, stop, "y", "z", excite=-1, **msl_kwargs)
    else:
        port = fdtd.AddLumpedPort(
            1,
            port_spec["resistance"],
            port_spec["start"],
            port_spec["stop"],
            port_spec["direction"],
            1.0,
            priority=5,
            edges2grid="xy",
        )

    nf2ff = fdtd.CreateNF2FFBox()

    run_kwargs = {"cleanup": True}
    if spec.get("threads"):
        # Older bindings lack the numThreads kwarg; fall back silently.
        try:
            fdtd.Run(str(sim_dir / "fdtd"), numThreads=spec["threads"], **run_kwargs)
        except TypeError:
            fdtd.Run(str(sim_dir / "fdtd"), **run_kwargs)
    else:
        fdtd.Run(str(sim_dir / "fdtd"), **run_kwargs)

    f = np.linspace(freq["f_start"], freq["f_stop"], freq["n_freq"])
    port.CalcPort(str(sim_dir / "fdtd"), f)
    s11 = port.uf_ref / port.uf_inc
    zin = port.uf_tot / port.if_tot
    p_in = 0.5 * np.real(port.uf_tot * np.conj(port.if_tot))

    # Search for resonance away from the sweep edges: the Gaussian excitation has
    # little energy there, so the S11 ratio is noise and can produce spurious dips.
    guard = max(1, len(f) // 10)
    s11_db = 20 * np.log10(np.abs(s11) + 1e-12)
    idx_res = guard + int(np.argmin(s11_db[guard:-guard]))
    f_res = float(f[idx_res])

    result: dict[str, Any] = {
        "f": f,
        "s11": s11,
        "zin": zin,
        "p_in": p_in,
        "f_res": f_res,
    }

    nf_spec = spec.get("nf2ff")
    if nf_spec:
        theta = np.array(nf_spec["theta_deg"])
        phi = np.array(nf_spec["phi_deg"])
        nf_res = nf2ff.CalcNF2FF(str(sim_dir / "fdtd"), f_res, theta, phi, center=[0, 0, 1e-3])
        E_norm = nf_res.E_norm[0] / np.max(nf_res.E_norm[0])
        result.update(
            {
                "theta_deg": theta,
                "phi_deg": phi,
                "e_norm": E_norm,
                "dmax": float(nf_res.Dmax[0]),
                "prad": float(nf_res.Prad[0]),
                "p_acc": float(np.interp(f_res, f, port.P_acc)),
            }
        )

    np.savez(sim_dir / "results.npz", **result)
    print(f"done: f_res={f_res / 1e9:.3f} GHz, |s11|min={np.abs(s11[idx_res]):.4f}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))

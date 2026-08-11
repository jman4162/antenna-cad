# Example: 2x2 corporate-fed patch array at 10 GHz

Four inset-fed patches on a 0.6 λ0 lattice, fed by a T-junction corporate tree:
50-ohm routing, 70.7-ohm quarter-wave transformers into each split, and a half-wave
phase trombone on the arms serving the mirrored (fed-from-above) row.

```bash
uv run antenna-cad layout examples/array_2x2_10ghz/spec.yaml -o build/array_2x2
uv run antenna-cad drc build/array_2x2/array_2x2_10ghz.kicad_pcb
uv run antenna-cad report examples/array_2x2_10ghz/spec.yaml -o build/array_2x2
```

The report step runs the openEMS FDTD verification (a few minutes per iteration in
the Docker runner; `--tune` runs up to four). The broadside main lobe in both
pattern cuts is the check that the mirror-row phase compensation is right — a phase
error splits the beam.

Measured (openEMS 0.37, Docker, `--tune`, 2026-08-10): f_res 10.12 GHz (1.2% from
target), S11 −14.8 dB, directivity 12.8 dBi, gain 11.7 dBi, single broadside lobe,
sidelobes below −13 dB.

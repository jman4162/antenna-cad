# Example: 2x2 corporate-fed patch array at 10 GHz

Four inset-fed patches on a 0.6 λ0 lattice, fed by a T-junction corporate tree:
50-ohm routing, 70.7-ohm quarter-wave transformers into each split, and a half-wave
phase trombone on the arms serving the mirrored (fed-from-above) row.

```bash
uv run antenna-cad layout examples/array_2x2_10ghz/spec.yaml -o build/array_2x2
uv run antenna-cad drc build/array_2x2/array_2x2_10ghz.kicad_pcb
uv run antenna-cad report examples/array_2x2_10ghz/spec.yaml -o build/array_2x2
```

The report step runs the openEMS FDTD verification (tens of minutes in the Docker
runner). Expected: a single broadside main lobe in both pattern cuts (this is the
check that the mirror-row phase compensation is right — a phase error splits the
beam), S11 below -10 dB near 10 GHz, and directivity around 11-13 dBi.

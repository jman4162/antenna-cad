# Example: 4x4 corporate-fed patch array at 10 GHz

Sixteen patches on a 0.6 λ0 lattice with a three-level corporate tree (columns →
rows → columns → elements), quarter-wave transformers at every split, and phase
trombones on mirrored rows.

```bash
uv run antenna-cad layout examples/array_4x4_10ghz/spec.yaml -o build/array_4x4
uv run antenna-cad drc build/array_4x4/array_4x4_10ghz.kicad_pcb
```

The full-wave run is hours-scale on a desktop CPU, so it is a manual step rather
than part of the automated example:

```bash
uv run antenna-cad report examples/array_4x4_10ghz/spec.yaml -o build/array_4x4
```

Expected: broadside beam, directivity around 17-19 dBi, first sidelobes near -13 dB
(uniform taper). Record measured metrics here after running.

# Example: 4x4 corporate-fed patch array at 10 GHz

Sixteen patches on a 0.6 λ0 lattice with a three-level corporate tree (columns →
rows → columns → elements), quarter-wave transformers at every split, and phase
trombones on mirrored rows.

| Board | S11 | Pattern |
|:---:|:---:|:---:|
| ![board](https://raw.githubusercontent.com/jman4162/antenna-cad/main/docs/images/array_4x4_top.png) | ![s11](https://raw.githubusercontent.com/jman4162/antenna-cad/main/docs/images/array_4x4_s11.png) | ![pattern](https://raw.githubusercontent.com/jman4162/antenna-cad/main/docs/images/array_4x4_pattern.png) |

```bash
uv run antenna-cad layout examples/array_4x4_10ghz/spec.yaml -o build/array_4x4
uv run antenna-cad drc build/array_4x4/array_4x4_10ghz.kicad_pcb
```

The full-wave run is hours-scale on a desktop CPU, so it is a manual step rather
than part of the automated example:

```bash
uv run antenna-cad report examples/array_4x4_10ghz/spec.yaml -o build/array_4x4
```

Measured (openEMS 0.37, Docker, 2026-08-10, untuned): f_res 9.68 GHz, directivity
16.8 dBi, gain 15.4 dBi, sharp broadside beam with E-plane first sidelobes near
-13 dB (H-plane shoulders around -8 dB from feed-network radiation). S11 tops out
near -8 dB (VSWR 2.3:1) regardless of frequency tuning: the three-level feed tree's
accumulated T-junction reactances and unmitered corners limit the match, where the
two-level 2x2 reaches -14.8 dB. Corner miters and junction compensation are the
known next steps; treat 4x4 boards as radiation-verified but match-limited in this
release.

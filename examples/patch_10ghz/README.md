# Example: 10 GHz inset-fed patch on RO4350B

The MVP acceptance workflow: one spec file in, a DRC-checked and full-wave-verified
KiCad board out. Run everything from the repository root.

| Board | S11 | Pattern |
|:---:|:---:|:---:|
| ![board](https://raw.githubusercontent.com/jman4162/antenna-cad/main/docs/images/patch_top.png) | ![s11](https://raw.githubusercontent.com/jman4162/antenna-cad/main/docs/images/patch_s11.png) | ![pattern](https://raw.githubusercontent.com/jman4162/antenna-cad/main/docs/images/patch_pattern.png) |

## 1. Synthesize and inspect

```bash
uv run antenna-cad synthesize examples/patch_10ghz/spec.yaml -o build/patch_10ghz
```

Prints the analytic dimensions (patch width/length, inset depth, feed width) and
writes the serialized design IR. Re-running produces the identical content hash.

## 2. Emit the KiCad board and check it

```bash
uv run antenna-cad layout examples/patch_10ghz/spec.yaml -o build/patch_10ghz
uv run antenna-cad drc build/patch_10ghz/patch_10ghz.kicad_pcb
```

Requires KiCad 8+ (`brew install --cask kicad` on macOS). The board opens in the
KiCad GUI like any hand-drawn design; copper carries real nets.

## 3. Simulate and produce the report

```bash
uv run antenna-cad report examples/patch_10ghz/spec.yaml -o build/patch_10ghz
```

Runs geometry checks, DRC, and the openEMS FDTD simulation (a few minutes on a
desktop CPU), then writes `report.md` with the S11 sweep, pattern cuts, board
render, metrics, and provenance. openEMS runs natively if its Python bindings are
installed, or in the container built with:

```bash
docker build -t antenna-cad-openems docker/
```

Expected result: resonance within a few percent of 10 GHz, S11 minimum well below
-10 dB, and broadside directivity near 7 dBi — typical for a single patch this size.

## 4. Manufacturing outputs

```bash
uv run antenna-cad export build/patch_10ghz/patch_10ghz.kicad_pcb -o build/patch_10ghz/fab --step
```

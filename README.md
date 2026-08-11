# antenna-cad

Compile antenna and phased-array design intent into simulation-ready KiCad PCB layouts.

antenna-cad is a Python design compiler for printed antennas. You describe requirements
(frequency, substrate, polarization, gain); it synthesizes geometry, writes a
DRC-checkable `.kicad_pcb`, simulates the layout with openEMS, and reports predicted
performance against the requirements. Every step is deterministic and runs headlessly,
with no KiCad GUI and no LLM in the loop. Agents can drive the same typed API, but
nothing depends on one.

## Status

Pre-alpha; the closed loop works end to end for single patches and corporate-fed
arrays. From a spec file, the toolchain synthesizes the geometry (patch dimensions,
T-junction feed tree with quarter-wave transformers and phase-compensated mirrored
rows), emits a KiCad board that passes DRC with zero violations, and verifies it
with openEMS FDTD. The 2x2 example, after simulation-feedback tuning (`--tune`):
resonance 10.12 GHz against a 10 GHz target, S11 -14.8 dB, directivity 12.8 dBi,
a single broadside beam. Lattice positions interoperate with
[phased-array-modeling](https://github.com/jman4162/Phased-Array-Antenna-Model);
an MCP server exposes the pipeline to agents. APIs are unstable.

```bash
uv run antenna-cad report examples/array_2x2_10ghz/spec.yaml -o build/array_2x2 --tune
```

## Design principles

- **Compiler, not file generator.** The source of truth is a typed internal
  representation of the design — geometry, stackup, nets, ports, constraints, units.
  KiCad, Gerber, and solver files are build artifacts compiled from it.
- **Deterministic core.** The same spec produces the same board, byte for byte.
  Verification runs through real engines: KiCad DRC (`kicad-cli`) and full-wave FDTD
  (openEMS).
- **Physical quantities carry units** (via pint). `10 GHz` and `8.42 mm` are values in
  the API; bare floats cross into backends only at explicit conversion boundaries.
- **Narrow scope by design.** This targets the structures printed antennas need
  (patches, microstrip lines, impedance transformers, feed trees, ground pours, via
  fences) rather than general PCB autorouting or schematic capture.

## Install

Not yet published. From a checkout:

```bash
uv sync --all-extras --group dev
```

KiCad 10 provides DRC and manufacturing export (`brew install kicad` on macOS).
openEMS setup is documented in `docs/` once the solver backend lands.

## License

MIT

# Changelog

All notable changes to antenna-cad are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow
[SemVer](https://semver.org/).

## [0.1.0] - 2026-08-10

### Added

- Corporate-fed patch arrays (2x2, 4x4, and single-row lattices): T-junction
  H-tree with quarter-wave transformers, mirrored-row phase compensation via
  symmetric-corner half-wave jogs, length-match auditing. The 2x2 example
  verifies end to end in openEMS: f_res 10.12 GHz, S11 -14.8 dB, directivity
  12.8 dBi, single broadside lobe.
- Array lattice adapter compatible with phased-array-modeling ([pam] extra),
  plus a dependency-free fallback verified position-identical to it.
- Simulation-feedback tuning for single patches and arrays (damped, divergence-
  guarded, matched-iterate selection); `report --tune`.
- MCP server ([mcp] extra, SDK 1.x/2.x compatible): spec/synthesize/layout/drc/
  simulate/report/export tools; `antenna-cad mcp serve`.
- Closed-loop MVP for a single rectangular patch: YAML spec → analytic synthesis
  (Hammerstad microstrip, Balanis patch with cos^4 inset correction) → typed IR →
  KiCad board emission (net-bound copper, DRC-clean under kicad-cli 10) → openEMS
  FDTD verification (native or Docker) → markdown report with S11/pattern plots.
- Simulation-feedback tuning (`report --tune`): corrects patch length and inset from
  measured resonance and input resistance.
- `antenna-cad` CLI: new, synthesize, layout, drc, simulate, report, export.
- Project scaffold: packaging, lint/type/test tooling, CI, prose checks.

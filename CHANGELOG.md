# Changelog

All notable changes to antenna-cad are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow
[SemVer](https://semver.org/).

## [Unreleased]

### Added

- Closed-loop MVP for a single rectangular patch: YAML spec → analytic synthesis
  (Hammerstad microstrip, Balanis patch with cos^4 inset correction) → typed IR →
  KiCad board emission (net-bound copper, DRC-clean under kicad-cli 10) → openEMS
  FDTD verification (native or Docker) → markdown report with S11/pattern plots.
- Simulation-feedback tuning (`report --tune`): corrects patch length and inset from
  measured resonance and input resistance.
- `antenna-cad` CLI: new, synthesize, layout, drc, simulate, report, export.
- Project scaffold: packaging, lint/type/test tooling, CI, prose checks.

# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project status

Early implementation of the MVP: a closed loop for a single rectangular microstrip
patch (synthesize → IR → layout → KiCad export → DRC → openEMS → report). The draft
spec lives in `BACKGROUND_INFORMATION_v1.local.md` (gitignored, local-only) and is the
source of truth for scope and architecture. The implementation plan with research
findings (KiCad emission strategy, openEMS toolchain, ecosystem APIs) is at
`~/.claude/plans/please-git-init-and-vivid-firefly.md`.

## Commands

```bash
uv sync --all-extras --group dev      # environment
uv run pytest                         # fast test suite (doctests included)
uv run pytest -m "slow"               # EM simulation tests
uv run pytest tests/test_foo.py::test_bar   # single test
uv run ruff check . && uv run ruff format --check .
uv run mypy                           # strict; scoped to src/antenna_cad
pre-commit run --all-files            # hooks: ruff, mypy, slopscore
scripts/slopcheck.sh                  # AI-slop prose lint (advisory; --strict for CI)
```

## Prose rule

Every piece of prose (README, docs, docstrings, commit messages) gets checked with
`scripts/slopcheck.sh` (slopscore-lint, profile `technical`). The script header lists
domain false positives ("critical angle", "dynamic range") — leave those alone.

## Key integration facts

- Array geometry comes from `phased-array-modeling` (import `phased_array`), source at
  `~/code/Phased-Array-Antenna-Model`. `ArrayGeometry` positions are in **meters**, but
  factory spacing args are in wavelengths scaled by a `wavelength` kwarg defaulting to
  1.0 — always pass `wavelength` explicitly. Reference adapter:
  `~/Documents/code/agentic-phased-array-builder/src/apab/pattern/wrappers_pam.py`.
- KiCad backend writes `.kicad_pcb` directly (typed, write-only S-expression emitter);
  never depend on the IPC API (needs a GUI until KiCad 11) or SWIG pcbnew (removed in
  11). All downstream checks go through `kicad-cli` (DRC json, gerbers, step, render).
- openEMS has no pip package; bindings build from a pinned openEMS-Project commit.
  Docker is the reproducible runner; macOS native uses the `vinn-ie/openems` tap.
- Element/net identity follows arrayfault's slash-delimited `NodeId` scheme
  (`~/Documents/code/phased-array-topology-model/src/arrayfault/ids.py`).

## Core architectural decisions (from the spec)

These are settled positions, not open questions:

- **Compiler, not file generator.** The source of truth is a versioned, typed internal
  representation (IR) of physical-design intent — never KiCad, HFSS, or Gerber files.
  External EDA/solver tools are compilation targets. Flow:
  `DesignSpec → EM intent → Physical Design IR → transforms → backend representation`.
- **Deterministic core, agent-optional.** All functionality must work without an LLM.
  Agents make topology decisions and call typed tools; they never emit raw copper
  geometry or edit `.kicad_pcb` files directly.
- **IR is semantically richer than KiCad.** A trace in the IR knows its impedance,
  symmetry group, electrical-length constraint, and reference plane — not just net,
  layer, and width.
- **Design changes are typed transforms and patches**, returning before/after hashes
  and changed-object lists. Agents emit schema-validated `DesignPatch` objects, never
  file rewrites. Full provenance (`DesignRevision` chain) for every artifact.
- **Topology vs. parameters split.** Agents/discrete optimizers choose topology (feed
  architecture, lattice, antenna family); numerical optimizers (SciPy/JAX) tune
  continuous dimensions. Don't ask an LLM to pick a trace length.
- **KiCad via its IPC API only** — the SWIG `pcbnew` bindings are deprecated. Headless
  operations (DRC, Gerber/drill/STEP export, rendering) go through `kicad-cli`.
- **Units are mandatory** on all physical quantities (pint-style); conversion happens
  explicitly at backend boundaries.
- **Integrate, don't absorb.** The user's existing packages stay separate:
  `phased-array-modeling` (array geometry/factors — consume via adapter, don't
  reimplement), `metasurface-py`, EdgeFEM, APAB. Simulation results use `xarray`
  datasets with explicit dimensions (frequency, port, element, theta, phi, ...).
  Feed networks convert to `scikit-rf` Networks for circuit analysis.
- **RF router, not a general PCB autorouter.** Deterministic templates first
  (bends, miters, tapers, Wilkinson, corporate trees), then constraint-based
  pathfinding, then optimization-assisted. Learned routing only after deterministic
  baselines and benchmarks exist.
- **Agent boundary is MCP + typed Python tools** with JSON-schema inputs, structured
  outputs, and artifact references (never large files in model context).
  OpenTelemetry for tracing. Strands is an optional adapter, not a dependency.
- **Approval gates:** an agent may advance a design through simulation states but must
  never mark it `MANUFACTURING_RELEASED` without an explicit user operation.

## v0.1 scope (keep it narrow)

One complete closed-loop workflow: rectangular microstrip patch → rectangular planar
array → equal-power corporate feed (microstrip, Wilkinson dividers, length matching,
ground plane, via fence) → KiCad/DXF export → KiCad DRC → openEMS simulation →
objective report. Two-layer and simple four-layer stackups. Integrations:
phased-array-modeling, scikit-rf, MCP. Resist adding antenna types before this loop
works end to end.

The intended package layout (`antenna_cad/core`, `ir`, `elements`,
`transmission_lines`, `feeds`, `arrays`, `routing`, `pcb`, `optimize`, `solvers`,
`backends`, `integrations`, `agent`, `telemetry`, `cli`) is in spec §30.

## Naming

"ApertureCAD" is taken (existing open-source antenna project); check PyPI/GitHub
availability before settling a public name.

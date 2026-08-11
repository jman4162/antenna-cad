"""Tests for the openEMS spec builder (no solver required)."""

import itertools
import json

import pytest

from antenna_cad import DesignProblem
from antenna_cad.elements import RectangularPatch
from antenna_cad.solvers import EMSolver, SimulationConfig
from antenna_cad.solvers.openems.spec import build_spec


@pytest.fixture
def design():
    return RectangularPatch.synthesize(DesignProblem(center_frequency="10 GHz")).to_design()


@pytest.fixture
def spec(design):
    return build_spec(design, SimulationConfig())


class TestSpecStructure:
    def test_json_serializable(self, spec):
        assert json.loads(json.dumps(spec))["name"] == "patch"

    def test_frequency_defaults(self, spec):
        f = spec["frequency"]
        assert f["f_start"] == pytest.approx(6e9)
        assert f["f_stop"] == pytest.approx(14e9)
        assert f["f0"] == pytest.approx(10e9)

    def test_substrate_block(self, spec):
        sub = spec["substrate"]
        assert sub["eps_r"] == pytest.approx(3.66)
        assert sub["z"] == [0.0, pytest.approx(0.508)]
        assert sub["kappa"] > 0  # RO4350B is lossy

    def test_copper_layers_at_correct_heights(self, spec):
        heights = {entry["name"].rsplit("_", 1)[0]: entry["z"] for entry in spec["copper"]}
        assert heights["radiator"] == pytest.approx(0.508)
        assert heights["ground"] == 0.0

    def test_msl_port_default(self, spec):
        port = spec["port"]
        assert port["type"] == "msl"
        assert port["resistance"] == 50.0
        assert port["z_top"] == pytest.approx(0.508)
        assert port["prop_span"][0] == 0.0
        assert port["prop_span"][1] > 4 * 0.508
        assert 0 < port["meas_shift"] < port["prop_span"][1]

    def test_lumped_port_opt_in(self, design):
        lumped = build_spec(design, SimulationConfig(port_model="lumped"))["port"]
        assert lumped["type"] == "lumped"
        assert lumped["start"][2] == 0.0
        assert lumped["stop"][2] == pytest.approx(0.508)

    def test_box_encloses_board_with_air(self, spec, design):
        minx, _miny, maxx, _maxy = design.board.outline.bounds
        assert spec["box"]["x"][0] < minx
        assert spec["box"]["x"][1] > maxx
        assert spec["box"]["z"][0] < 0
        assert spec["box"]["z"][1] > 0.508


class TestMeshLines:
    def test_mesh_covers_box(self, spec):
        for axis in ("x", "y", "z"):
            lines = spec["mesh"][axis]
            assert lines == sorted(lines)
            assert lines[0] == pytest.approx(spec["box"][axis][0])
            assert lines[-1] == pytest.approx(spec["box"][axis][1])

    def test_port_position_meshed(self, spec):
        px = spec["port"]["center_x"]
        assert any(abs(line - px) < 1e-6 for line in spec["mesh"]["x"])
        meas_y = spec["port"]["prop_span"][0] + spec["port"]["meas_shift"]
        assert any(abs(line - meas_y) < 0.1 for line in spec["mesh"]["y"])

    def test_thirds_lines_bracket_metal_edges(self, spec, design):
        # Each x-edge of the patch should have nearby refined lines on both sides.
        patch_poly = design.shapes[0].polygon
        minx = patch_poly.bounds[0]
        near = [line for line in spec["mesh"]["x"] if abs(line - minx) < 0.5 and line != minx]
        assert any(line < minx for line in near)
        assert any(line > minx for line in near)

    def test_substrate_z_resolved(self, spec):
        inside = [line for line in spec["mesh"]["z"] if 0 <= line <= 0.508]
        assert len(inside) >= 5


class TestProtocol:
    def test_openems_satisfies_emsolver(self):
        from antenna_cad.solvers.openems.solver import OpenEMS

        assert isinstance(OpenEMS.__new__(OpenEMS), EMSolver)

    def test_multiport_rejected(self, design):
        from antenna_cad.solvers.openems.spec import OpenEMSSpecError

        stripped = design.to_dict()
        stripped["ports"] = []
        from antenna_cad.ir import PhysicalDesign

        with pytest.raises(OpenEMSSpecError, match="exactly one port"):
            build_spec(PhysicalDesign.from_dict(stripped), SimulationConfig())


class TestMeshMerge:
    def test_close_lines_merge(self):
        from antenna_cad.solvers.openems.spec import _merge_close

        lines = [0.0, 10.290664, 10.290664365987631, 20.0]
        merged = _merge_close(lines)
        assert merged == [0.0, 10.290664, 20.0]

    def test_no_degenerate_spacing_in_built_spec(self, spec):
        for axis in ("x", "y", "z"):
            lines = spec["mesh"][axis]
            gaps = [b - a for a, b in itertools.pairwise(lines)]
            assert min(gaps) > 1e-3, f"degenerate {axis} mesh spacing: {min(gaps)}"

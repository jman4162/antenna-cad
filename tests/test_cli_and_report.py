"""Tests for the spec loader, verification loop, and CLI."""

import pytest
from typer.testing import CliRunner

from antenna_cad.cli import app
from antenna_cad.designspec import DesignSpec, write_template
from antenna_cad.report import verify_design

runner = CliRunner()


@pytest.fixture
def spec_file(tmp_path):
    return write_template(tmp_path / "spec.yaml")


class TestDesignSpec:
    def test_template_loads(self, spec_file):
        spec = DesignSpec.load(spec_file)
        assert spec.name == "x_band_patch"
        assert spec.problem.center_frequency.magnitude == 10.0

    def test_synthesize_produces_design(self, spec_file):
        design = DesignSpec.load(spec_file).synthesize()
        assert design.name == "x_band_patch"
        assert design.shapes

    def test_unknown_element_rejected(self, tmp_path):
        bad = tmp_path / "bad.yaml"
        bad.write_text("requirements:\n  center_frequency: 1 GHz\nelement:\n  type: helix\n")
        with pytest.raises(ValueError, match="helix"):
            DesignSpec.load(bad)

    def test_missing_requirements_rejected(self, tmp_path):
        bad = tmp_path / "bad.yaml"
        bad.write_text("design:\n  name: x\n")
        with pytest.raises(ValueError, match="requirements"):
            DesignSpec.load(bad)


class TestVerifyDesign:
    def test_loop_without_solver(self, spec_file, tmp_path):
        design = DesignSpec.load(spec_file).synthesize()
        report = verify_design(design, tmp_path / "out", solver=None)
        names = {step.name: step.status for step in report.steps}
        assert names["geometry"] == "pass"
        assert names["em_simulation"] == "skipped"
        assert (tmp_path / "out" / "report.md").exists()
        assert "kicad_pcb" in report.artifacts

    def test_report_mentions_all_steps(self, spec_file, tmp_path):
        design = DesignSpec.load(spec_file).synthesize()
        verify_design(design, tmp_path / "out", drc=False, solver=None)
        text = (tmp_path / "out" / "report.md").read_text()
        assert "geometry" in text
        assert "em_simulation" in text
        assert design.content_hash()[:16] in text


class TestCli:
    def test_new_and_synthesize(self, tmp_path):
        spec = tmp_path / "spec.yaml"
        result = runner.invoke(app, ["new", str(spec)])
        assert result.exit_code == 0, result.output
        result = runner.invoke(app, ["synthesize", str(spec), "-o", str(tmp_path / "build")])
        assert result.exit_code == 0, result.output
        assert "patch_width" in result.output
        assert (tmp_path / "build" / "x_band_patch.design.yaml").exists()

    def test_new_refuses_overwrite(self, tmp_path):
        spec = tmp_path / "spec.yaml"
        spec.write_text("x")
        result = runner.invoke(app, ["new", str(spec)])
        assert result.exit_code == 1

    def test_layout_writes_board(self, tmp_path):
        spec = tmp_path / "spec.yaml"
        runner.invoke(app, ["new", str(spec)])
        result = runner.invoke(app, ["layout", str(spec), "-o", str(tmp_path / "build")])
        assert result.exit_code == 0, result.output
        assert (tmp_path / "build" / "x_band_patch.kicad_pcb").exists()

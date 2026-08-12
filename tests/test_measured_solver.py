"""Tests for the measured-data solver and configurable acceptance criteria."""

from __future__ import annotations

from pathlib import Path

import pytest

from antenna_cad.designspec import AcceptanceCriteria, DesignSpec
from antenna_cad.solvers import EMSolver
from antenna_cad.solvers.measured import (
    MeasuredSolver,
    MeasurementContractError,
    load_sidecar,
)

FIXTURE = Path(__file__).parent / "fixtures" / "patch_28ghz_synthetic.s2p"


class TestContract:
    def test_sidecar_loads(self):
        prov = load_sidecar(FIXTURE)
        assert prov["synthetic"] is True
        assert "instrument" in prov

    def test_missing_sidecar_refused(self, tmp_path):
        bare = tmp_path / "bare.s2p"
        bare.write_text(FIXTURE.read_text())
        with pytest.raises(MeasurementContractError, match="sidecar"):
            MeasuredSolver(bare)

    def test_incomplete_sidecar_refused(self, tmp_path):
        data = tmp_path / "d.s2p"
        data.write_text(FIXTURE.read_text())
        (tmp_path / "d.meta.yaml").write_text("instrument: x\nsynthetic: false\n")
        with pytest.raises(MeasurementContractError, match="missing required"):
            MeasuredSolver(data)


class TestMeasuredSolver:
    def test_satisfies_the_protocol(self):
        assert isinstance(MeasuredSolver(FIXTURE), EMSolver)

    def test_result_shape_and_fixture_values(self):
        """The synthetic fixture dips to exactly -19.085 dB at 28 GHz."""
        solver = MeasuredSolver(FIXTURE)
        result = solver.simulate(design=None)  # design is ignored by contract

        assert result.metrics["f_res_hz"] == pytest.approx(28e9, rel=1e-9)
        assert result.metrics["s11_min_db"] == pytest.approx(-19.085, abs=0.01)
        assert "bandwidth_10db_hz" in result.metrics
        assert result.solver["name"] == "measured"
        assert result.solver["synthetic"] == "true"
        # s11_db helper works on the xarray shape
        assert float(result.s11_db().min()) == pytest.approx(-19.085, abs=0.01)

    def test_lazy_import_guard_stays_green(self):
        """Constructing the solver must not import scikit-rf; only
        simulate() may (mirrors tests/test_package.py)."""
        import subprocess
        import sys

        code = (
            "import sys; from antenna_cad.solvers.measured import MeasuredSolver; "
            f"MeasuredSolver(r'{FIXTURE}'); "
            "assert 'skrf' not in sys.modules, 'skrf imported at construction'"
        )
        subprocess.run([sys.executable, "-c", code], check=True)


class TestAcceptanceCriteria:
    def test_defaults_reproduce_hardcodes(self):
        c = AcceptanceCriteria()
        assert c.freq_tolerance == 0.05
        assert c.s11_max_db == -10.0
        assert c.tune_freq_tolerance == 0.02

    def test_spec_section_parses(self, tmp_path):
        spec = tmp_path / "d.yaml"
        spec.write_text(
            "design: {name: t}\n"
            "requirements: {center_frequency: 28 GHz}\n"
            "acceptance: {freq_tolerance: 0.01, s11_max_db: -15.0}\n"
        )
        loaded = DesignSpec.load(spec)
        assert loaded.acceptance.freq_tolerance == 0.01
        assert loaded.acceptance.s11_max_db == -15.0
        assert loaded.acceptance.tune_freq_tolerance == 0.02

    def test_spec_without_section_gets_defaults(self, tmp_path):
        spec = tmp_path / "d.yaml"
        spec.write_text("design: {name: t}\nrequirements: {center_frequency: 28 GHz}\n")
        assert DesignSpec.load(spec).acceptance == AcceptanceCriteria()


class TestVerifyWithMeasured:
    def test_measured_board_through_report_gate(self, tmp_path):
        """A 28 GHz design verified against the 28 GHz fixture passes; a
        tighter S11 criterion fails it — the gate is configurable."""
        from antenna_cad.elements import RectangularPatch
        from antenna_cad.problem import DesignProblem
        from antenna_cad.report import verify_design

        problem = DesignProblem(center_frequency="28 GHz")
        design = RectangularPatch.synthesize(problem).to_design(name="meas-test")
        solver = MeasuredSolver(FIXTURE)

        report = verify_design(design, tmp_path / "pass", drc=False, solver=solver)
        sim_step = next(s for s in report.steps if s.name == "em_simulation")
        assert sim_step.status == "pass"

        report2 = verify_design(
            design,
            tmp_path / "fail",
            drc=False,
            solver=solver,
            acceptance=AcceptanceCriteria(s11_max_db=-25.0),
        )
        sim_step2 = next(s for s in report2.steps if s.name == "em_simulation")
        assert sim_step2.status == "fail"

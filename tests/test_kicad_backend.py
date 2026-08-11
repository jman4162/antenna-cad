"""KiCad backend tests: S-expressions, emitted boards, and (if installed) real DRC."""

import pytest

from antenna_cad import DesignProblem
from antenna_cad.backends.kicad.cli import KicadCli, find_kicad_cli
from antenna_cad.backends.kicad.emitter import board_sexpr, write_kicad_project
from antenna_cad.backends.kicad.sexpr import Sym, dumps, fmt_mm
from antenna_cad.elements import RectangularPatch

needs_kicad = pytest.mark.skipif(find_kicad_cli() is None, reason="kicad-cli not installed")


@pytest.fixture
def design():
    return RectangularPatch.synthesize(DesignProblem(center_frequency="10 GHz")).to_design()


class TestSexpr:
    def test_atoms_and_quoting(self):
        assert dumps([Sym("net"), 1, "antenna/feed"]) == '(net 1 "antenna/feed")'

    def test_string_escaping(self):
        assert dumps([Sym("a"), 'say "hi"']) == '(a "say \\"hi\\"")'

    def test_nested_block_layout(self):
        text = dumps([Sym("a"), [Sym("b"), [Sym("c"), 1]]])
        assert text == "(a\n\t(b (c 1))\n)"

    def test_float_formatting(self):
        assert str(fmt_mm(1.230000)) == "1.23"
        assert str(fmt_mm(25.4)) == "25.4"
        assert str(fmt_mm(-0.0)) == "0"


class TestEmitter:
    def test_output_is_deterministic(self, design):
        assert dumps(board_sexpr(design)) == dumps(board_sexpr(design))

    def test_header_and_nets(self, design):
        text = dumps(board_sexpr(design))
        assert text.startswith("(kicad_pcb")
        assert "(version 20240108)" in text
        assert '(net 1 "antenna/feed")' in text
        assert '(net 2 "gnd")' in text

    def test_copper_carries_nets(self, design):
        text = dumps(board_sexpr(design))
        # Radiator: custom pad on F.Cu bound to the feed net.
        assert "(pad" in text
        assert "custom" in text
        # Ground: filled zone on B.Cu.
        assert "(zone" in text
        assert '(net_name "gnd")' in text

    def test_edge_cuts_present(self, design):
        assert '"Edge.Cuts"' in dumps(board_sexpr(design))

    def test_write_project_files(self, design, tmp_path):
        board = write_kicad_project(design, tmp_path)
        assert board.exists()
        assert (tmp_path / "patch.kicad_pro").exists()
        assert board.read_text().startswith("(kicad_pcb")

    def test_golden_snapshot(self, design, tmp_path, file_regression):
        board = write_kicad_project(design, tmp_path)
        file_regression.check(board.read_text(), extension=".kicad_pcb")


@needs_kicad
class TestKicadCliIntegration:
    @pytest.mark.kicad
    def test_drc_passes(self, design, tmp_path):
        board = write_kicad_project(design, tmp_path)
        report = KicadCli().drc(board)
        assert report.error_count == 0, report.summary() + "\n" + str(report.violations)
        assert not report.unconnected_items

    @pytest.mark.kicad
    def test_gerber_export(self, design, tmp_path):
        board = write_kicad_project(design, tmp_path)
        out = KicadCli().export_gerbers(board, tmp_path / "gerbers")
        gerbers = list(out.glob("*.g*"))
        assert gerbers, "no gerber files produced"


def test_dxf_export(design, tmp_path):
    ezdxf = pytest.importorskip("ezdxf")
    from antenna_cad.backends.dxf import write_dxf

    path = write_dxf(design, tmp_path / "patch.dxf")
    doc = ezdxf.readfile(path)
    layers = {layer.dxf.name for layer in doc.layers}
    assert {"EDGE", "TOP", "BOTTOM"} <= layers

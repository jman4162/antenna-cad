"""Tests for the physical-design IR: validation, serialization, hashing."""

import pytest
from shapely.geometry import Polygon, box

from antenna_cad.core.materials import FR4, RO4350B
from antenna_cad.ir import (
    BoardDefinition,
    Net,
    PhysicalDesign,
    PlanarShape,
    Port,
    Stackup,
    Via,
)


@pytest.fixture
def design() -> PhysicalDesign:
    return PhysicalDesign(
        name="patch_test",
        frequency="10 GHz",
        stackup=Stackup.two_layer(RO4350B, "0.508 mm"),
        board=BoardDefinition(outline=box(0, 0, 40, 40)),
        nets=(Net(name="antenna/feed"), Net(name="gnd", kind="ground")),
        shapes=(
            PlanarShape(
                layer="top", polygon=box(10, 10, 18.5, 20), net="antenna/feed", role="radiator"
            ),
            PlanarShape(layer="bottom", polygon=box(0, 0, 40, 40), net="gnd", role="ground"),
        ),
        vias=(
            Via(
                position=(5.0, 5.0),
                drill="0.3 mm",
                diameter="0.6 mm",
                layers=("top", "bottom"),
                net="gnd",
            ),
        ),
        ports=(
            Port(
                name="p1",
                net="antenna/feed",
                position=(14.25, 10.0),
                layer="top",
                reference_layer="bottom",
            ),
        ),
        parameters={"patch_width": "8.5 mm"},
    )


class TestStackup:
    def test_two_layer_structure(self):
        stackup = Stackup.two_layer(RO4350B, "0.508 mm")
        assert stackup.copper_names == ("top", "bottom")
        core = stackup.dielectric_between("top", "bottom")
        assert core.material.name == "RO4350B"
        assert core.thickness.magnitude == pytest.approx(0.508)

    def test_duplicate_names_rejected(self):
        from antenna_cad.ir.stackup import CopperLayer, DielectricLayer

        with pytest.raises(ValueError, match="duplicate"):
            Stackup(
                layers=(
                    CopperLayer(name="top"),
                    DielectricLayer(name="top", material=FR4, thickness="1 mm"),
                )
            )

    def test_adjacent_same_kind_rejected(self):
        from antenna_cad.ir.stackup import CopperLayer

        with pytest.raises(ValueError, match="both copper"):
            Stackup(layers=(CopperLayer(name="a"), CopperLayer(name="b")))


class TestGeometry:
    def test_invalid_polygon_rejected(self):
        bowtie = Polygon([(0, 0), (2, 2), (2, 0), (0, 2)])
        with pytest.raises(ValueError, match=r"[Ii]nvalid"):
            PlanarShape(layer="top", polygon=bowtie)

    def test_wkt_input_accepted(self):
        shape = PlanarShape(layer="top", polygon="POLYGON ((0 0, 1 0, 1 1, 0 1, 0 0))")
        assert shape.polygon.area == pytest.approx(1.0)

    def test_via_drill_must_be_smaller(self):
        with pytest.raises(ValueError, match="smaller"):
            Via(
                position=(0, 0),
                drill="0.6 mm",
                diameter="0.3 mm",
                layers=("top", "bottom"),
            )


class TestDesignValidation:
    def test_valid_design_builds(self, design):
        assert design.frequency.magnitude == 10.0

    def test_unknown_layer_rejected(self, design):
        data = design.to_dict()
        data["shapes"][0]["layer"] = "inner1"
        with pytest.raises(ValueError, match="unknown copper layer"):
            PhysicalDesign.from_dict(data)

    def test_undeclared_net_rejected(self, design):
        data = design.to_dict()
        data["ports"][0]["net"] = "nope"
        with pytest.raises(ValueError, match="undeclared net"):
            PhysicalDesign.from_dict(data)


class TestSerialization:
    def test_yaml_round_trip(self, design, tmp_path):
        path = tmp_path / "design.yaml"
        design.to_yaml(path)
        restored = PhysicalDesign.from_yaml(path)
        assert restored == design
        assert restored.content_hash() == design.content_hash()

    def test_dict_round_trip(self, design):
        assert PhysicalDesign.from_dict(design.to_dict()) == design

    def test_quantities_serialize_readably(self, design):
        data = design.to_dict()
        assert data["frequency"] == "10.0 GHz"
        assert data["vias"][0]["drill"] == "0.3 mm"


class TestContentHash:
    def test_stable_across_unit_spellings(self, design):
        data = design.to_dict()
        data["frequency"] = "10000 MHz"
        rebuilt = PhysicalDesign.from_dict(data)
        assert rebuilt.content_hash() == design.content_hash()

    def test_sensitive_to_geometry_change(self, design):
        data = design.to_dict()
        data["shapes"][0]["polygon"] = "POLYGON ((10 10, 18.6 10, 18.6 20, 10 20, 10 10))"
        changed = PhysicalDesign.from_dict(data)
        assert changed.content_hash() != design.content_hash()

    def test_polygon_orientation_normalized(self):
        cw = Polygon([(0, 0), (0, 1), (1, 1), (1, 0)])
        ccw = Polygon([(0, 0), (1, 0), (1, 1), (0, 1)])
        a = PlanarShape(layer="top", polygon=cw)
        b = PlanarShape(layer="top", polygon=ccw)
        assert a.model_dump(mode="json") == b.model_dump(mode="json")

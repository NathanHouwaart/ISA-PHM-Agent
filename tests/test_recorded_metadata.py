import copy
import json
from pathlib import Path

from isa_parser import ISAParser


def test_sensor_alias_reads_canonical_and_legacy_names():
    parser = ISAParser({"studies": []})
    for name in ("sensor_alias", "sensor alias"):
        assay = {"comments": [{"name": name, "value": "Accel"}]}
        assert parser._assay_alias(assay) == "Accel"
        assert parser._find_assay({"assays": [assay]}, "Accel") is assay


def test_ai_context_keeps_recorded_factor_names_without_semantic_mapping():
    parser = ISAParser({"identifier": "i", "studies": [{"identifier": "s", "title": "Study", "factors": [
        {"factorName": "Load - Axial", "factorType": {"annotationValue": "Operating condition"}},
        {"factorName": "My custom field", "factorType": {"annotationValue": "Other"}},
    ], "assays": [], "materials": {"samples": []}}]})
    context = parser.get_ai_context()
    assert [f["name"] for f in context["studies"][0]["factors"]] == ["Load - Axial", "My custom field"]
    assert "semantic_manifest" not in context
    assert parser._classify_factor({"factorName": "wear", "factorType": {"annotationValue": "Other"}}) == "other"


def test_sensor_compatibility_does_not_treat_fs_as_sampling_rate():
    fixture = Path(__file__).parent / "fixtures" / "diagnostic-signal-mini" / "i_investigation.json"
    data = json.loads(fixture.read_text(encoding="utf-8"))
    parser = ISAParser(copy.deepcopy(data))
    study = parser.data["studies"][0]
    alias = parser._assay_alias(study["assays"][0])
    assert parser.get_sensor_compatibility(study["title"], alias)["sampling_rate_hz"] == 25600
    parameter = next(p for p in study["protocols"][0]["parameters"] if p["parameterName"]["annotationValue"] == "Sampling Rate")
    parameter["parameterName"]["annotationValue"] = "fs"
    assert parser.get_sensor_compatibility(study["title"], alias)["sampling_rate_hz"] is None

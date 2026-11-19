"""Exercise the Agent's metadata tools with the bundled miniature dataset."""

import json
from pathlib import Path

import pytest

from isa_parser import load_from_file
from tools import execute_tool

FIXTURE = Path(__file__).parent / "fixtures" / "diagnostic-signal-mini" / "i_investigation.json"


@pytest.fixture(scope="module")
def parser():
    return load_from_file(str(FIXTURE))


@pytest.mark.parametrize("tool,arguments", [
    ("get_investigation_overview", {}),
    ("list_studies", {}),
    ("ai_context", {}),
    ("validate_dataset", {}),
    ("get_experiment_matrix", {}),
    ("get_label_coverage", {}),
    ("get_sensor_availability", {}),
    ("classify_phm_objective", {}),
    ("search_metadata", {"term": "vibration"}),
    ("get_study_details", {"study_title": "Mini Diagnostic Study"}),
    ("get_run_inventory", {"study_title": "Mini Diagnostic Study"}),
    ("get_protocol_details", {"study_title": "Mini Diagnostic Study"}),
    ("get_replication_gaps", {"study_title": "Mini Diagnostic Study"}),
    ("get_assay_details", {"study_title": "Mini Diagnostic Study", "sensor_alias": "mini-vibration"}),
    ("get_sensor_compatibility", {"study_title": "Mini Diagnostic Study", "sensor_alias": "mini-vibration"}),
    ("list_data_files", {"study_title": "Mini Diagnostic Study", "sensor_alias": "mini-vibration"}),
])
def test_metadata_tool_runs_without_error(parser, tool, arguments):
    result = json.loads(execute_tool(tool, {"dataset_name": "mini", **arguments}, {"mini": parser}))
    assert not (isinstance(result, dict) and result.get("error")), result

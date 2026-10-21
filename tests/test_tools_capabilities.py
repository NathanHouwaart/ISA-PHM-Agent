"""Regression tests for Agent-to-Wrapper capability decisions."""

from __future__ import annotations

import sys
import unittest
import json
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from isa_parser import load_from_file
from tools import _frequency_capability, execute_tool


FIXTURE = Path(__file__).parent / "fixtures" / "diagnostic-signal-mini" / "i_investigation.json"


class _Run:
    def __init__(self, capabilities):
        self._capabilities = capabilities

    def analysis_capabilities(self):
        return self._capabilities


class _Assay:
    def __init__(self, capabilities):
        self._capabilities = capabilities

    def analysis_capabilities(self):
        return self._capabilities

    def run(self, _run_id):
        return _Run(self._capabilities)


def _capabilities(*, available: bool, value: float | None = None, reason: str | None = None):
    return SimpleNamespace(
        frequency_domain=SimpleNamespace(available=available, reason=reason),
        sampling_frequency=SimpleNamespace(
            available=available, value=value, model_dump=lambda: {"available": available, "value": value},
        ),
    )


class FrequencyCapabilityTests(unittest.TestCase):
    def test_missing_sampling_rate_returns_structured_unavailable_result(self):
        fs, error = _frequency_capability(
            _Assay(_capabilities(available=False, reason="Sampling frequency is not provided.")),
            "run_01",
        )

        self.assertIsNone(fs)
        self.assertEqual(error["status"], "analysis_unavailable")
        self.assertIn("Sampling frequency", error["reason"])

    def test_explicit_sampling_rate_returns_hz_value(self):
        fs, error = _frequency_capability(
            _Assay(_capabilities(available=True, value=25_600.0)), "run_01"
        )

        self.assertEqual(fs, 25_600.0)
        self.assertIsNone(error)


class DiagnosticSignalMiniTests(unittest.TestCase):
    def test_parser_overview_uses_wrapper_public_summaries_when_attached(self):
        parser = load_from_file(str(FIXTURE))

        overview = parser.get_investigation_overview()
        studies = parser.list_studies()

        self.assertEqual(overview["number_of_studies"], 1)
        self.assertEqual(studies[0]["identifier"], "mini-study-001")
        self.assertEqual(studies[0]["number_of_assays"], 1)

    def test_parser_study_and_assay_details_use_wrapper_structure(self):
        parser = load_from_file(str(FIXTURE))

        study = parser.get_study_details("Mini Diagnostic Study")
        assay = parser.get_assay_details("Mini Diagnostic Study", "mini-vibration")

        self.assertEqual(study["identifier"], "mini-study-001")
        self.assertEqual(assay["measurement_type"], "Vibration")
        self.assertEqual(assay["number_of_data_files"], 2)

    def test_data_file_inventory_uses_wrapper_run_summaries(self):
        parser = load_from_file(str(FIXTURE))

        files = parser.list_data_files("Mini Diagnostic Study", "mini-vibration")

        self.assertEqual(len(files), 2)
        self.assertTrue(all(row["type"] == "Processed Data File" for row in files))
        self.assertTrue(all(row["file"].endswith(".csv") for row in files))

    def test_fixture_exposes_frequency_domain_capability(self):
        parser = load_from_file(str(FIXTURE))
        result = json.loads(execute_tool(
            "get_analysis_capabilities",
            {
                "dataset_name": "mini",
                "study_title": "Mini Diagnostic Study",
                "sensor_alias": "mini-vibration",
            },
            {"mini": parser},
        ))

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["scope"], "assay")
        self.assertTrue(result["capabilities"]["frequency_domain"]["available"])
        self.assertEqual(result["capabilities"]["sampling_frequency"]["value"], 25_600.0)

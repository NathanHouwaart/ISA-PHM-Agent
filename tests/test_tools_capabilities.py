"""Regression tests for Agent-to-Wrapper capability decisions."""

from __future__ import annotations

import sys
import unittest
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from isa_parser import load_from_file
from tools import FIGURE_REGISTRY, _compare_lifecycle_plot, _frequency_capability, _serialize_wrapper_result, _wrapper_api_reference, execute_tool


FIXTURE = Path(__file__).parent / "fixtures" / "diagnostic-signal-mini" / "i_investigation.json"


class SignalSourceTests(unittest.TestCase):
    def _assay(self):
        import pandas as pd

        class Assay:
            def __init__(self):
                self.requested = []

            def list_runs(self):
                return [SimpleNamespace(run_id="run_01")]

            def run(self, run_id):
                return SimpleNamespace(analysis_capabilities=lambda: SimpleNamespace(measured_unit={"value": "G", "available": True}))

            def load_dataframe_with_meta(self, run_id, file_type):
                self.requested.append(file_type)
                resolved = "processed" if file_type == "auto" else file_type
                return pd.DataFrame({"time": [0, 1, 2, 3], "value": [1., 2., 3., 4.]}), {"resolved_file_type": resolved, "file_path": f"{resolved}.csv"}

            def load_dataframe(self, run_id, file_type):
                self.requested.append(file_type)
                return pd.DataFrame({"time": [0, 1, 2, 3], "value": [1., 2., 3., 4.]})

            def fix_outliers(self, df, **kwargs):
                return df

        return Assay()

    def test_load_reports_actual_processed_source(self):
        assay = self._assay()
        with patch("tools._resolve_assay_proxy", return_value=(assay, None)):
            result = json.loads(execute_tool("load_run_csv", {"dataset_name": "d", "study_title": "s", "sensor_alias": "a"}, {"d": SimpleNamespace(wrapper=object())}))
        self.assertEqual(result["source"], "processed_file")
        self.assertEqual(result["load_meta"]["resolved_file_type"], "processed")
        self.assertEqual(result["recorded_measurement_unit"]["value"], "G")

    def test_cleaning_really_starts_from_raw(self):
        assay = self._assay()
        with patch("tools._resolve_assay_proxy", return_value=(assay, None)):
            result = json.loads(execute_tool("process_signal", {"dataset_name": "d", "study_title": "s", "sensor_alias": "a", "fix_outliers": {}}, {"d": SimpleNamespace(wrapper=object())}))
        self.assertEqual(result["status"], "ok")
        self.assertEqual(assay.requested, ["raw"])

    def test_explicit_raw_bypasses_existing_working_copy(self):
        import pandas as pd
        assay = self._assay()
        cached = {("d", "s", "a", "run_01"): {"df": pd.DataFrame({"time": [0], "value": [99.]}), "transforms": []}}
        with patch("tools._resolve_assay_proxy", return_value=(assay, None)):
            result = json.loads(execute_tool("load_run_csv", {"dataset_name": "d", "study_title": "s", "sensor_alias": "a", "file_type": "raw"}, {"d": SimpleNamespace(wrapper=object())}, working_copies=cached))
        self.assertEqual(result["source"], "raw_file")
        self.assertEqual(assay.requested, ["raw"])


class ValidationCoverageTests(unittest.TestCase):
    def test_validation_describes_its_partial_coverage(self):
        parser = load_from_file(str(FIXTURE))
        result = parser.validate_dataset()
        self.assertEqual(result["coverage"]["status"], "partial")
        self.assertIn("complete ISA-PHM specification", result["coverage"]["not_checked"])
        self.assertNotEqual(result["gate_summary"]["1_structural"], "pass")
        self.assertNotEqual(result["status"], "pass")

    def test_invalid_explicit_file_never_falls_back_to_last_run(self):
        parser = load_from_file(str(FIXTURE))
        base = {"dataset_name": "mini", "study_title": "Mini Diagnostic Study",
                "sensor_alias": "mini-vibration", "relative_path": "missing-run.csv"}
        cases = [
            ("load_run_csv", base),
            ("get_analysis_capabilities", base),
            ("make_plot", {**base, "kind": "timeseries"}),
            ("call_wrapper_function", {**base, "target": "run", "method": "overview"}),
        ]
        for name, args in cases:
            with self.subTest(tool=name):
                result = json.loads(execute_tool(name, args, {"mini": parser}))
                self.assertIn("matches path", result["error"])

    def test_grouped_plot_delegates_to_wrapper_and_reports_errors(self):
        from tools import _build_multi_lifecycle
        calls = []
        study = SimpleNamespace(plot_sensor_features=lambda **kw: calls.append(kw) or "figure")
        self.assertEqual(_build_multi_lifecycle(study, "rms", "raw"), "figure")
        self.assertEqual(calls, [{"feature": "rms", "file_type": "raw", "n_workers": 2}])
        def fail(**_kwargs):
            raise ValueError('different units')
        self.assertIn('different units', _build_multi_lifecycle(SimpleNamespace(plot_sensor_features=fail), 'rms')['error'])

    def test_timeline_plot_exposes_approximation_and_raw_source(self):
        from bokeh.layouts import column
        from bokeh.models import Div
        calls = []
        run = SimpleNamespace(plot_with_operating_conditions=lambda **kw: calls.append(kw) or column(Div(text='Plot')))
        assay = SimpleNamespace(
            run=lambda number: run,
            list_runs=lambda: [SimpleNamespace(run_id='run_02', raw_file_path='raw.csv', processed_file_path=None)],
        )
        parser = SimpleNamespace(wrapper=object(), get_run_id_for_path=lambda *args: 'run_02')
        args = {'dataset_name': 'mini', 'kind': 'sensor_with_operating_conditions',
                'study_title': 'Study', 'sensor_alias': 'Sensor', 'relative_path': 'raw.csv',
                'file_type': 'raw', 'alignment': 'first_sample'}
        with patch('tools._resolve_assay_proxy', return_value=(assay, None)):
            result = json.loads(execute_tool('make_plot', args, {'mini': parser}))
        self.assertEqual(calls, [{'file_type': 'raw', 'alignment': 'first_sample'}])
        self.assertEqual(result['source'], {'type': 'raw', 'file_path': 'raw.csv'})
        self.assertIn('not verified synchronization', result['timing_note'])
        self.assertIn(result['plot_id'], FIGURE_REGISTRY)

    def test_multi_sensor_plot_reports_units_and_distinct_run_numbers(self):
        from bokeh.plotting import figure
        summaries = [SimpleNamespace(assay_id='a', sensor_alias='Sensor A', n_runs=2),
                     SimpleNamespace(assay_id='b', sensor_alias='Sensor B', n_runs=2)]
        assay = SimpleNamespace(list_runs=lambda: [SimpleNamespace(run_number=1), SimpleNamespace(run_number=2)],
                                analysis_capabilities=lambda: SimpleNamespace(measured_unit=SimpleNamespace(available=True, value='fm')))
        study = SimpleNamespace(list_assays=lambda: summaries, assay=lambda _id: assay)
        parser = SimpleNamespace(wrapper=object())
        args = {'dataset_name': 'mini', 'kind': 'multi_lifecycle', 'study_title': 'Study', 'feature': 'rms', 'file_type': 'raw'}
        with patch('tools._resolve_study_proxy', return_value=(study, None)), patch('tools._build_multi_lifecycle', return_value=figure()):
            result = json.loads(execute_tool('make_plot', args, {'mini': parser}))
        self.assertEqual(result['measured_unit'], 'fm')
        self.assertEqual(result['measurement_count'], 4)
        self.assertEqual(result['run_numbers'], [1, 2])
        self.assertIn('not distinct runs', result['count_note'])


class CrossStudyLifecyclePlotTests(unittest.TestCase):
    @staticmethod
    def _parser(missing=False, mismatch=False, failure=False):
        import pandas as pd
        class Assay:
            def __init__(self, unit, bad): self.unit, self.bad = unit, bad
            def analysis_capabilities(self):
                return SimpleNamespace(measured_unit=SimpleNamespace(available=True, value=self.unit))
            def lifecycle_features(self, file_type):
                return pd.DataFrame([{"run_id": "run_01", "run_number": 1, "rms": 1.0, "resolved_file_type": "raw", "error": None}, {"run_id": "run_02", "run_number": 2, "rms": float('nan') if self.bad else 2.0, "resolved_file_type": "raw", "error": "missing file" if self.bad else None}])
        class Study:
            def __init__(self, study): self.study = study
            def list_assays(self):
                names = ["axial"] if missing and self.study == "B" else ["axial", "radial"]
                return [SimpleNamespace(sensor_alias=n, assay_id=n, quantity_kind_identifier="acceleration") for n in names]
            def assay(self, alias): return Assay("m/s2" if mismatch and self.study == "B" else "G", failure and alias == "axial" and self.study == "B")
        return SimpleNamespace(wrapper=SimpleNamespace(study=lambda title: Study(title)))

    def test_four_curves_one_plot(self):
        result = _compare_lifecycle_plot(self._parser(), {"study_titles": ["A", "B"], "sensor_aliases": ["axial", "radial"]}, "dataset")
        self.assertEqual(len(result["curves"]), 4)
        self.assertEqual(result["missing"], [])
        plot = FIGURE_REGISTRY[result["plot_id"]]["figure"]
        self.assertEqual(len(plot.legend[0].items), 4)
        self.assertIn("G", plot.yaxis[0].axis_label)

    def test_missing_sensor_and_failed_run_are_reported(self):
        result = _compare_lifecycle_plot(self._parser(missing=True, failure=True), {"study_titles": ["A", "B"], "sensor_aliases": ["axial", "radial"]}, "dataset")
        self.assertEqual(len(result["curves"]), 3)
        self.assertTrue(any(item.get("run_id") == "run_02" and "missing file" in item["reason"] for item in result["missing"]))
        self.assertTrue(any(item["sensor"] == "radial" and item["study"] == "B" for item in result["missing"]))

    def test_mismatched_units_are_not_plotted(self):
        result = _compare_lifecycle_plot(self._parser(mismatch=True), {"study_titles": ["A", "B"]}, "dataset")
        self.assertIn("different measured units", result["error"])
        self.assertNotIn("plot_id", result)


class FeatureTableIntegrationTests(unittest.TestCase):
    def test_agent_dispatches_feature_table_and_keeps_exclusion_report(self):
        parser = load_from_file(str(FIXTURE))
        result = json.loads(execute_tool(
            "call_wrapper_function",
            {"dataset_name": "mini", "target": "assay", "study_title": "Mini Diagnostic Study", "sensor_alias": "mini-vibration", "method": "feature_table", "arguments": {"features": ["rms"], "file_type": "auto", "on_incomplete": "drop"}},
            {"mini": parser},
        ))
        self.assertEqual(result["result_type"], "feature_table_with_exclusions")
        self.assertEqual(result["table"]["n_rows"], 2)
        self.assertEqual(result["exclusions"]["n_rows"], 0)

    def test_wrapper_api_exposes_feature_table_not_removed_method(self):
        result = _wrapper_api_reference(class_name="AssayProxy")
        names = {item["name"] for item in result["classes"]["AssayProxy"]}
        self.assertIn("feature_table", names)
        self.assertNotIn("to_ml_dataset", names)

    def test_feature_table_exclusions_are_reported_separately(self):
        import pandas as pd
        table = pd.DataFrame([{"run_id": "r1", "rms": 1.0}])
        report = pd.DataFrame([{"run_id": "r2", "reasons": ["file missing"]}])
        result = _serialize_wrapper_result((table, report), "test", "assay", "feature_table")
        self.assertEqual(result["result_type"], "feature_table_with_exclusions")
        self.assertEqual(result["table"]["n_rows"], 1)
        self.assertEqual(result["exclusions"]["preview_rows"][0]["run_id"], "r2")


class AttachmentToolTests(unittest.TestCase):
    def test_tool_registers_local_preview_without_sending_contents(self):
        from isa_phm.attachments import Attachment
        image = Attachment("image", "Study A", "source", "Testbed", "Images/setup.png", Path("Images/setup.png"), "available")
        missing = Attachment("datasheet", "Study A", "sensor", "Accel", "Datasheets/missing.pdf", Path("Datasheets/missing.pdf"), "missing")
        wrapper = SimpleNamespace(attachments=lambda **kwargs: [image, missing])
        registry = {}
        result = json.loads(execute_tool("show_dataset_attachments", {"dataset_name": "mini", "study_title": "Study A"}, {"mini": SimpleNamespace(wrapper=wrapper)}, attachment_registry=registry))
        self.assertEqual(result["unique_previews"], 1)
        self.assertEqual(len(registry), 1)
        self.assertEqual(result["attachments"][1]["status"], "missing")
        self.assertIn("not been read", result["note"])
        self.assertNotIn("data:", json.dumps(result))

    def test_duplicate_references_share_one_preview(self):
        from isa_phm.attachments import Attachment
        one = Attachment("datasheet", "A", "sensor", "X", "Datasheets/s.pdf", Path("Datasheets/s.pdf"), "available")
        two = Attachment("datasheet", "A", "sensor", "Y", "Datasheets/s.pdf", Path("Datasheets/s.pdf"), "available")
        registry = {}
        result = json.loads(execute_tool("show_dataset_attachments", {"dataset_name": "mini"}, {"mini": SimpleNamespace(wrapper=SimpleNamespace(attachments=lambda **kwargs: [one, two]))}, attachment_registry=registry))
        self.assertEqual(len(registry), 1)
        self.assertEqual(result["attachments"][0]["attachment_id"], result["attachments"][1]["attachment_id"])


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
        self.assertEqual(studies[0]["distinct_run_ids"], 2)
        self.assertEqual(studies[0]["sensor_run_records"], 2)

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

    def test_run_inventory_uses_wrapper_study_run_summaries(self):
        parser = load_from_file(str(FIXTURE))

        inventory = parser.get_run_inventory("Mini Diagnostic Study")

        self.assertEqual(inventory["continuity"]["n_runs"], 2)
        self.assertEqual([run["run_id"] for run in inventory["runs"]], ["run_01", "run_02"])
        self.assertTrue(all(run["sensor_alias"] == "mini-vibration" for run in inventory["runs"]))
        self.assertTrue(all(len(run["data_files"]) == 1 for run in inventory["runs"]))

    def test_run_inventory_distinguishes_run_ids_from_sensor_records(self):
        parser = load_from_file(str(FIXTURE))
        def row(run_id, number, assay):
            return SimpleNamespace(run_id=run_id, run_number=number, assay_id=assay,
                sensor_alias=assay, raw_file_path=f'{assay}-{run_id}.csv', processed_file_path=None,
                factor_values={}, measurement_params=[], processing_params=[])
        records = [row('run_01', 1, 'a'), row('run_02', 2, 'a'),
                   row('run_01', 1, 'b'), row('run_02', 2, 'b')]
        study_proxy = SimpleNamespace(title='Mini Diagnostic Study', list_runs=lambda: records)
        parser.wrapper = SimpleNamespace(study=lambda _title: study_proxy)
        with patch('isa_parser._METADATA_LIST_BUDGET', 1):
            # _cap_records has a default argument, so patch it explicitly to
            # exercise truncation while retaining the actual serialized rows.
            from isa_parser import _cap_records
            with patch('isa_parser._cap_records', side_effect=lambda items: _cap_records(items, budget=350)):
                inventory = parser.get_run_inventory('Mini Diagnostic Study')
        self.assertEqual(inventory['continuity']['n_runs'], 2)
        self.assertEqual(inventory['continuity']['n_sensor_run_records'], 4)
        self.assertEqual(inventory['measurement_records_total'], 4)
        self.assertIn('sensor-run records', inventory['note'])
        self.assertNotIn('runs_total', inventory)
        self.assertIn('do not by themselves prove', inventory['continuity']['alignment_note'])

    def test_protocol_details_use_wrapper_protocol_and_parameter_apis(self):
        parser = load_from_file(str(FIXTURE))

        details = parser.get_protocol_details("Mini Diagnostic Study")

        self.assertEqual(details["n_runs"], 2)
        self.assertEqual(details["assays"][0]["sensor_alias"], "mini-vibration")
        sampling = details["assays"][0]["parameters"]["Sampling Rate"]
        self.assertEqual(sampling["value"], 25_600)
        self.assertEqual(sampling["unit"], "Hz")
        self.assertEqual(sampling["protocol"], "Vibration measurement")
        self.assertEqual(details["study_design_descriptors"], ["Diagnostic study"])
        self.assertEqual(
            details["buckets"]["sensor_placement"],
            [{"source": "characteristic_category", "name": "Sensor mounting"}],
        )

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

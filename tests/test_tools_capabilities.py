"""Regression tests for Agent-to-Wrapper capability decisions."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import _frequency_capability


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

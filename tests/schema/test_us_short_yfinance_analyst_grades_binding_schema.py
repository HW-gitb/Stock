from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine import us_short_yfinance_analyst_grades as g  # noqa: E402


SCHEMA_PATH = ROOT / "schemas" / "us_short_yfinance_analyst_grades_binding.schema.json"


class YFinanceGradesBindingSchemaTest(unittest.TestCase):
    def setUp(self):
        from jsonschema import Draft7Validator

        self.validator = Draft7Validator(json.loads(SCHEMA_PATH.read_text(encoding="utf-8")))
        self.binding = g.load_binding()

    def _errors(self, binding):
        return list(self.validator.iter_errors(binding))

    def _mutated(self, path, value):
        binding = copy.deepcopy(self.binding)
        cursor = binding
        for key in path[:-1]:
            cursor = cursor[key]
        cursor[path[-1]] = value
        return binding

    def test_real_binding_validates(self):
        self.assertEqual(self._errors(self.binding), [])

    def test_provider_endpoint_and_direction_drift_rejected(self):
        self.assertTrue(self._errors(self._mutated(["provider_id"], "fmp")))
        self.assertTrue(self._errors(self._mutated(["endpoint_or_filing_type"], "recommendations")))
        self.assertTrue(self._errors(self._mutated(["direction_map", "_default"], "down")))

    def test_record_summary_and_duplicate_policy_drift_rejected(self):
        self.assertTrue(self._errors(self._mutated(["record_fields_required"], ["Action", "Firm"])))
        self.assertTrue(self._errors(self._mutated(
            ["summary_contract", "fields"],
            ["upgrades", "downgrades", "net", "distinct_firms", "window_days"],
        )))
        self.assertTrue(self._errors(self._mutated(["duplicate_policy", "on_duplicate"], "keep_all")))
        self.assertTrue(self._errors(self._mutated(["duplicate_policy", "firm_identity_normalization"], "verbatim")))

    def test_pit_and_checked_empty_drift_rejected(self):
        self.assertTrue(self._errors(self._mutated(
            ["pit_clock_contract", "observed_at_cutoff_operator"], "at_or_before"
        )))
        self.assertTrue(self._errors(self._mutated(
            ["pit_clock_contract", "chronology_order"], ["observed_at", "record_date", "source_as_of", "as_of"]
        )))
        self.assertTrue(self._errors(self._mutated(["checked_empty_disposition"], "silent_drop")))

    def test_noncritical_authorization_boundary_flip_rejected(self):
        for flag in (
            "live_fetch",
            "network",
            "raw_capture",
            "datahub",
            "production",
            "ship_gate",
            "emit_gate",
            "critical_provider_health",
        ):
            self.assertTrue(self._errors(self._mutated(["authorization_boundary", flag], True)), flag)

    def test_extra_top_key_rejected(self):
        binding = copy.deepcopy(self.binding)
        binding["extra"] = True
        self.assertTrue(self._errors(binding))


if __name__ == "__main__":
    unittest.main()

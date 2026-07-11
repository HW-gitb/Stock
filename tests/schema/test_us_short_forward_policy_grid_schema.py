from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PYTHON_LIBS = ROOT / ".tools" / "python_libs"
if PYTHON_LIBS.exists() and str(PYTHON_LIBS) not in sys.path:
    sys.path.insert(0, str(PYTHON_LIBS))

SCHEMA_PATH = ROOT / "schemas" / "us_short_forward_policy_grid.schema.json"
PRESET_PATH = ROOT / "presets" / "us_short_forward_policy_grid_20260711.json"


class UsShortForwardPolicyGridSchemaTest(unittest.TestCase):
    def setUp(self):
        from jsonschema import Draft7Validator
        self.validator = Draft7Validator(json.loads(SCHEMA_PATH.read_text(encoding="utf-8")))
        self.grid = json.loads(PRESET_PATH.read_text(encoding="utf-8"))

    def _errors(self, value):
        return list(self.validator.iter_errors(value))

    def test_preset_passes(self):
        self.assertEqual(self._errors(self.grid), [])

    def test_catalyst_reallocation_drift_rejected(self):
        value = copy.deepcopy(self.grid)
        value["policies"]["catalyst_off"]["score_weights"]["momentum"] = 0.5
        self.assertTrue(self._errors(value))

    def test_execution_policy_cannot_be_made_selection_immediate(self):
        value = copy.deepcopy(self.grid)
        value["policies"]["overextension_execution_off"]["materialization"] = "selection_immediate"
        self.assertTrue(self._errors(value))

    def test_sizing_neutral_cannot_be_sneaked_into_grid(self):
        value = copy.deepcopy(self.grid)
        value["second_wave_live_policies"].append("sizing_neutral")
        self.assertTrue(self._errors(value))


if __name__ == "__main__":
    unittest.main()

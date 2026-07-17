from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from engine.a_short_rule6_evaluation import RULE6_V142_THRESHOLDS
from runners.backtest_execution import load_yaml_mapping


SCHEMA_PATH = Path("schemas/a_short_rule6_thresholds.schema.json")
ARTIFACT_PATH = Path("presets/a_short_rule6_thresholds_20260714.json")
PRESET_PATH = Path("presets/a_short.yaml")


class Rule6ThresholdSchemaTests(unittest.TestCase):
    def _schema(self) -> dict:
        return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

    def _artifact(self) -> dict:
        return json.loads(ARTIFACT_PATH.read_text(encoding="utf-8"))

    def _validate(self, payload: dict) -> list:
        try:
            from jsonschema import Draft7Validator
        except ModuleNotFoundError as exc:
            raise unittest.SkipTest("jsonschema is not installed in this interpreter") from exc
        return list(Draft7Validator(self._schema()).iter_errors(payload))

    def test_frozen_artifact_matches_schema_and_evaluator_constants(self):
        self.assertEqual(self._validate(self._artifact()), [])
        self.assertEqual(self._artifact()["thresholds"], RULE6_V142_THRESHOLDS)

    def test_mutated_result_tuned_threshold_is_rejected(self):
        mutated = copy.deepcopy(self._artifact())
        mutated["thresholds"]["margin_extreme_growth_gt"] = 0.19
        self.assertNotEqual(self._validate(mutated), [])

    def test_preset_routes_to_the_frozen_contract(self):
        routing = load_yaml_mapping(PRESET_PATH)["rule6_threshold_governance"]
        self.assertEqual(routing["schema_ref"], str(SCHEMA_PATH).replace("\\", "/"))
        self.assertEqual(routing["artifact_ref"], str(ARTIFACT_PATH).replace("\\", "/"))
        self.assertEqual(routing["source_code_ref"], "engine/a_short_rule6_evaluation.py::RULE6_V142_THRESHOLDS")
        self.assertEqual(routing["parity_test_ref"], "tests/schema/test_a_short_rule6_thresholds_schema.py")
        self.assertEqual(routing["status"], "frozen_v14_2_no_result_tuning")


if __name__ == "__main__":
    unittest.main()

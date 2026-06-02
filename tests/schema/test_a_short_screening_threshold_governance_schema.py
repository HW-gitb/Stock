from __future__ import annotations

import ast
import copy
import json
import unittest
from pathlib import Path

from runners.backtest_execution import load_yaml_mapping


SCHEMA_PATH = Path("schemas/a_short_screening_threshold_governance.schema.json")
ARTIFACT_PATH = Path("presets/a_short_screening_threshold_governance_20260602.json")
PRESET_PATH = Path("presets/a_short.yaml")
EGS_MAIN_PATH = Path("A-EGS/egs_main.py")


EXPECTED_THRESHOLD_KEYS = {
    "min_avg_amount",
    "unlock_ratio",
    "top_n",
    "watch_n",
    "final_n",
    "suspend_lookback",
    "suspend_daily_min_coverage",
    "daily_stats_min_rows",
    "momentum_std_threshold",
    "max_concepts_per_stock",
    "overheat_5d",
    "overheat_20d",
    "esp_raw_cap",
}


class AShortScreeningThresholdGovernanceSchemaTest(unittest.TestCase):
    def _load_schema(self) -> dict:
        return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

    def _load_artifact(self) -> dict:
        return json.loads(ARTIFACT_PATH.read_text(encoding="utf-8"))

    def _validate(self, payload: dict) -> list:
        try:
            from jsonschema import Draft7Validator
        except ModuleNotFoundError as exc:
            raise unittest.SkipTest("jsonschema is not installed in this interpreter") from exc
        return list(Draft7Validator(self._load_schema()).iter_errors(payload))

    def _extract_conf_literals(self) -> dict[str, object]:
        tree = ast.parse(EGS_MAIN_PATH.read_text(encoding="utf-8"))
        for node in tree.body:
            if not isinstance(node, ast.Assign):
                continue
            if not any(isinstance(target, ast.Name) and target.id == "CONF" for target in node.targets):
                continue
            if not isinstance(node.value, ast.Dict):
                self.fail("CONF must be a dict literal")
            literals: dict[str, object] = {}
            for key_node, value_node in zip(node.value.keys, node.value.values):
                if not isinstance(key_node, ast.Constant) or not isinstance(key_node.value, str):
                    continue
                try:
                    literals[key_node.value] = ast.literal_eval(value_node)
                except (ValueError, TypeError):
                    continue
            return literals
        self.fail("CONF assignment not found in A-EGS/egs_main.py")

    def test_schema_meta_validates_when_jsonschema_available(self) -> None:
        try:
            from jsonschema import Draft7Validator
        except ModuleNotFoundError as exc:
            raise unittest.SkipTest("jsonschema is not installed in this interpreter") from exc

        schema = self._load_schema()

        Draft7Validator.check_schema(schema)
        self.assertEqual(
            schema["properties"]["schema_name"]["const"],
            "a_short_screening_threshold_governance",
        )
        self.assertIn("preset/code parity", schema["description"])
        self.assertIn("does not change runtime behavior", schema["description"])
        self.assertFalse(schema["additionalProperties"])

    def test_artifact_validates_when_jsonschema_available(self) -> None:
        self.assertEqual(self._validate(self._load_artifact()), [])

    def test_preset_routes_to_governance_artifact_without_breaking_yaml_loader(self) -> None:
        preset = load_yaml_mapping(PRESET_PATH)
        routing = preset["screening_threshold_governance"]

        self.assertEqual(routing["schema_ref"], str(SCHEMA_PATH).replace("\\", "/"))
        self.assertEqual(routing["artifact_ref"], str(ARTIFACT_PATH).replace("\\", "/"))
        self.assertEqual(routing["source_code_ref"], "A-EGS/egs_main.py::CONF")
        self.assertEqual(
            routing["parity_test_ref"],
            "tests/schema/test_a_short_screening_threshold_governance_schema.py",
        )
        self.assertEqual(routing["status"], "current_conf_mirrored_no_runtime_behavior_change")

    def test_threshold_inventory_matches_current_egs_conf_literals(self) -> None:
        artifact = self._load_artifact()
        conf_literals = self._extract_conf_literals()
        threshold_items = {item["conf_key"]: item for item in artifact["threshold_items"]}

        self.assertEqual(set(threshold_items), EXPECTED_THRESHOLD_KEYS)
        for key, item in threshold_items.items():
            with self.subTest(conf_key=key):
                self.assertIn(key, conf_literals)
                self.assertEqual(conf_literals[key], item["expected_value"])

    def test_scope_and_parity_rules_do_not_authorize_runtime_or_provider_work(self) -> None:
        artifact = self._load_artifact()
        scope = artifact["scope"]
        rules = artifact["parity_rules"]
        prohibited = artifact["prohibited_actions"]

        self.assertEqual(scope["contract_status"], "parity_contract_no_runtime_behavior_change")
        for key, value in scope.items():
            if key.endswith("_allowed") or key == "runtime_behavior_changed_by_this_artifact":
                self.assertFalse(value, key)
        self.assertTrue(rules["exact_value_match_required"])
        self.assertTrue(rules["threshold_change_requires_reviewed_artifact_update"])
        self.assertFalse(rules["silent_runtime_default_allowed"])
        self.assertFalse(rules["code_only_threshold_allowed"])
        for key, value in prohibited.items():
            self.assertFalse(value, key)

    def test_migration_gates_keep_runtime_loader_change_deferred(self) -> None:
        artifact = self._load_artifact()
        gates = {item["gate_id"]: item for item in artifact["migration_gates"]}

        self.assertEqual(
            set(gates),
            {
                "current_conf_parity_test",
                "future_runtime_loader_migration",
                "future_threshold_change_review",
            },
        )
        self.assertEqual(gates["current_conf_parity_test"]["status"], "satisfied_by_this_parity_contract")
        self.assertEqual(
            gates["future_runtime_loader_migration"]["status"],
            "deferred_until_runtime_loader_migration",
        )
        for gate_id, gate in gates.items():
            with self.subTest(gate_id=gate_id):
                self.assertFalse(gate["authorizes_runtime_loader_change"])
                self.assertFalse(gate["authorizes_threshold_behavior_change"])

    def test_scope_creep_is_rejected_when_jsonschema_available(self) -> None:
        invalid = copy.deepcopy(self._load_artifact())
        invalid["scope"]["provider_call_allowed"] = True
        invalid["scope"]["egs_runner_change_allowed"] = True
        invalid["threshold_items"][0]["conf_key"] = "request_delay"
        invalid["parity_rules"]["silent_runtime_default_allowed"] = True
        invalid["prohibited_actions"]["run_screening"] = True

        self.assertNotEqual(self._validate(invalid), [])


if __name__ == "__main__":
    unittest.main()

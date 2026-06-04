from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from runners import a_long_tushare_route_validation_packet as runner


SCHEMA_PATH = Path("schemas/a_long_tushare_route_validation_execution_summary.schema.json")
SUMMARY_PATH = Path("docs/a_long_tushare_route_validation_execution_summary_20260604.json")


class ALongTushareRouteValidationExecutionSummarySchemaTest(unittest.TestCase):
    def _load_schema(self) -> dict:
        return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

    def _validate(self, payload: dict) -> list:
        try:
            from jsonschema import Draft7Validator
        except ModuleNotFoundError as exc:
            raise unittest.SkipTest("jsonschema is not installed in this interpreter") from exc
        return list(Draft7Validator(self._load_schema()).iter_errors(payload))

    def _no_execution_payload(self) -> dict:
        return runner.build_summary(
            results=[],
            calls=runner.call_plan(),
            generated_at="2026-06-04T00:00:00+00:00",
            raw_root=runner.RAW_ROOT,
            summary_path=runner.SUMMARY_PATH,
            environment_precheck_passed=False,
            network_call_attempted=False,
        )

    def test_schema_meta_validates_when_jsonschema_available(self) -> None:
        try:
            from jsonschema import Draft7Validator
        except ModuleNotFoundError as exc:
            raise unittest.SkipTest("jsonschema is not installed in this interpreter") from exc

        schema = self._load_schema()

        Draft7Validator.check_schema(schema)
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(
            schema["properties"]["schema_name"]["const"],
            "a_long_tushare_route_validation_execution_summary",
        )
        self.assertIn("field-presence", schema["description"])

    def test_environment_missing_summary_validates(self) -> None:
        payload = self._no_execution_payload()

        self.assertEqual(self._validate(payload), [])
        self.assertEqual(payload["decision"]["route_validation_status"], "not_executed_environment_missing")
        self.assertFalse(payload["scope"]["provider_call_executed"])
        self.assertEqual(payload["endpoint_results"], [])
        self.assertFalse(payload["decision"]["data_can_be_used_now"])

    def test_persisted_summary_validates_when_present(self) -> None:
        if not SUMMARY_PATH.exists():
            self.skipTest("route-validation summary has not been generated yet")

        payload = json.loads(SUMMARY_PATH.read_text(encoding="utf-8"))

        self.assertEqual(self._validate(payload), [])
        self.assertFalse(payload["decision"]["data_can_be_used_now"])
        self.assertFalse(payload["decision"]["signal_search_allowed_by_this_summary"])
        self.assertFalse(payload["decision"]["full_materialization_allowed_by_this_summary"])

    def test_scope_creep_is_rejected(self) -> None:
        invalid = copy.deepcopy(self._no_execution_payload())
        invalid["scope"]["signal_search_executed"] = True
        invalid["scope"]["tracked_summary_contains_raw_rows"] = True
        invalid["decision"]["data_can_be_used_now"] = True
        invalid["prohibited_claims"]["a_long_data_ready"] = True
        invalid["prohibited_claims"]["signal_search_authorized"] = True

        self.assertNotEqual(self._validate(invalid), [])


if __name__ == "__main__":
    unittest.main()

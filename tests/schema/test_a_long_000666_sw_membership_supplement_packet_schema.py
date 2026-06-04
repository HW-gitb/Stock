from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from runners import a_long_000666_sw_membership_supplement_packet as runner
from tests.test_a_long_000666_sw_membership_supplement_packet import FakeFoundMembershipPro


PACKET_SCHEMA_PATH = Path("schemas/a_long_000666_sw_membership_supplement_packet.schema.json")
PACKET_PATH = Path("docs/a_long_000666_sw_membership_supplement_packet_20260604.json")
SUMMARY_SCHEMA_PATH = Path("schemas/a_long_000666_sw_membership_supplement_execution_summary.schema.json")
ACTUAL_SUMMARY_PATH = Path("docs/a_long_000666_sw_membership_supplement_execution_summary_20260604.json")


class ALong000666SwMembershipSupplementPacketSchemaTest(unittest.TestCase):
    def _load_packet_schema(self) -> dict:
        return json.loads(PACKET_SCHEMA_PATH.read_text(encoding="utf-8"))

    def _load_summary_schema(self) -> dict:
        return json.loads(SUMMARY_SCHEMA_PATH.read_text(encoding="utf-8"))

    def _load_packet(self) -> dict:
        return json.loads(PACKET_PATH.read_text(encoding="utf-8"))

    def _validate_packet(self, payload: dict) -> list:
        try:
            from jsonschema import Draft7Validator
        except ModuleNotFoundError as exc:
            raise unittest.SkipTest("jsonschema is not installed in this interpreter") from exc
        return list(Draft7Validator(self._load_packet_schema()).iter_errors(payload))

    def _validate_summary(self, payload: dict) -> list:
        try:
            from jsonschema import Draft7Validator
        except ModuleNotFoundError as exc:
            raise unittest.SkipTest("jsonschema is not installed in this interpreter") from exc
        return list(Draft7Validator(self._load_summary_schema()).iter_errors(payload))

    def test_packet_schema_meta_validates_when_jsonschema_available(self) -> None:
        try:
            from jsonschema import Draft7Validator
        except ModuleNotFoundError as exc:
            raise unittest.SkipTest("jsonschema is not installed in this interpreter") from exc

        schema = self._load_packet_schema()

        Draft7Validator.check_schema(schema)
        self.assertEqual(schema["properties"]["schema_name"]["const"], "a_long_000666_sw_membership_supplement_packet")
        self.assertIn("No-access", schema["description"])
        self.assertFalse(schema["additionalProperties"])

    def test_summary_schema_meta_validates_when_jsonschema_available(self) -> None:
        try:
            from jsonschema import Draft7Validator
        except ModuleNotFoundError as exc:
            raise unittest.SkipTest("jsonschema is not installed in this interpreter") from exc

        schema = self._load_summary_schema()

        Draft7Validator.check_schema(schema)
        self.assertEqual(
            schema["properties"]["schema_name"]["const"],
            "a_long_000666_sw_membership_supplement_execution_summary",
        )
        self.assertIn("Raw rows must stay gitignored", schema["description"])
        self.assertFalse(schema["additionalProperties"])
        self.assertIn("dry_run_environment_ready", schema["$defs"]["decision"]["properties"]["supplement_status"]["enum"])

    def test_packet_artifact_validates_when_jsonschema_available(self) -> None:
        self.assertEqual(self._validate_packet(self._load_packet()), [])

    def test_scope_and_target_are_fixed(self) -> None:
        artifact = self._load_packet()
        scope = artifact["scope"]
        target = artifact["target"]

        self.assertEqual(scope["phase"], "7a_alpha_validation")
        self.assertEqual(scope["lane_id"], "a_long")
        self.assertEqual(scope["provider_family"], "tushare_existing_account")
        self.assertTrue(scope["single_symbol_supplement_only"])
        self.assertTrue(scope["ready_for_later_execution_after_independent_review"])
        self.assertTrue(scope["actual_tushare_calls_require_post_review_execute_command"])
        self.assertEqual(target["symbol"], "000666.SZ")
        self.assertEqual(target["current_materialized_sw_membership_row_count"], 0)
        for field in [
            "provider_calls_executed_by_this_artifact",
            "tushare_calls_executed_by_this_artifact",
            "data_fetch_executed_by_this_artifact",
            "raw_payloads_read_by_this_artifact",
            "audit_rerun_allowed_by_this_artifact",
            "signal_search_allowed",
            "alpha_backtest_allowed",
            "datahub_allowed",
            "production_use_allowed",
            "ship_gate_claim_allowed",
            "full_size_manual_use_allowed",
            "broker_or_order_automation_allowed",
        ]:
            self.assertFalse(scope[field], field)

    def test_call_plan_budget_and_storage_are_fixed(self) -> None:
        artifact = self._load_packet()

        self.assertEqual(artifact["call_budget"]["planned_total_endpoint_calls"], 4)
        self.assertEqual(artifact["call_budget"]["max_total_endpoint_calls"], 4)
        self.assertEqual(artifact["call_budget"]["retry_count_allowed"], 0)
        self.assertEqual(artifact["call_plan"], runner.supplement_call_plan())
        self.assertIn("industry", artifact["call_plan"][0]["kwargs"]["fields"])
        self.assertIn("area", artifact["call_plan"][0]["kwargs"]["fields"])
        self.assertEqual(artifact["call_plan"][1]["method"], "index_classify")
        self.assertNotIn("index_member", {call["method"] for call in artifact["call_plan"]})
        self.assertEqual(
            artifact["storage"]["raw_output_root"],
            "data/a_long/raw/tushare/000666_sw_membership_supplement_20260604/",
        )
        self.assertEqual(
            artifact["storage"]["tracked_summary_path"],
            "docs/a_long_000666_sw_membership_supplement_execution_summary_20260604.json",
        )
        for field, value in artifact["pre_execution_gates"].items():
            self.assertTrue(value, field)
        for field, value in artifact["prohibited_claims"].items():
            self.assertFalse(value, field)

    def test_fake_execution_summary_validates_when_jsonschema_available(self) -> None:
        raw_root = runner.RAW_ROOT / "schema_unit_test"
        try:
            with tempfile.TemporaryDirectory() as tmp:
                summary = runner.execute_supplement(
                    pro_factory=lambda: FakeFoundMembershipPro(),
                    raw_root=raw_root,
                    summary_path=Path(tmp) / "summary.json",
                    generated_at="2026-06-04T00:00:00+00:00",
                    confirm_independent_review_pass=True,
                    confirm_post_review_execute=True,
                )
            self.assertEqual(self._validate_summary(summary), [])
        finally:
            if raw_root.exists():
                import shutil

                shutil.rmtree(raw_root)

    def test_actual_execution_summary_validates_when_present(self) -> None:
        if not ACTUAL_SUMMARY_PATH.exists():
            raise unittest.SkipTest("actual supplement execution summary has not been generated")
        summary = json.loads(ACTUAL_SUMMARY_PATH.read_text(encoding="utf-8"))

        self.assertEqual(self._validate_summary(summary), [])
        self.assertEqual(summary["decision"]["supplement_status"], "no_candidate_sw_membership_source_found")
        self.assertFalse(summary["decision"]["candidate_sw_membership_source_found"])
        self.assertFalse(summary["decision"]["data_can_be_used_for_alpha_now"])
        self.assertFalse(summary["decision"]["audit_rerun_authorized_by_this_summary"])
        self.assertFalse(summary["decision"]["signal_search_authorized_by_this_summary"])
        self.assertEqual(summary["execution"]["actual_call_count"], 4)
        stock_basic = [
            item
            for item in summary["endpoint_results"]
            if item["call_id"] == "stock_basic_000666_delisted_context"
        ][0]
        self.assertEqual(stock_basic["target_value_flags"], {"industry": False, "area": False})

    def test_packet_scope_creep_is_rejected_when_jsonschema_available(self) -> None:
        invalid = copy.deepcopy(self._load_packet())
        invalid["scope"]["provider_calls_executed_by_this_artifact"] = True
        invalid["scope"]["signal_search_allowed"] = True
        invalid["target"]["symbol"] = "600519.SH"
        invalid["call_budget"]["max_total_endpoint_calls"] = 5
        invalid["call_plan"][1]["kwargs"]["ts_code"] = "600519.SH"
        invalid["prohibited_claims"]["a_long_alpha_found"] = True

        self.assertNotEqual(self._validate_packet(invalid), [])

    def test_summary_overclaim_is_rejected_when_jsonschema_available(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            summary = runner.execute_supplement(
                pro_factory=lambda: FakeFoundMembershipPro(),
                raw_root=runner.RAW_ROOT / "schema_overclaim_unit_test",
                summary_path=Path(tmp) / "summary.json",
                generated_at="2026-06-04T00:00:00+00:00",
                confirm_independent_review_pass=True,
                confirm_post_review_execute=True,
            )

        invalid = copy.deepcopy(summary)
        invalid["decision"]["data_can_be_used_for_alpha_now"] = True
        invalid["decision"]["signal_search_authorized_by_this_summary"] = True
        invalid["prohibited_claims"]["a_long_alpha_found"] = True
        invalid["scope"]["production_use_allowed"] = True

        self.assertNotEqual(self._validate_summary(invalid), [])
        raw_root = runner.RAW_ROOT / "schema_overclaim_unit_test"
        if raw_root.exists():
            import shutil

            shutil.rmtree(raw_root)


if __name__ == "__main__":
    unittest.main()

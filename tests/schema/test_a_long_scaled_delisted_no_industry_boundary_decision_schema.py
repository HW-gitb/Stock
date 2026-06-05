from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path


SCHEMA_PATH = Path("schemas/a_long_scaled_delisted_no_industry_boundary_decision.schema.json")
ARTIFACT_PATH = Path("docs/a_long_scaled_delisted_no_industry_boundary_decision_20260605.json")
REPAIR_SUMMARY_PATH = Path("docs/a_long_main_board_sw_coverage_repair_execution_summary_20260604.json")


class ALongScaledDelistedNoIndustryBoundaryDecisionSchemaTest(unittest.TestCase):
    def _load_json(self, path: Path) -> dict:
        return json.loads(path.read_text(encoding="utf-8"))

    def _load_schema(self) -> dict:
        return self._load_json(SCHEMA_PATH)

    def _load_artifact(self) -> dict:
        return self._load_json(ARTIFACT_PATH)

    def _validate(self, payload: dict) -> list:
        try:
            from jsonschema import Draft7Validator
        except ModuleNotFoundError as exc:
            raise unittest.SkipTest("jsonschema is not installed in this interpreter") from exc

        schema = self._load_schema()
        Draft7Validator.check_schema(schema)
        return list(Draft7Validator(schema).iter_errors(payload))

    def test_schema_and_artifact_validate_when_jsonschema_available(self) -> None:
        try:
            from jsonschema import Draft7Validator
        except ModuleNotFoundError as exc:
            raise unittest.SkipTest("jsonschema is not installed in this interpreter") from exc

        schema = self._load_schema()
        artifact = self._load_artifact()

        Draft7Validator.check_schema(schema)
        self.assertEqual(list(Draft7Validator(schema).iter_errors(artifact)), [])

    def test_boundary_counts_match_repair_summary(self) -> None:
        artifact = self._load_artifact()
        repair = self._load_json(REPAIR_SUMMARY_PATH)
        boundary = artifact["reviewed_boundary"]

        self.assertEqual(boundary["main_board_active_count"], repair["candidate_universe_before"]["main_board_active_count"])
        self.assertEqual(
            boundary["main_board_delisted_2018_2025_count"],
            repair["candidate_universe_before"]["main_board_delisted_2018_2025_count"],
        )
        self.assertEqual(
            boundary["active_delisting_shell_symbols"],
            repair["active_delisting_shell_boundary"]["detected_symbols"],
        )
        self.assertEqual(
            boundary["scaled_no_industry_boundary_count_if_approved"],
            repair["active_delisting_shell_boundary"]["pending_scaled_delisted_no_source_count_if_approved"],
        )
        self.assertEqual(boundary["active_investable_unresolved_count"], 0)
        self.assertLessEqual(boundary["scaled_exception_rate_pct"], boundary["max_exception_rate_pct"])

    def test_scope_stops_before_full_pull_and_signal_search(self) -> None:
        artifact = self._load_artifact()
        scope = artifact["scope"]
        decision = artifact["decision"]

        self.assertTrue(scope["research_only"])
        self.assertTrue(scope["docs_only"])
        self.assertTrue(scope["reads_tracked_summary_only"])
        self.assertFalse(scope["data_fetch_executed"])
        self.assertFalse(scope["provider_call_executed"])
        self.assertFalse(scope["tushare_call_executed"])
        self.assertFalse(scope["full_universe_data_pull_authorized_by_this_artifact"])
        self.assertFalse(scope["full_universe_signal_search_authorized_by_this_artifact"])
        self.assertFalse(decision["candidate_universe_ready_for_full_pull_now"])
        self.assertFalse(decision["full_pull_authorized_by_this_artifact"])
        self.assertFalse(decision["signal_search_authorized_by_this_artifact"])

    def test_boundary_treatment_blocks_manual_fill_and_drop_from_returns(self) -> None:
        treatment = self._load_artifact()["reviewed_boundary"]["boundary_treatment"]

        self.assertFalse(treatment["manual_industry_fill_allowed"])
        self.assertFalse(treatment["silent_unknown_or_default_industry_allowed"])
        self.assertFalse(treatment["drop_from_universe_returns_or_risk_allowed"])
        self.assertTrue(treatment["exclude_only_from_industry_normalization_denominators"])
        self.assertTrue(treatment["keep_in_pit_universe_returns_risk_drawdown_and_coverage"])
        self.assertTrue(treatment["terminal_delisting_return_required"])
        self.assertTrue(treatment["selection_time_st_or_delisting_name_veto_required"])

    def test_scope_creep_is_rejected_by_schema(self) -> None:
        invalid = copy.deepcopy(self._load_artifact())
        invalid["scope"]["full_universe_data_pull_authorized_by_this_artifact"] = True
        invalid["scope"]["full_universe_signal_search_authorized_by_this_artifact"] = True
        invalid["reviewed_boundary"]["boundary_treatment"]["manual_industry_fill_allowed"] = True
        invalid["reviewed_boundary"]["boundary_treatment"]["drop_from_universe_returns_or_risk_allowed"] = True
        invalid["decision"]["candidate_universe_ready_for_full_pull_now"] = True
        invalid["decision"]["full_pull_authorized_by_this_artifact"] = True
        invalid["prohibited_claims"]["a_long_alpha_found"] = True

        self.assertGreaterEqual(len(self._validate(invalid)), 7)


if __name__ == "__main__":
    unittest.main()

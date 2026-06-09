from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from jsonschema import Draft7Validator


ARTIFACT_PATH = Path("research/preregistrations/a_long_large_cap_batch_factor_search_20260609.json")
SCHEMA_PATH = Path("schemas/a_long_large_cap_batch_factor_search_preregistration.schema.json")
LEDGER_ARTIFACT_PATH = Path("research/ledgers/a_long_large_cap_batch_factor_search_program_test_budget_ledger_20260609.json")
LEDGER_SCHEMA_PATH = Path("schemas/program_test_budget_ledger.schema.json")

EXPECTED_FACTOR_IDS = {
    "book_to_circ_mv", "cash_flow_to_circ_mv", "sales_to_circ_mv", "low_accruals",
    "low_asset_growth", "roa_ttm", "low_beta", "low_max", "momentum_12_1",
}


class ALongLargeCapBatchFactorSearchPreregistrationSchemaTest(unittest.TestCase):
    def _load_json(self, path: Path) -> dict:
        return json.loads(path.read_text(encoding="utf-8"))

    def _validate(self, schema_path: Path, payload: dict) -> list:
        schema = self._load_json(schema_path)
        Draft7Validator.check_schema(schema)
        return list(Draft7Validator(schema).iter_errors(payload))

    def _load_artifact(self) -> dict:
        return self._load_json(ARTIFACT_PATH)

    def _load_ledger(self) -> dict:
        return self._load_json(LEDGER_ARTIFACT_PATH)

    # --- structural ---

    def test_schema_is_valid_draft7(self) -> None:
        Draft7Validator.check_schema(self._load_json(SCHEMA_PATH))

    def test_preregistration_validates_against_schema(self) -> None:
        self.assertEqual(self._validate(SCHEMA_PATH, self._load_artifact()), [])

    def test_artifact_identity(self) -> None:
        art = self._load_artifact()
        self.assertEqual(art["schema_name"], "a_long_large_cap_batch_factor_search_preregistration")
        self.assertEqual(art["artifact_id"], "a_long_large_cap_batch_factor_search_20260609")
        self.assertEqual(art["frozen_design"]["design_id"], "a_long_large_cap_batch_factor_search_v1")

    def test_review_status_is_passed_post_review(self) -> None:
        # Post-PASS committed state (Codex 审查 PASS 2026-06-09). The schema enum also accepts the draft
        # pending value, so both states validate; this asserts the committed one.
        self.assertEqual(
            self._load_artifact()["scope"]["preregistration_review_status"],
            "passed_independent_review_ready_for_freeze",
        )

    # --- frozen design content ---

    def test_batch_has_nine_factors_plus_composite(self) -> None:
        bfr = self._load_artifact()["frozen_design"]["batch_factor_rule"]
        self.assertEqual(bfr["factor_count"], 9)
        self.assertEqual(bfr["composite_count"], 1)
        self.assertEqual(bfr["total_primary_hypotheses"], 10)
        ids = {f["factor_id"] for f in bfr["factors"]}
        self.assertEqual(ids, EXPECTED_FACTOR_IDS)
        self.assertEqual(bfr["composite"]["composite_id"], "family_balanced_composite")
        self.assertTrue(all(f["high_value_is_high_score"] for f in bfr["factors"]))

    def test_fdr_and_q_are_frozen(self) -> None:
        dr = self._load_artifact()["frozen_design"]["decision_rule"]
        self.assertEqual(dr["decision_type"], "batch_bh_fdr_over_primary_cells")
        self.assertEqual(dr["fdr_method"], "benjamini_hochberg")
        self.assertEqual(dr["m_total_hypotheses"], 10)
        self.assertEqual(dr["q_research_clue_gate"], 0.1)
        self.assertEqual(dr["q_strict_diagnostic_reported"], 0.05)
        self.assertTrue(dr["q_frozen_before_run"])
        self.assertFalse(dr["q_search_allowed"])
        self.assertFalse(dr["diagnostics_can_define_alpha"])

    def test_robustness_and_risk_thresholds_are_frozen(self) -> None:
        fd = self._load_artifact()["frozen_design"]
        gates = fd["decision_rule"]["per_factor_statistical_alpha_clue_gates"]
        self.assertEqual(gates["minimum_monthly_cohorts"], 48)
        self.assertEqual(gates["name_concentration_guard_max_share"], 0.2)
        self.assertEqual(gates["single_year_positive_return_guard_max_share"], 0.35)
        self.assertTrue(gates["sub_period_both_halves_mean_excess_positive_required"])
        self.assertEqual(fd["risk_gate"]["minimum_allowed_relative_nav_drawdown"], -0.15)
        self.assertEqual(fd["measurement_rule"]["round_trip_cost"], 0.0026)
        self.assertEqual(fd["measurement_rule"]["primary_horizon_trading_days"], 504)
        self.assertEqual(fd["universe_rule"]["universe_size_n"], 500)
        self.assertEqual(fd["pit_and_hygiene_controls"]["expected_restatement_exclusion_group_count"], 1504)

    def test_stopping_rule_present(self) -> None:
        sr = self._load_artifact()["frozen_design"]["stopping_rule"]
        self.assertTrue(sr["this_is_the_last_structured_batch_candidate_generation_round"])
        self.assertTrue(sr["no_further_factor_definition_rescue_after_dry_batch"])

    def test_anti_p_hacking_search_flags_all_false(self) -> None:
        ctrl = self._load_artifact()["frozen_design"]["anti_p_hacking_controls"]
        for flag in [
            "parameter_sweep_allowed", "universe_n_search_allowed", "factor_definition_search_allowed",
            "factor_count_search_allowed", "trailing_window_search_allowed", "q_threshold_search_allowed",
            "composite_weight_search_allowed", "post_result_rescue_slicing_allowed",
            "drop_losing_factors_then_re_fdr_allowed",
        ]:
            self.assertFalse(ctrl[flag], flag)
        self.assertEqual(ctrl["test_budget_units"], 1)

    # --- ledger ---

    def test_ledger_validates_and_is_one_unspent_pending_singleton(self) -> None:
        ledger = self._load_ledger()
        self.assertEqual(self._validate(LEDGER_SCHEMA_PATH, ledger), [])
        self.assertEqual(ledger["family_id"], "a_long_large_cap_batch_factor_search_v1")
        self.assertEqual(ledger["ledger_status"], "active_planned_test_pending_review")
        self.assertEqual(ledger["budget_policy"]["tests_spent_count"], 0)
        self.assertEqual(ledger["budget_policy"]["tests_available_without_new_review"], 0)
        self.assertEqual(ledger["test_spend_log"], [])
        self.assertEqual(len(ledger["planned_tests"]), 1)
        planned = ledger["planned_tests"][0]
        self.assertEqual(planned["test_id"], "a_long_large_cap_batch_factor_search_20260609")
        self.assertEqual(planned["planned_status"], "planned_not_reviewed")
        self.assertEqual(planned["expected_tests_spent"], 1)
        self.assertEqual(
            self._load_artifact()["planned_test_budget"]["ledger_ref"],
            str(LEDGER_ARTIFACT_PATH).replace("\\", "/"),
        )

    # --- adversarial: schema must reject design drift ---

    def test_schema_rejects_wrong_factor_count(self) -> None:
        bad = copy.deepcopy(self._load_artifact())
        bad["frozen_design"]["batch_factor_rule"]["factor_count"] = 8
        self.assertGreaterEqual(len(self._validate(SCHEMA_PATH, bad)), 1)

    def test_schema_rejects_dropped_factor(self) -> None:
        bad = copy.deepcopy(self._load_artifact())
        bad["frozen_design"]["batch_factor_rule"]["factors"] = bad["frozen_design"]["batch_factor_rule"]["factors"][:8]
        self.assertGreaterEqual(len(self._validate(SCHEMA_PATH, bad)), 1)

    def test_schema_rejects_q_relaxation(self) -> None:
        bad = copy.deepcopy(self._load_artifact())
        bad["frozen_design"]["decision_rule"]["q_research_clue_gate"] = 0.25
        self.assertGreaterEqual(len(self._validate(SCHEMA_PATH, bad)), 1)

    def test_schema_rejects_enabled_search_flag(self) -> None:
        bad = copy.deepcopy(self._load_artifact())
        bad["frozen_design"]["anti_p_hacking_controls"]["factor_definition_search_allowed"] = True
        self.assertGreaterEqual(len(self._validate(SCHEMA_PATH, bad)), 1)

    def test_schema_rejects_drop_losers_then_refdr(self) -> None:
        bad = copy.deepcopy(self._load_artifact())
        bad["frozen_design"]["anti_p_hacking_controls"]["drop_losing_factors_then_re_fdr_allowed"] = True
        self.assertGreaterEqual(len(self._validate(SCHEMA_PATH, bad)), 1)

    def test_schema_rejects_relaxed_risk_gate(self) -> None:
        bad = copy.deepcopy(self._load_artifact())
        bad["frozen_design"]["risk_gate"]["minimum_allowed_relative_nav_drawdown"] = -0.30
        self.assertGreaterEqual(len(self._validate(SCHEMA_PATH, bad)), 1)

    def test_schema_rejects_production_or_signal_authorization(self) -> None:
        bad = copy.deepcopy(self._load_artifact())
        bad["scope"]["signal_search_authorized_by_this_artifact"] = True
        bad["scope"]["production_use_allowed"] = True
        self.assertGreaterEqual(len(self._validate(SCHEMA_PATH, bad)), 2)

    def test_schema_rejects_unknown_top_level_field(self) -> None:
        bad = copy.deepcopy(self._load_artifact())
        bad["unexpected_extra_field"] = True
        self.assertGreaterEqual(len(self._validate(SCHEMA_PATH, bad)), 1)

    # --- adversarial: schema must FREEZE every factor's formula / inputs / window (R-BATCH-FACTOR-CONSTS) ---

    def _factor(self, art: dict, fid: str) -> dict:
        for f in art["frozen_design"]["batch_factor_rule"]["factors"]:
            if f["factor_id"] == fid:
                return f
        raise AssertionError(f"factor {fid} not found")

    def test_schema_rejects_mutated_factor_definition(self) -> None:
        for fid in ["book_to_circ_mv", "cash_flow_to_circ_mv", "low_accruals", "low_beta", "momentum_12_1"]:
            bad = copy.deepcopy(self._load_artifact())
            self._factor(bad, fid)["definition"] = "mutated_definition_post_review"
            self.assertGreaterEqual(len(self._validate(SCHEMA_PATH, bad)), 1, f"definition mutation for {fid} not caught")

    def test_schema_rejects_mutated_factor_input_fields(self) -> None:
        for fid in ["book_to_circ_mv", "cash_flow_to_circ_mv", "low_accruals", "low_beta", "momentum_12_1"]:
            bad = copy.deepcopy(self._load_artifact())
            self._factor(bad, fid)["input_fields"] = ["some.other_field"]
            self.assertGreaterEqual(len(self._validate(SCHEMA_PATH, bad)), 1, f"input_fields mutation for {fid} not caught")

    def test_schema_rejects_mutated_trailing_or_formation_window(self) -> None:
        bad = copy.deepcopy(self._load_artifact())
        self._factor(bad, "low_beta")["trailing_window_trading_days"] = 60
        self.assertGreaterEqual(len(self._validate(SCHEMA_PATH, bad)), 1, "low_beta window mutation not caught")
        bad2 = copy.deepcopy(self._load_artifact())
        self._factor(bad2, "momentum_12_1")["formation_end_trading_days_ago"] = 0
        self.assertGreaterEqual(len(self._validate(SCHEMA_PATH, bad2)), 1, "momentum formation mutation not caught")

    def test_schema_rejects_extra_field_on_factor(self) -> None:
        bad = copy.deepcopy(self._load_artifact())
        self._factor(bad, "book_to_circ_mv")["sneaky_param"] = 7
        self.assertGreaterEqual(len(self._validate(SCHEMA_PATH, bad)), 1)

    # --- adversarial: source lineage + field-verification freeze (R-BATCH-SOURCE-REF) ---

    def test_source_draft_path_is_correct_and_exists_on_disk(self) -> None:
        paths = [r["path"] for r in self._load_artifact()["source_doc_refs"]]
        draft = "docs/a_long_large_cap_batch_factor_search_design_draft_20260608.md"
        self.assertIn(draft, paths)
        self.assertTrue(Path(draft).exists(), "design-draft source ref must point to a committed file")

    def test_schema_rejects_bad_source_draft_path(self) -> None:
        bad = copy.deepcopy(self._load_artifact())
        bad["source_doc_refs"][0]["path"] = "docs/a_long_large_cap_batch_factor_search_design_draft_20260609.md"
        self.assertGreaterEqual(len(self._validate(SCHEMA_PATH, bad)), 1)

    def test_schema_rejects_reduced_materialized_present_list(self) -> None:
        bad = copy.deepcopy(self._load_artifact())
        bad["data_reuse"]["materialized_fields_verified_present"] = ["daily.close"]
        self.assertGreaterEqual(len(self._validate(SCHEMA_PATH, bad)), 1)


if __name__ == "__main__":
    unittest.main()

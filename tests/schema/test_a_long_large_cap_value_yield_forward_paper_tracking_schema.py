"""Schema test for the A-long large-cap value-yield forward PAPER-tracking design. The bespoke schema
is all-frozen: every design value (universe, neutralization, the 3 tracked constructions, basket rule,
forward window, decision rule, scope locks, prohibited claims) is const-pinned so post-review drift
cannot validate. Only generated_at, the review-status enum, and prose fields are flexible."""
from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

import jsonschema

ROOT = Path(__file__).resolve().parents[2]
SPEC_PATH = ROOT / "research" / "preregistrations" / "a_long_large_cap_value_yield_forward_paper_tracking_20260609.json"
SCHEMA_PATH = ROOT / "schemas" / "a_long_large_cap_value_yield_forward_paper_tracking.schema.json"
LEDGER_PATH = ROOT / "research" / "ledgers" / "a_long_large_cap_value_yield_forward_paper_tracking_program_test_budget_ledger_20260609.json"
LEDGER_SCHEMA_PATH = ROOT / "schemas" / "program_test_budget_ledger.schema.json"


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


class ForwardPaperTrackingSchemaValidTests(unittest.TestCase):
    def setUp(self):
        self.spec = load(SPEC_PATH)
        self.schema = load(SCHEMA_PATH)

    def test_real_spec_validates(self):
        jsonschema.validate(self.spec, self.schema)

    def test_post_review_status_flip_validates(self):
        spec = copy.deepcopy(self.spec)
        spec["scope"]["preregistration_review_status"] = "passed_independent_review_ready_for_freeze"
        jsonschema.validate(spec, self.schema)

    def test_generated_at_and_prose_are_flexible(self):
        spec = copy.deepcopy(self.spec)
        spec["generated_at"] = "2099-12-31T23:59:59+08:00"
        spec["limitations"][0] = "reworded limitation prose stays valid"
        jsonschema.validate(spec, self.schema)

    def test_frozen_design_anchors_present(self):
        ids = [c["construction_id"] for c in self.spec["frozen_construction"]["tracked_constructions"]]
        self.assertEqual(ids, ["cash_flow_to_circ_mv", "sales_to_circ_mv", "value_yield_composite_cf_sales"])
        self.assertEqual(self.spec["scope"]["evidence_level"], "paper")
        self.assertFalse(self.spec["scope"]["paper_evidence_satisfies_ship_gate"])
        self.assertEqual(self.spec["provenance"]["surviving_clue_factor_ids"], ["cash_flow_to_circ_mv", "sales_to_circ_mv"])
        self.assertEqual(
            self.spec["evidence_and_decision_rule"]["paper_read_per_construction"]["tradeable_drawdown_floor"], -0.15
        )

    def test_single_primary_promotion_construction_no_cherry_pick(self):
        roles = {c["construction_id"]: c["promotion_role"] for c in self.spec["frozen_construction"]["tracked_constructions"]}
        self.assertEqual(roles["cash_flow_to_circ_mv"], "diagnostic_supporting_only")
        self.assertEqual(roles["sales_to_circ_mv"], "diagnostic_supporting_only")
        self.assertEqual(roles["value_yield_composite_cf_sales"], "primary_promotion_construction")
        fdr = self.spec["family_decision_rule"]
        self.assertEqual(fdr["promotion_eligible_construction_count"], 1)
        self.assertEqual(fdr["single_primary_promotion_construction"], "value_yield_composite_cf_sales")
        self.assertFalse(fdr["diagnostics_can_independently_promote"])
        self.assertTrue(fdr["best_of_three_post_window_selection_forbidden"])

    def test_ledger_is_valid_unspent_singleton_and_referenced(self):
        ledger = load(LEDGER_PATH)
        jsonschema.validate(ledger, load(LEDGER_SCHEMA_PATH))
        self.assertEqual(ledger["family_id"], "a_long_large_cap_value_yield_forward_paper_v1")
        self.assertEqual(ledger["budget_policy"]["ledger_cardinality"], "singleton_program_level")
        self.assertEqual(ledger["budget_policy"]["tests_spent_count"], 0)
        self.assertEqual(ledger["ledger_status"], "active_planned_test_pending_review")
        self.assertEqual(ledger["test_spend_log"], [])
        self.assertEqual(len(ledger["planned_tests"]), 1)
        self.assertEqual(ledger["planned_tests"][0]["expected_tests_spent"], 1)
        ref = self.spec["planned_test_budget"]["ledger_ref"]
        self.assertEqual(ref, str(LEDGER_PATH.relative_to(ROOT)).replace("\\", "/"))
        self.assertEqual(self.spec["planned_test_budget"]["family_id"], ledger["family_id"])
        self.assertEqual(self.spec["planned_test_budget"]["test_budget_units"], 1)
        # Exact-ref checks (O-VY-LEDGER-EXACT-REF-TEST): the generic ledger schema accepts any string ref;
        # assert the planned test routes back to THIS spec/result and spends exactly one. (Adversarial
        # misroute REJECTION belongs to the future capture-runner's hardened load_and_validate_ledger.)
        planned = ledger["planned_tests"][0]
        spec_rel = str(SPEC_PATH.relative_to(ROOT)).replace("\\", "/")
        self.assertEqual(planned["planned_preregistration_ref"], spec_rel)
        self.assertEqual(
            planned["planned_result_ref"],
            "research/results/a_long_large_cap_value_yield_forward_paper_tracking_20260609/paper_read_summary.json",
        )
        self.assertEqual(planned["test_id"], "a_long_large_cap_value_yield_forward_paper_promotion_decision_20260609")
        self.assertTrue(planned["promotion_relevant"])


class ForwardPaperTrackingSchemaAdversarialTests(unittest.TestCase):
    def setUp(self):
        self.spec = load(SPEC_PATH)
        self.schema = load(SCHEMA_PATH)

    def _reject(self, spec):
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(spec, self.schema)

    def test_extra_top_level_field_rejected(self):
        spec = copy.deepcopy(self.spec)
        spec["unexpected_field"] = True
        self._reject(spec)

    def test_dropped_required_scope_field_rejected(self):
        spec = copy.deepcopy(self.spec)
        del spec["scope"]["manual_order_only"]
        self._reject(spec)

    def test_real_money_committed_true_rejected(self):
        spec = copy.deepcopy(self.spec)
        spec["scope"]["real_money_committed"] = True
        self._reject(spec)

    def test_paper_satisfies_ship_gate_true_rejected(self):
        spec = copy.deepcopy(self.spec)
        spec["scope"]["paper_evidence_satisfies_ship_gate"] = True
        self._reject(spec)

    def test_data_fetch_authorized_true_rejected(self):
        spec = copy.deepcopy(self.spec)
        spec["scope"]["data_fetch_allowed_by_this_artifact"] = True
        self._reject(spec)

    def test_top_fraction_drift_rejected(self):
        spec = copy.deepcopy(self.spec)
        spec["frozen_construction"]["basket_rule"]["top_fraction"] = 0.3
        self._reject(spec)

    def test_drawdown_floor_drift_rejected(self):
        spec = copy.deepcopy(self.spec)
        spec["evidence_and_decision_rule"]["paper_read_per_construction"]["tradeable_drawdown_floor"] = -0.25
        self._reject(spec)

    def test_ship_gate_threshold_drift_rejected(self):
        spec = copy.deepcopy(self.spec)
        spec["evidence_and_decision_rule"]["ship_gate_thresholds_for_reference_only"]["max_drawdown_max"] = 0.30
        self._reject(spec)

    def test_construction_definition_drift_rejected(self):
        spec = copy.deepcopy(self.spec)
        spec["frozen_construction"]["tracked_constructions"][0]["definition"] = "ttm_revenue_div_total_mv"
        self._reject(spec)

    def test_dropped_tracked_construction_rejected(self):
        spec = copy.deepcopy(self.spec)
        spec["frozen_construction"]["tracked_constructions"] = spec["frozen_construction"]["tracked_constructions"][:2]
        self._reject(spec)

    def test_clue_factor_ids_drift_rejected(self):
        spec = copy.deepcopy(self.spec)
        spec["provenance"]["surviving_clue_factor_ids"] = ["cash_flow_to_circ_mv", "book_to_circ_mv"]
        self._reject(spec)

    def test_forward_window_start_floor_drift_rejected(self):
        spec = copy.deepcopy(self.spec)
        spec["forward_window"]["forward_window_start_floor"] = "20260101"
        self._reject(spec)

    def test_prohibited_claim_flip_rejected(self):
        spec = copy.deepcopy(self.spec)
        spec["prohibited_claims"]["real_money_authorized"] = True
        self._reject(spec)

    def test_bad_review_status_rejected(self):
        spec = copy.deepcopy(self.spec)
        spec["scope"]["preregistration_review_status"] = "self_approved"
        self._reject(spec)

    def test_single_factor_marked_promotion_primary_rejected(self):
        spec = copy.deepcopy(self.spec)
        spec["frozen_construction"]["tracked_constructions"][0]["promotion_role"] = "primary_promotion_construction"
        self._reject(spec)

    def test_diagnostics_can_independently_promote_flip_rejected(self):
        spec = copy.deepcopy(self.spec)
        spec["family_decision_rule"]["diagnostics_can_independently_promote"] = True
        self._reject(spec)

    def test_cherry_pick_guard_flip_rejected(self):
        spec = copy.deepcopy(self.spec)
        spec["family_decision_rule"]["best_of_three_post_window_selection_forbidden"] = False
        self._reject(spec)

    def test_primary_promotion_construction_drift_rejected(self):
        spec = copy.deepcopy(self.spec)
        spec["family_decision_rule"]["single_primary_promotion_construction"] = "cash_flow_to_circ_mv"
        self._reject(spec)

    def test_promotion_eligible_count_drift_rejected(self):
        spec = copy.deepcopy(self.spec)
        spec["family_decision_rule"]["promotion_eligible_construction_count"] = 3
        self._reject(spec)

    def test_test_budget_units_drift_rejected(self):
        spec = copy.deepcopy(self.spec)
        spec["planned_test_budget"]["test_budget_units"] = 3
        self._reject(spec)


if __name__ == "__main__":
    unittest.main()

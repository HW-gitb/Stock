"""Schema-first contracts for A-short experiment admission and manual baseline activation."""
from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.a_short_experiment_governance import (  # noqa: E402
    ExperimentGovernanceError,
    baseline_for_canonical_week,
    build_adjudication_suggestion,
    build_baseline_activation_plan,
    seal_experiment_admission,
    seal_user_decision_receipt,
    validate_baseline_activation_plan,
    validate_experiment_admission,
    validate_receipt_collection,
    validate_user_decision_receipt,
)
from engine.a_short_experiment_admission_registry import get_admission  # noqa: E402


FIXTURE_PATH = ROOT / "tests" / "fixtures" / "a_short_experiment_governance_admission.json"


def _fixture() -> tuple[dict, dict]:
    payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    admission = seal_experiment_admission(payload["admission"])
    receipt = copy.deepcopy(payload["receipt"])
    receipt["admission_identity_sha256"] = admission["identity_sha256"]
    receipt["old_baseline_definition_sha256"] = admission["baseline"]["definition_sha256"]
    receipt["new_baseline_definition_sha256"] = admission["candidate"]["definition_sha256"]
    return admission, seal_user_decision_receipt(receipt)


class ExperimentAdmissionTests(unittest.TestCase):
    def test_admission_receipt_and_component_only_activation_are_valid(self) -> None:
        admission, receipt = _fixture()
        validate_experiment_admission(admission)
        validate_user_decision_receipt(receipt, admission=admission)
        suggestion = build_adjudication_suggestion(admission, adjudication_sha256=receipt["adjudication_sha256"])
        self.assertTrue(suggestion["advisory_only"])
        self.assertFalse(suggestion["automatic_production_config_write"])
        current = {
            "industry_weight_profile": {
                "arm_id": "legacy",
                "definition_sha256": admission["baseline"]["definition_sha256"],
            },
            "unrelated_component": {"arm_id": "unchanged", "definition_sha256": "e" * 64},
        }
        plan = build_baseline_activation_plan(admission, receipt, current_baselines=current, prior_receipts=[])
        validate_baseline_activation_plan(plan, admission=admission, receipt=receipt)
        self.assertEqual(plan["component_replacement"]["component_id"], "industry_weight_profile")
        self.assertEqual(plan["unchanged_component_baselines"], {"unrelated_component": current["unrelated_component"]})
        self.assertEqual(plan["shadow_baseline"]["arm_id"], "legacy")
        self.assertEqual(plan["epoch_restarts"], [{"experiment_id": "a_short_overlay_top5_on_balanced_profile", "reason": "upstream_component_baseline_changed"}])
        self.assertFalse(plan["configuration_change"]["automatic_write"])
        historical_evidence = [{"decision_week": "20260720", "baseline_arm_id": "legacy"}]
        historical_before = copy.deepcopy(historical_evidence)
        self.assertEqual(baseline_for_canonical_week(plan, "20260720")["arm_id"], "legacy")
        self.assertEqual(baseline_for_canonical_week(plan, "20260727")["arm_id"], "balanced")
        self.assertEqual(historical_evidence, historical_before)

    def test_tampered_definition_digest_is_rejected(self) -> None:
        admission, _ = _fixture()
        admission["candidate"]["definition"]["weights"]["industry_heat"] = 0.20
        with self.assertRaisesRegex(ExperimentGovernanceError, "definition sha256"):
            validate_experiment_admission(admission)

    def test_resealed_statistical_pit_or_dependency_contract_drift_invalidates_receipt(self) -> None:
        admission, receipt = _fixture()
        original_arms = copy.deepcopy((admission["baseline"], admission["candidate"]))
        drift_cases = {
            "statistical": lambda value: value["statistical_contract"]["definition"].__setitem__("multiplicity", "none"),
            "pit": lambda value: value["pit_forward_contract"].__setitem__("contract_sha256", "1" * 64),
            "dependency": lambda value: value["dependency_components"][0].__setitem__("baseline_definition_sha256", "2" * 64),
        }
        for label, mutate in drift_cases.items():
            with self.subTest(label=label):
                drifted_admission = copy.deepcopy(admission)
                mutate(drifted_admission)
                drifted_admission = seal_experiment_admission(drifted_admission)
                self.assertEqual((drifted_admission["baseline"], drifted_admission["candidate"]), original_arms)
                with self.assertRaisesRegex(ExperimentGovernanceError, "admission identity"):
                    validate_user_decision_receipt(receipt, admission=drifted_admission)
                current = {"industry_weight_profile": {"arm_id": "legacy", "definition_sha256": admission["baseline"]["definition_sha256"]}}
                with self.assertRaisesRegex(ExperimentGovernanceError, "admission identity"):
                    build_baseline_activation_plan(drifted_admission, receipt, current_baselines=current, prior_receipts=[])

    def test_second_component_is_rejected_even_if_attacker_reseals_identity(self) -> None:
        admission, _ = _fixture()
        admission["one_change_only"]["changed_component_ids"].append("overlay_rank_source")
        resealed = seal_experiment_admission(admission)
        with self.assertRaisesRegex(ExperimentGovernanceError, "exactly one component"):
            validate_experiment_admission(resealed)

    def test_dependent_experiment_cannot_self_reference(self) -> None:
        admission, _ = _fixture()
        admission["dependent_experiment_ids"] = [admission["experiment_id"]]
        resealed = seal_experiment_admission(admission)
        with self.assertRaisesRegex(ExperimentGovernanceError, "dependent experiment"):
            validate_experiment_admission(resealed)

    def test_diagnostic_only_admission_cannot_yield_a_baseline_activation_plan(self) -> None:
        admission, receipt = _fixture()
        admission["track_mode"] = "diagnostic_only"
        admission = seal_experiment_admission(admission)
        receipt["admission_identity_sha256"] = admission["identity_sha256"]
        receipt = seal_user_decision_receipt(receipt)
        validate_user_decision_receipt(receipt, admission=admission)
        suggestion = build_adjudication_suggestion(admission, adjudication_sha256=receipt["adjudication_sha256"])
        self.assertEqual(suggestion["recommendation"], "diagnostic_only_no_baseline_change")
        current = {"industry_weight_profile": {"arm_id": "legacy", "definition_sha256": admission["baseline"]["definition_sha256"]}}
        with self.assertRaisesRegex(ExperimentGovernanceError, "diagnostic-only"):
            build_baseline_activation_plan(admission, receipt, current_baselines=current, prior_receipts=[])

    def test_wrong_effective_week_is_rejected(self) -> None:
        admission, receipt = _fixture()
        receipt["effective_from_canonical_week"] = receipt["decision_canonical_week"]
        receipt = seal_user_decision_receipt(receipt)
        with self.assertRaisesRegex(ExperimentGovernanceError, "after decision_canonical_week"):
            validate_user_decision_receipt(receipt, admission=admission)

    def test_p4_activation_plan_is_single_rank_source_and_restarts_only_p4b(self) -> None:
        admission = get_admission("p4_stage3_rank_source")
        _, receipt = _fixture()
        receipt.update({
            "receipt_id": "receipt-p4-stage3-overlay-score-20260801",
            "experiment_id": admission["experiment_id"],
            "admission_identity_sha256": admission["identity_sha256"],
            "component_id": admission["component_id"],
            "candidate_arm_id": admission["candidate"]["arm_id"],
            "decision_canonical_week": "20260727",
            "effective_from_canonical_week": "20260803",
            "old_baseline_definition_sha256": admission["baseline"]["definition_sha256"],
            "new_baseline_definition_sha256": admission["candidate"]["definition_sha256"],
            "allowed_configuration_path": admission["allowed_configuration_path"],
        })
        receipt = seal_user_decision_receipt(receipt)
        current = {"stage3_rank_source": {"arm_id": "final_score",
                                             "definition_sha256": admission["baseline"]["definition_sha256"]},
                   "top5_selector": {"arm_id": "frozen", "definition_sha256": "f" * 64}}
        plan = build_baseline_activation_plan(admission, receipt, current_baselines=current, prior_receipts=[])
        validate_baseline_activation_plan(plan, admission=admission, receipt=receipt)
        self.assertEqual(plan["component_replacement"]["component_id"], "stage3_rank_source")
        self.assertEqual(plan["unchanged_component_baselines"], {"top5_selector": current["top5_selector"]})
        self.assertEqual(plan["epoch_restarts"], [{"experiment_id": "a_short_p4b_portfolio_overlay_activation",
                                                     "reason": "upstream_component_baseline_changed"}])
        self.assertFalse(plan["configuration_change"]["automatic_write"])

    def test_duplicate_receipt_is_rejected(self) -> None:
        admission, receipt = _fixture()
        with self.assertRaisesRegex(ExperimentGovernanceError, "duplicate receipt_id"):
            validate_receipt_collection([receipt, copy.deepcopy(receipt)], admission=admission)
        conflicting = copy.deepcopy(receipt)
        conflicting["receipt_id"] = "receipt-industry-weight-balanced-duplicate"
        conflicting = seal_user_decision_receipt(conflicting)
        with self.assertRaisesRegex(ExperimentGovernanceError, "duplicate accepted component"):
            validate_receipt_collection([receipt, conflicting], admission=admission)

    def test_missing_dependent_epoch_restart_is_rejected(self) -> None:
        admission, receipt = _fixture()
        current = {"industry_weight_profile": {"arm_id": "legacy", "definition_sha256": admission["baseline"]["definition_sha256"]}}
        plan = build_baseline_activation_plan(admission, receipt, current_baselines=current, prior_receipts=[])
        plan["epoch_restarts"] = []
        with self.assertRaisesRegex(ExperimentGovernanceError, "epoch restarts"):
            validate_baseline_activation_plan(plan, admission=admission, receipt=receipt)

    def test_rollback_requires_a_distinct_new_user_receipt(self) -> None:
        admission, receipt = _fixture()
        rollback = copy.deepcopy(receipt)
        rollback["receipt_id"] = "receipt-industry-weight-legacy-20260801"
        rollback["candidate_arm_id"] = "legacy"
        rollback["decision_kind"] = "rollback"
        rollback["decision_canonical_week"] = "20260727"
        rollback["effective_from_canonical_week"] = "20260803"
        rollback["old_baseline_definition_sha256"] = admission["candidate"]["definition_sha256"]
        rollback["new_baseline_definition_sha256"] = admission["baseline"]["definition_sha256"]
        rollback["supersedes_receipt_id"] = receipt["receipt_id"]
        rollback = seal_user_decision_receipt(rollback)
        validate_receipt_collection([receipt, rollback], admission=admission)
        current = {"industry_weight_profile": {"arm_id": "balanced", "definition_sha256": admission["candidate"]["definition_sha256"]}}
        with self.assertRaisesRegex(ExperimentGovernanceError, "rollback must supersede"):
            build_baseline_activation_plan(admission, rollback, current_baselines=current, prior_receipts=[])
        rollback["receipt_id"] = receipt["receipt_id"]
        rollback = seal_user_decision_receipt(rollback)
        with self.assertRaisesRegex(ExperimentGovernanceError, "duplicate receipt_id"):
            validate_receipt_collection([receipt, rollback], admission=admission)


if __name__ == "__main__":
    unittest.main()

"""Frozen-admission coverage for the existing A-short evidence lanes."""
from __future__ import annotations

import copy
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.a_short_experiment_admission_registry import admissions, admission_snapshot  # noqa: E402
from engine import a_short_experiment_admission_registry as registry  # noqa: E402
from engine.a_short_experiment_governance import (  # noqa: E402
    ExperimentGovernanceError,
    seal_experiment_admission,
    validate_experiment_admission,
)


class AdmissionRegistryTests(unittest.TestCase):

    def setUp(self):
        registry._sealed_admission_from_payload.cache_clear()

    def test_admission_memo_reuses_exact_payload_and_returns_copies(self):
        with mock.patch.object(registry, "validate_experiment_admission",
                               wraps=registry.validate_experiment_admission) as validate:
            first = registry.admissions()
            first_validation_count = validate.call_count
            first["p1_regime_action_proxy"]["baseline"]["arm_id"] = "poison"
            second = registry.admissions()
        self.assertGreater(first_validation_count, 0)
        self.assertEqual(validate.call_count, first_validation_count)
        self.assertEqual(second["p1_regime_action_proxy"]["baseline"]["arm_id"], "current_build")

    def test_warm_admission_cache_cannot_skip_replaced_seal(self):
        registry.admissions()
        with mock.patch.object(
                registry, "seal_experiment_admission",
                side_effect=ExperimentGovernanceError("seal replacement probe")):
            with self.assertRaisesRegex(ExperimentGovernanceError, "seal replacement probe"):
                registry.admissions()

    def test_warm_admission_cache_cannot_skip_changed_schema(self):
        registry.admissions()
        schema = json.loads(registry.governance.ADMISSION_SCHEMA_PATH.read_text(encoding="utf-8"))
        schema["required"] = [*schema["required"], "cache_invalidation_probe"]
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "admission.schema.json"
            path.write_text(json.dumps(schema), encoding="utf-8")
            with mock.patch.object(registry.governance, "ADMISSION_SCHEMA_PATH", path):
                with self.assertRaisesRegex(ExperimentGovernanceError, "schema validation failed"):
                    registry.admissions()

    def test_every_active_lane_has_a_valid_sealed_admission(self) -> None:
        registry = admissions()
        self.assertEqual(
            set(registry),
            {
                "p0_d1_entry_anchor_entry_ma_pullback", "p0_d1_entry_anchor_entry_range_pullback",
                "p0_d3_iv_policy_iv_step_down", "p0_d3_iv_policy_iv_joint_stress",
                "p1_regime_action_proxy", "p2_target_exit_policy", "p2_breakout_entry_policy",
                "p3_selected_vs_candidate_pool", "p3_selected_vs_csi1000", "p3_managed_exit_vs_hold",
                "p4_stage3_rank_source",
                "p5_balanced_vs_legacy", "p5_aggressive_vs_balanced", "p5_theme_double_vs_balanced",
            },
        )
        for admission in registry.values():
            validate_experiment_admission(admission)
            self.assertEqual(admission["one_change_only"]["changed_component_ids"], [admission["component_id"]])

    def test_p0_excludes_old_multi_component_combination_from_new_formal_admission(self) -> None:
        registry = admissions()
        p0 = {key: value for key, value in registry.items() if key.startswith("p0_")}
        self.assertEqual(len(p0), 4)
        self.assertEqual(len({value["component_id"] for value in p0.values()}), 4)
        self.assertFalse(any("combo" in key or value["effect_surface"] == "combined_policy" for key, value in p0.items()))

    def test_p1_p3_are_diagnostic_and_p2_p5_questions_are_independent(self) -> None:
        registry = admissions()
        self.assertEqual(registry["p1_regime_action_proxy"]["track_mode"], "diagnostic_only")
        self.assertTrue(all(registry[key]["track_mode"] == "diagnostic_only" for key in registry if key.startswith("p3_")))
        self.assertEqual(registry["p2_target_exit_policy"]["component_id"], "target_exit_policy")
        self.assertEqual(registry["p2_breakout_entry_policy"]["component_id"], "breakout_entry_policy")
        self.assertEqual(registry["p4_stage3_rank_source"]["component_id"], "stage3_rank_source")
        self.assertEqual(registry["p4_stage3_rank_source"]["track_mode"], "switchable")
        self.assertEqual(registry["p4_stage3_rank_source"]["allowed_configuration_path"],
                         "A-EGS/egs_main.py#/stage3_rank_source")
        self.assertNotEqual(registry["p2_target_exit_policy"]["dependency_components"],
                            registry["p2_breakout_entry_policy"]["dependency_components"])
        p5 = [registry[key] for key in registry if key.startswith("p5_")]
        self.assertEqual({row["component_id"] for row in p5}, {"industry_weight_profile"})
        self.assertEqual(len({row["identity_sha256"] for row in p5}), 3)

    def test_p5b_adjudication_uses_the_preset_clock_as_its_only_numeric_source(self) -> None:
        definition = admissions()["p5_balanced_vs_legacy"]["statistical_contract"]["definition"]
        p5b = definition["p5b_adjudication_governance"]
        self.assertEqual(p5b["p_value_method"], "engine.a_short_overlay_adjudication._signflip_p")
        self.assertEqual(
            [int(checkpoint) for checkpoint in p5b["checkpoint_stages"]],
            definition["clock"]["checkpoints"],
        )
        self.assertNotIn("difference_minimums", p5b)
        self.assertNotIn("nonoverlap_block_minimums", p5b)
        self.assertNotIn("terminal_branches_require_difference_and_nonoverlap_minimums", p5b)

        original_load = registry._load

        def changed_p5_governance(path):
            payload = original_load(path)
            if Path(path).name == "a_short_industry_weight_comparison_governance_20260722.json":
                payload["clock_contract"]["difference_minimums"] = [7, 12, 18]
            return payload

        with mock.patch.object(registry, "_load", side_effect=changed_p5_governance):
            changed = registry._p5_admissions()["p5_balanced_vs_legacy"]
        self.assertEqual(
            changed["statistical_contract"]["definition"]["clock"]["difference_minimums"],
            [7, 12, 18],
        )

    def test_statistical_pit_and_dependency_drift_invalidates_a_registered_identity(self) -> None:
        admission = copy.deepcopy(admissions()["p2_target_exit_policy"])
        for field, mutate in (
            ("statistical", lambda value: value["statistical_contract"]["definition"].__setitem__("primary_window", "h10")),
            ("pit", lambda value: value["pit_forward_contract"].__setitem__("contract_sha256", "1" * 64)),
            ("dependency", lambda value: value["dependency_components"][0].__setitem__("baseline_definition_sha256", "2" * 64)),
        ):
            with self.subTest(field=field):
                drifted = copy.deepcopy(admission)
                mutate(drifted)
                with self.assertRaises(ExperimentGovernanceError):
                    validate_experiment_admission(drifted)
                drifted = seal_experiment_admission(drifted)
                self.assertNotEqual(drifted["identity_sha256"], admission["identity_sha256"])
                validate_experiment_admission(drifted)

    def test_one_change_only_rejects_a_second_component_even_when_resealed(self) -> None:
        admission = copy.deepcopy(admissions()["p5_balanced_vs_legacy"])
        admission["one_change_only"]["changed_component_ids"].append("unrelated_component")
        resealed = seal_experiment_admission(admission)
        with self.assertRaises(ExperimentGovernanceError):
            validate_experiment_admission(resealed)

    def test_one_change_only_rejects_resealed_undeclared_candidate_rule(self) -> None:
        admission = copy.deepcopy(admissions()["p2_target_exit_policy"])
        admission["candidate"]["definition"]["unrelated_breakout_rule"] = "forbidden_extra_change"
        with self.assertRaises(ExperimentGovernanceError):
            seal_experiment_admission(admission)

    def test_one_change_only_cannot_delete_inventory_anchors_before_resealing(self) -> None:
        admission = copy.deepcopy(admissions()["p2_target_exit_policy"])
        admission["candidate"]["definition"]["unrelated_breakout_rule"] = "forbidden_extra_change"
        admission["one_change_only"].pop("frozen_baseline_definition_sha256")
        admission["one_change_only"].pop("frozen_candidate_definition_sha256")
        with self.assertRaises(ExperimentGovernanceError):
            seal_experiment_admission(admission)

    def test_one_change_only_cannot_rewrite_inventory_anchors_before_resealing(self) -> None:
        admission = copy.deepcopy(admissions()["p2_target_exit_policy"])
        admission["candidate"]["definition"]["unrelated_breakout_rule"] = "forbidden_extra_change"
        candidate_digest = hashlib.sha256(json.dumps(
            admission["candidate"]["definition"], ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        ).encode("utf-8")).hexdigest()
        admission["one_change_only"]["frozen_candidate_definition_sha256"] = candidate_digest
        with self.assertRaises(ExperimentGovernanceError):
            seal_experiment_admission(admission)

    def test_public_snapshot_exposes_only_contract_identity_not_arm_definitions(self) -> None:
        snapshot = admission_snapshot("p1_regime_action_proxy", "p2_target_exit_policy")
        self.assertEqual(set(snapshot), {"p1_regime_action_proxy", "p2_target_exit_policy"})
        encoded = repr(snapshot)
        self.assertNotIn("candidate_proxy_description", encoded)
        self.assertNotIn("profile_weights", encoded)


if __name__ == "__main__":
    unittest.main()

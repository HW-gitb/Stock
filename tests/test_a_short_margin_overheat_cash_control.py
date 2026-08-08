"""Knife 1 contract, namespace, state and freeze-boundary tests."""
from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path
from unittest.mock import patch

import jsonschema

from engine import a_short_evidence_epoch_mode as epoch_mode
from engine import a_short_margin_overheat as production_margin
from engine import a_short_margin_overheat_cash_control as track


ROOT = Path(__file__).resolve().parents[1]


class MarginOverheatCashControlContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.governance = track.load_governance()
        cls.schema = json.loads(track.PROGRAM_SCHEMA_PATH.read_text(encoding="utf-8"))

    def test_governance_is_schema_valid_and_has_exact_two_stage_arm_sets(self):
        jsonschema.validate(self.governance, self.schema)
        self.assertEqual(track.stage_arm_ids(track.STAGE_A),
                         ("baseline", "level_p95", "change_rate_p90", "change_rate_p95"))
        self.assertEqual(track.stage_arm_ids(track.STAGE_B),
                         ("baseline", "cash_factor_0_9", "cash_factor_0_8", "cash_factor_0_7"))

    def _reject(self, mutated):
        with self.assertRaises((jsonschema.ValidationError, track.MarginOverheatCashControlError)):
            track.validate_governance(mutated)

    def test_schema_rejects_second_problem(self):
        mutated = copy.deepcopy(self.governance)
        mutated["second_question"] = {"question_id": "d1_entry_anchor"}
        self._reject(mutated)

    def test_schema_rejects_fifth_arm(self):
        mutated = copy.deepcopy(self.governance)
        mutated["stage_a"]["challengers"].append(copy.deepcopy(mutated["stage_a"]["challengers"][0]))
        self._reject(mutated)

    def test_schema_rejects_other_effect_surface(self):
        mutated = copy.deepcopy(self.governance)
        mutated["stage_a"]["challengers"][0]["effect_surface"] = "entry_type"
        self._reject(mutated)

    def test_schema_rejects_production_or_automatic_switch(self):
        for key in ("production", "production_effect_enabled", "automatic_policy_switch"):
            with self.subTest(key=key):
                mutated = copy.deepcopy(self.governance)
                mutated["boundary"][key] = True
                self._reject(mutated)

    def test_schema_rejects_history_backfill_and_cross_namespace_ledger(self):
        mutated = copy.deepcopy(self.governance)
        mutated["namespace"]["historical_backfill_forbidden"] = False
        self._reject(mutated)
        mutated = copy.deepcopy(self.governance)
        mutated["namespace"]["ledger_namespace"] = "a_short.factor_comparison_v2"
        self._reject(mutated)

    def test_all_three_production_constants_remain_off(self):
        self.assertIsNone(production_margin.MARGIN_OVERHEAT_PERCENTILE_THRESHOLD)
        self.assertIsNone(production_margin.MARGIN_OVERHEAT_CASH_FACTOR)
        self.assertFalse(production_margin.MARGIN_OVERHEAT_PRODUCTION_EFFECT_ENABLED)
        self.assertFalse(track.evidence_counts_toward_clock())
        self.assertEqual(track.current_mode(), track.PRE_FREEZE)

    def test_production_boundary_gate_rejects_each_constant_mutation(self):
        mutations = (
            ("percentile", "MARGIN_OVERHEAT_PERCENTILE_THRESHOLD", 0.95),
            ("cash_factor", "MARGIN_OVERHEAT_CASH_FACTOR", 0.80),
            ("effect", "MARGIN_OVERHEAT_PRODUCTION_EFFECT_ENABLED", True),
        )
        for label, attribute, value in mutations:
            with self.subTest(label=label), patch.object(
                production_margin, attribute, value
            ):
                with self.assertRaisesRegex(
                    track.MarginOverheatCashControlError,
                    "crossed the comparison boundary",
                ):
                    track.validate_governance(self.governance)

    def test_governance_rejects_json_integer_for_float_const(self):
        mutated = copy.deepcopy(self.governance)
        mutated["outcome_contract"]["model_cash_cny"] = 100000
        with self.assertRaisesRegex(
            track.MarginOverheatCashControlError, "numeric type mismatch"
        ):
            track.validate_governance(mutated)

    def test_trigger_floor_is_read_from_governed_state_contract(self):
        source = track.__file__
        text = Path(source).read_text(encoding="utf-8")
        self.assertIn('governance["state_contract"]["min_trigger_effective_weeks"]', text)
        self.assertNotIn("trigger_effective_weeks < 4", text)

    def test_source_binding_rejects_prose_other_context_and_other_verdicts(self):
        allowed = self.governance["source_binding"]["allowed_structured_sources"]
        track.validate_source_references(allowed)
        for forbidden in ("rendered_text", "other_market_context", "other_comparison_verdicts"):
            with self.subTest(forbidden=forbidden):
                refs = list(allowed)
                refs[-1] = forbidden
                with self.assertRaises(track.MarginOverheatCashControlError):
                    track.validate_source_references(refs)

    def test_semantic_projection_ignores_annotations_but_not_decision_fields(self):
        baseline = track.semantic_fingerprint(self.governance)
        cosmetic = copy.deepcopy(self.governance)
        cosmetic["annotations"] = {"note": "formatting and prose do not change the estimand"}
        self.assertEqual(baseline, track.semantic_fingerprint(cosmetic))
        semantic = copy.deepcopy(self.governance)
        semantic["stage_a"]["challengers"][0]["criterion_id"] = "level_percentile_p90"
        self.assertNotEqual(baseline, track.semantic_fingerprint(semantic))
        with self.assertRaises(track.MarginOverheatCashControlError):
            track.validate_governance(semantic)
        for label, path, value in (
            ("arm", ("stage_a", "challengers", 0, "arm_id"), "level_p90"),
            ("trigger gate", ("state_contract", "min_trigger_effective_weeks"), 5),
            ("cash stack", ("outcome_contract", "cash_stack"), "different_cash_stack"),
            ("settlement", ("capture_contract", "settlement_price_basis"), "different_basis"),
        ):
            with self.subTest(label=label):
                candidate = copy.deepcopy(self.governance)
                target = candidate
                for key in path[:-1]:
                    target = target[key]
                target[path[-1]] = value
                self.assertNotEqual(baseline, track.semantic_fingerprint(candidate))

    def test_current_epoch_id_is_bound_to_this_track_semantics(self):
        self.assertEqual(track.current_epoch_id(), "epoch-" + track.semantic_fingerprint()[:12])
        self.assertEqual(len(track.current_epoch_id()), 18)


class MarginOverheatCashControlStateTests(unittest.TestCase):
    def test_registry_pre_freeze_rejects_explicit_frozen_mode(self):
        self.assertEqual(track.current_mode(), track.PRE_FREEZE)
        with self.assertRaisesRegex(
            track.MarginOverheatCashControlError, "shared epoch registry"
        ):
            track.build_state(
                calendar_effective_weeks=36,
                trigger_effective_weeks=10,
                mode=track.FROZEN,
            )

    def test_pre_freeze_synthetic_36_weeks_stays_zero_and_not_evaluated(self):
        state = track.build_state(calendar_effective_weeks=36, trigger_effective_weeks=36)
        self.assertEqual(state["mode"], track.PRE_FREEZE)
        self.assertEqual(state["calendar_effective_weeks"], 0)
        self.assertEqual(state["trigger_effective_weeks"], 0)
        self.assertEqual(state["comparison_verdict"], "not_evaluated")
        self.assertEqual(state["reason"], "pre_freeze_audit_only")
        track.validate_state(state)

    def test_pre_freeze_cannot_be_given_a_supported_or_not_supported_verdict(self):
        for verdict in ("supported", "not_supported", "inconclusive"):
            with self.subTest(verdict=verdict), self.assertRaises(track.MarginOverheatCashControlError):
                track.build_state(calendar_effective_weeks=36, trigger_effective_weeks=4,
                comparison_verdict=verdict)

    def test_l1_build_state_rejects_frozen_count_without_shared_clock_gate(self):
        with patch.object(epoch_mode, "_mode", return_value=track.FROZEN), \
                patch.object(
                    epoch_mode,
                    "evidence_counts_toward_clock",
                    side_effect=epoch_mode.EvidenceEpochModeError("injected shared gate failure"),
                ):
            with self.assertRaisesRegex(
                track.MarginOverheatCashControlError, "evidence_counts_toward_clock"
            ):
                track.build_state(
                    calendar_effective_weeks=24,
                    trigger_effective_weeks=8,
                    mode=track.FROZEN,
                )

    def test_l1_validate_state_rejects_frozen_count_without_shared_clock_gate(self):
        with patch.object(epoch_mode, "_mode", return_value=track.FROZEN), \
                patch.object(epoch_mode, "evidence_counts_toward_clock", return_value=True):
            state = track.build_state(
                calendar_effective_weeks=24,
                trigger_effective_weeks=8,
                mode=track.FROZEN,
            )
        with patch.object(epoch_mode, "_mode", return_value=track.FROZEN), \
                patch.object(
                    epoch_mode,
                    "evidence_counts_toward_clock",
                    side_effect=epoch_mode.EvidenceEpochModeError("injected shared gate failure"),
                ):
            with self.assertRaisesRegex(
                track.MarginOverheatCashControlError, "evidence_counts_toward_clock"
            ):
                track.validate_state(state)

    def test_l2_validate_state_rejects_verdict_in_any_mode(self):
        state = {
            "schema_name": "a_short_margin_overheat_cash_control_state",
            "schema_version": "1.0.0",
            "track_id": track.TRACK_ID,
            "stage": track.STAGE_A,
            "mode": track.FROZEN,
            "clock_status": "not_started",
            "calendar_effective_weeks": 0,
            "trigger_effective_weeks": 0,
            "evidence_status": "insufficient_data",
            "comparison_verdict": "supported",
            "production_unchanged": True,
            "reason": "zero-week verdict injection",
        }
        with self.assertRaisesRegex(
            track.MarginOverheatCashControlError, "comparison_verdict"
        ):
            track.validate_state(state)

    def test_l3_state_schema_rejects_pre_freeze_evidence_status(self):
        state = {
            "schema_name": "a_short_margin_overheat_cash_control_state",
            "schema_version": "1.0.0",
            "track_id": track.TRACK_ID,
            "stage": track.STAGE_A,
            "mode": track.PRE_FREEZE,
            "clock_status": "not_started",
            "calendar_effective_weeks": 0,
            "trigger_effective_weeks": 0,
            "evidence_status": "review_due",
            "comparison_verdict": "not_evaluated",
            "production_unchanged": True,
            "reason": "pre_freeze_audit_only",
        }
        with self.assertRaisesRegex(jsonschema.ValidationError, "insufficient_data"):
            jsonschema.validate(state, json.loads(track.STATE_SCHEMA_PATH.read_text(encoding="utf-8")))

    def test_trigger_weeks_cannot_exceed_calendar_weeks(self):
        with self.assertRaises(track.MarginOverheatCashControlError):
            track.build_state(calendar_effective_weeks=3, trigger_effective_weeks=4)

    def test_state_schema_has_no_arbitrary_trigger_upper_bound(self):
        state_schema = json.loads(track.STATE_SCHEMA_PATH.read_text(encoding="utf-8"))
        state = {
            "schema_name": "a_short_margin_overheat_cash_control_state",
            "schema_version": "1.0.0",
            "track_id": track.TRACK_ID,
            "stage": track.STAGE_A,
            "mode": track.FROZEN,
            "clock_status": "review_due",
            "calendar_effective_weeks": 1_000_001,
            "trigger_effective_weeks": 1_000_001,
            "evidence_status": "review_due",
            "comparison_verdict": "not_evaluated",
            "production_unchanged": True,
            "reason": "schema-bound state with no arbitrary integer ceiling",
        }
        jsonschema.validate(state, state_schema)

    def test_frozen_state_requires_trigger_floor_before_review_due(self):
        cases = (
            (36, 3, "insufficient_data", "running", "insufficient_trigger_weeks"),
            (24, 4, "review_due", "review_due", "review_due"),
            (12, 4, "review_due", "review_due", "review_due"),
        )
        with patch.object(epoch_mode, "_mode", return_value=track.FROZEN), \
                patch.object(epoch_mode, "evidence_counts_toward_clock", return_value=True):
            for calendar_weeks, trigger_weeks, evidence_status, clock_status, reason in cases:
                with self.subTest(calendar_weeks=calendar_weeks, trigger_weeks=trigger_weeks):
                    state = track.build_state(
                        calendar_effective_weeks=calendar_weeks,
                        trigger_effective_weeks=trigger_weeks,
                        mode=track.FROZEN,
                    )
                    self.assertEqual(state["evidence_status"], evidence_status)
                    self.assertEqual(state["clock_status"], clock_status)
                    self.assertEqual(state["reason"], reason)
                    self.assertEqual(state["comparison_verdict"], "not_evaluated")
                    track.validate_state(state)

    def test_validate_state_rejects_frozen_nonzero_state_when_registry_is_pre_freeze(self):
        with patch.object(epoch_mode, "_mode", return_value=track.FROZEN), \
                patch.object(epoch_mode, "evidence_counts_toward_clock", return_value=True):
            state = track.build_state(
                calendar_effective_weeks=36,
                trigger_effective_weeks=4,
                mode=track.FROZEN,
            )
        with self.assertRaisesRegex(
            track.MarginOverheatCashControlError, "shared epoch registry"
        ):
            track.validate_state(state)

    def test_l4_build_state_rejects_production_constant_mutation(self):
        with patch.object(
            production_margin, "MARGIN_OVERHEAT_CASH_FACTOR", 0.80
        ):
            with self.assertRaisesRegex(
                track.MarginOverheatCashControlError, "production margin-overheat constants"
            ):
                track.build_state(calendar_effective_weeks=36, trigger_effective_weeks=36)

    def test_l4_validate_state_rejects_production_constant_mutation(self):
        state = track.build_state(calendar_effective_weeks=0, trigger_effective_weeks=0)
        with patch.object(
            production_margin, "MARGIN_OVERHEAT_CASH_FACTOR", 0.80
        ):
            with self.assertRaisesRegex(
                track.MarginOverheatCashControlError, "production margin-overheat constants"
            ):
                track.validate_state(state)


class MarginOverheatCashControlFreezeTests(unittest.TestCase):
    def test_freeze_admission_requires_every_gate_and_does_not_write(self):
        prerequisites = {key: True for key in track.FREEZE_PREREQUISITES}
        with patch.object(
            epoch_mode,
            "validate_frozen_transition",
            return_value={
                "freeze_id": "freeze-test",
                "schema_version": "1.0.0",
                "record_sha256": "a" * 64,
            },
        ):
            receipt = track.validate_freeze_admission(prerequisites)
        self.assertEqual(receipt["requested_mode"], track.FROZEN)
        self.assertTrue(receipt["new_epoch_required"])
        self.assertFalse(receipt["write_performed"])

    def test_l5_freeze_admission_rejects_shared_frozen_transition_failure(self):
        prerequisites = {key: True for key in track.FREEZE_PREREQUISITES}
        with patch.object(
            epoch_mode,
            "validate_frozen_transition",
            side_effect=epoch_mode.EvidenceEpochModeError("injected transition failure"),
        ):
            with self.assertRaisesRegex(
                track.MarginOverheatCashControlError, "validate_frozen_transition"
            ):
                track.validate_freeze_admission(prerequisites)

    def test_freeze_admission_rejects_missing_review_or_user_authorization(self):
        prerequisites = {key: True for key in track.FREEZE_PREREQUISITES}
        for key in track.FREEZE_PREREQUISITES:
            with self.subTest(key=key):
                mutated = dict(prerequisites)
                mutated[key] = False
                with self.assertRaises(track.MarginOverheatCashControlError):
                    track.validate_freeze_admission(mutated)

    def test_stage_b_is_not_available_without_stage_a_receipt_by_document(self):
        stage_b = track.load_governance()["stage_b"]
        self.assertTrue(stage_b["requires_stage_a_supported"])
        self.assertTrue(stage_b["requires_user_accepted_source_receipt"])
        self.assertTrue(stage_b["new_forward_batch_required"])


if __name__ == "__main__":
    unittest.main()

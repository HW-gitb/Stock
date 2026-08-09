"""Knife 1 contract, namespace, state and freeze-boundary tests."""
from __future__ import annotations

import copy
import json
import math
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import jsonschema

from engine import a_short_evidence_epoch_mode as epoch_mode
from engine import a_short_margin_overheat as production_margin
from engine import a_short_margin_overheat_cash_control as track
import runners.a_short_weekly_pipeline as weekly_pipeline
from runners.a_short_weekly_pipeline import build_weekly_report
from tests import test_a_short_margin_overheat_wiring as wiring_fixtures
from tests.test_a_short_weekly_pipeline import AS_OF, GEN, _normalized, _sized_lineage


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

    def test_l1_validate_state_rejects_zero_week_frozen_state_without_shared_clock_gate(self):
        """A frozen state with no weeks still claims a clock; it must pass the gate too."""
        for clock_status, evidence_status in (
            ("review_due", "review_due"),
            ("running", "accumulating"),
            ("running", "insufficient_data"),
        ):
            with self.subTest(clock_status=clock_status, evidence_status=evidence_status):
                state = {
                    "schema_name": "a_short_margin_overheat_cash_control_state",
                    "schema_version": "1.0.0",
                    "track_id": track.TRACK_ID,
                    "stage": track.STAGE_A,
                    "mode": track.FROZEN,
                    "clock_status": clock_status,
                    "calendar_effective_weeks": 0,
                    "trigger_effective_weeks": 0,
                    "evidence_status": evidence_status,
                    "comparison_verdict": "not_evaluated",
                    "production_unchanged": True,
                    "reason": evidence_status,
                }
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
                with patch.object(epoch_mode, "_mode", return_value=track.FROZEN), \
                        patch.object(epoch_mode, "evidence_counts_toward_clock", return_value=True):
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


class MarginOverheatCashControlKnife2Tests(unittest.TestCase):
    """Knife 2 producer, replay gate and the single shared-core shadow consumer."""

    @staticmethod
    def _sessions():
        return wiring_fixtures._sessions(800)

    @staticmethod
    def _inverse_margin_rows(sessions):
        ordered = sorted(sessions)
        rows = []
        bases = (
            wiring_fixtures.SSE_BALANCE,
            wiring_fixtures.SZSE_BALANCE,
            wiring_fixtures.BSE_BALANCE,
        )
        for index, trade_date in enumerate(ordered):
            scale = 2.0 - index / (len(ordered) - 1)
            for exchange, base in zip(production_margin.MARGIN_OVERHEAT_EXCHANGES, bases):
                rows.append({
                    "trade_date": trade_date,
                    "exchange_id": exchange,
                    "rzye": base * scale,
                })
        return rows

    @classmethod
    def _predicate(cls, *, rising=True, jump=False):
        sessions = cls._sessions()
        rows = wiring_fixtures._margin_rows(sessions) if rising else cls._inverse_margin_rows(sessions)
        if jump:
            rows = [
                dict(row, rzye=float(row["rzye"]) * 2.0)
                if row["trade_date"] == sessions[0] else row
                for row in rows
            ]
        facts = track.build_predicate_facts(
            rows,
            wiring_fixtures._denominator_rows(sessions),
            requested_dates=sessions,
            source_as_of=sessions[0],
        )
        return sessions, facts

    @staticmethod
    def _reports():
        weekly = build_weekly_report(
            [_normalized()],
            AS_OF,
            GEN,
            run_lineage=_sized_lineage(),
            available_cash=None,
        )
        return weekly["reports"]

    @staticmethod
    def _margin_control_input(facts, *, production_effect_enabled=False):
        return {
            "source_as_of": facts["source_as_of"],
            "source_path": track.PREDICATE_SOURCE_REFERENCES[0],
            "percentile": facts["level"]["percentile"],
            "ratio": facts["level"]["ratio"],
            "balance_yuan": facts["level"]["balance_yuan"],
            "denominator_float_mv_yuan": facts["level"]["denominator_float_mv_yuan"],
            "window_start": facts["window_start"],
            "window_end": facts["window_end"],
            "requested_session_count": facts["requested_session_count"],
            "observed_session_count": facts["observed_session_count"],
            "coverage_complete": facts["coverage_complete"],
            "production_effect_enabled": production_effect_enabled,
        }

    @classmethod
    def _shadow(cls, facts, arm_id, *, pre_holiday_control=None):
        return track.materialize_shadow_cash_control(
            facts,
            arm_id=arm_id,
            reports=cls._reports(),
            available_cash=100_000.0,
            pre_holiday_control=pre_holiday_control,
            new_exposure_capacity=200_000.0,
            as_of=AS_OF,
            source_receipt=facts["source_receipt"],
        )

    def test_producer_known_sequence_emits_level_and_twenty_session_change(self):
        sessions, facts = self._predicate()
        total = (
            wiring_fixtures.SSE_BALANCE
            + wiring_fixtures.SZSE_BALANCE
            + wiring_fixtures.BSE_BALANCE
        )
        current_ratio = total * 2.0 / wiring_fixtures.DENOMINATOR_FLOAT_MV
        older_scale = 2.0 - 20.0 / (len(sessions) - 1)
        expected_change = 2.0 / older_scale - 1.0
        self.assertEqual(facts["status"], "available")
        self.assertEqual(facts["requested_session_count"], 800)
        self.assertEqual(facts["observed_session_count"], 800)
        self.assertEqual(facts["change_rate_20d"]["sample_count"], 780)
        self.assertAlmostEqual(facts["level"]["ratio"], current_ratio)
        self.assertAlmostEqual(facts["change_rate_20d"]["value"], expected_change)
        self.assertAlmostEqual(
            facts["level"]["ratio"] * facts["level"]["denominator_float_mv_yuan"],
            facts["level"]["balance_yuan"],
        )
        track.validate_predicate_facts(facts)

    def test_producer_missing_nan_inf_and_wrong_clock_are_unavailable(self):
        sessions = self._sessions()
        missing = wiring_fixtures._margin_rows(sessions)
        missing.pop()
        facts = track.build_predicate_facts(
            missing,
            wiring_fixtures._denominator_rows(sessions),
            requested_dates=sessions,
            source_as_of=sessions[0],
        )
        self.assertEqual(facts["status"], "unavailable")
        self.assertEqual(facts["unavailable_reason"], "coverage_incomplete")

        nan_rows = wiring_fixtures._margin_rows(sessions)
        nan_rows[0]["rzye"] = math.nan
        nan_facts = track.build_predicate_facts(
            nan_rows,
            wiring_fixtures._denominator_rows(sessions),
            requested_dates=sessions,
            source_as_of=sessions[0],
        )
        self.assertEqual(nan_facts["status"], "unavailable")
        self.assertEqual(nan_facts["unavailable_reason"], "coverage_incomplete")

        inf_rows = wiring_fixtures._margin_rows(sessions)
        inf_rows[0]["rzye"] = math.inf
        inf_facts = track.build_predicate_facts(
            inf_rows,
            wiring_fixtures._denominator_rows(sessions),
            requested_dates=sessions,
            source_as_of=sessions[0],
        )
        self.assertEqual(inf_facts["status"], "unavailable")
        self.assertEqual(inf_facts["unavailable_reason"], "coverage_incomplete")

        wrong_clock = track.build_predicate_facts(
            wiring_fixtures._margin_rows(sessions),
            wiring_fixtures._denominator_rows(sessions),
            requested_dates=sessions,
            source_as_of=sessions[1],
        )
        self.assertEqual(wrong_clock["status"], "unavailable")
        self.assertEqual(wrong_clock["unavailable_reason"], "source_clock_mismatch")

        tampered = copy.deepcopy(self._predicate()[1])
        tampered["change_rate_20d"]["value"] = math.inf
        with self.assertRaisesRegex(
            track.MarginOverheatCashControlError,
            "predicate change_rate_20d.value must be finite",
        ):
            track.validate_predicate_facts(tampered)

    def test_validate_recomputes_both_percentiles_from_source_ratio_series(self):
        _, facts = self._predicate(rising=False)
        for path in ("level", "change_rate_20d"):
            with self.subTest(path=path):
                tampered = copy.deepcopy(facts)
                key = "percentile"
                actual = tampered[path][key]
                tampered[path][key] = 0.0 if actual > 0.5 else 1.0
                with self.assertRaisesRegex(
                    track.MarginOverheatCashControlError,
                    rf"predicate {path}\.percentile is not derived from source ratios",
                ):
                    track.validate_predicate_facts(
                        tampered,
                        expected_source_digest=facts["source_digest"],
                    )

    def test_replay_is_source_bound_exploratory_and_not_forward(self):
        # The source window must include the 20-session warm-up outside the
        # earliest rolling three-year window before any week is evaluable.
        sessions = wiring_fixtures._sessions(1000)
        rows = wiring_fixtures._margin_rows(sessions)
        denominator = wiring_fixtures._denominator_rows(sessions)
        facts = track.build_predicate_facts(
            rows, denominator, requested_dates=sessions, source_as_of=sessions[0]
        )
        replay = track.build_replay_frequency(
            rows,
            denominator,
            requested_dates=sessions,
            source_as_of=sessions[0],
            source_receipt=facts["source_receipt"],
        )
        self.assertTrue(replay["comparison_only"])
        self.assertTrue(replay["exploratory"])
        self.assertFalse(replay["forward_eligible"])
        self.assertEqual(len(replay["by_arm"]), 3)
        self.assertGreater(replay["evaluable_week_count"], 0)
        self.assertGreater(replay["unavailable_week_count"], 0)
        self.assertIn(replay["status"], {"PARTIAL", "COMPLETE"})

        missing = track.build_replay_frequency(
            [],
            [],
            requested_dates=sessions,
            source_as_of=sessions[0],
        )
        self.assertEqual(missing["status"], "NOT_VERIFIED")
        self.assertFalse(missing["forward_eligible"])
        self.assertIn("no source receipt", " ".join(missing["not_verified"]))

    def test_shadow_non_trigger_is_field_identical_to_baseline(self):
        _, facts = self._predicate(rising=False)
        baseline = self._shadow(facts, "baseline")
        challenger = self._shadow(facts, "level_p95")
        self.assertFalse(challenger["predicate_triggered"])
        self.assertEqual(challenger["shadow_cash_factor"], 1.0)
        self.assertEqual(baseline["shadow_reports"], challenger["shadow_reports"])
        self.assertEqual(baseline["allocation_summary"], challenger["allocation_summary"])
        for field in (
            "available_cash_start",
            "allocated_cash_total",
            "remaining_cash",
            "new_exposure_capacity_start",
            "remaining_new_exposure_capacity",
        ):
            self.assertEqual(
                baseline["allocation_summary"].get(field),
                challenger["allocation_summary"].get(field),
                msg=field,
            )
        self.assertEqual(
            baseline["cash_factor_stack"], challenger["cash_factor_stack"]
        )

    def test_shadow_preserves_normalized_production_control_and_separates_arm_label(self):
        _, facts = self._predicate(jump=True)
        result = self._shadow(facts, "level_p95")
        expected = weekly_pipeline._normalise_margin_overheat_control(
            self._margin_control_input(facts),
            AS_OF,
        )
        expected["cash_factor"] = min(expected["cash_factor"], result["shadow_cash_factor"])
        self.assertEqual(result["allocation_summary"]["margin_overheat_control"], expected)
        self.assertEqual(
            result["comparison_margin_overheat_control"],
            {
                "arm_id": "level_p95",
                "criterion_id": "level_percentile_p95",
                "predicate_triggered": True,
                "cash_factor": track.load_governance()["stage_a"]["challengers"][0]["margin_cash_factor"],
                "reason": "comparison_margin_overheat_triggered",
            },
        )
        self.assertIsNot(
            result["cash_factor_stack"],
            result["allocation_summary"]["cash_factor_stack"],
        )

    def test_shadow_trigger_uses_each_criterion_and_shared_harshest_factor(self):
        _, facts = self._predicate(jump=True)
        stage_a = track.load_governance()["stage_a"]
        configured_factors = {
            arm["arm_id"]: arm["margin_cash_factor"]
            for arm in stage_a["challengers"]
        }
        for arm_id in ("level_p95", "change_rate_p90", "change_rate_p95"):
            with self.subTest(arm_id=arm_id):
                result = self._shadow(facts, arm_id)
                self.assertTrue(result["predicate_triggered"])
                self.assertEqual(result["shadow_cash_factor"], configured_factors[arm_id])
                self.assertEqual(
                    result["cash_factor_stack"]["effective_cash_factor"], 0.8
                )
                self.assertEqual(
                    result["cash_factor_stack"]["control_factors"]["margin_overheat_control"],
                    0.8,
                )
                self.assertEqual(
                    result["allocation_summary"]["available_cash_start"], 80_000.0
                )

        pre_holiday = {
            "source_as_of": AS_OF,
            "is_pre_holiday_window": True,
            "holiday_days_ahead": weekly_pipeline.PRE_HOLIDAY_MIN_CLOSED_DAYS,
            "next_trade_date": "20260610",
            "regime_status": "defense",
        }
        result = self._shadow(facts, "level_p95", pre_holiday_control=pre_holiday)
        expected = min(0.8, float(weekly_pipeline.PRE_HOLIDAY_CASH_FACTOR))
        self.assertEqual(result["cash_factor_stack"]["effective_cash_factor"], expected)
        self.assertNotEqual(result["cash_factor_stack"]["effective_cash_factor"], 0.64)
        self.assertEqual(
            result["cash_factor_stack"]["control_factors"]["pre_holiday_control"],
            expected,
        )

    def test_shadow_private_factor_takes_minimum_against_production_factor(self):
        _, facts = self._predicate(jump=True)
        control = self._margin_control_input(facts, production_effect_enabled=True)
        with patch.object(production_margin, "MARGIN_OVERHEAT_PERCENTILE_THRESHOLD", 0.0), \
                patch.object(production_margin, "MARGIN_OVERHEAT_CASH_FACTOR", 0.6), \
                patch.object(production_margin, "MARGIN_OVERHEAT_PRODUCTION_EFFECT_ENABLED", True):
            summary = weekly_pipeline._allocate_cash_shadow(
                self._reports(),
                100_000.0,
                200_000.0,
                pre_holiday_control=None,
                margin_overheat_control=control,
                shadow_cash_factor=0.8,
                as_of=AS_OF,
            )
        self.assertEqual(
            summary["cash_factor_stack"]["control_factors"]["margin_overheat_control"],
            0.6,
        )
        self.assertEqual(summary["cash_factor_stack"]["effective_cash_factor"], 0.6)
        self.assertEqual(summary["available_cash_start"], 60_000.0)

    def test_shadow_rejects_forged_receipt_and_requires_shared_core(self):
        _, facts = self._predicate()
        forged = dict(facts["source_receipt"], source_digest="0" * 64)
        with self.assertRaisesRegex(
            track.MarginOverheatCashControlError, "source digest"
        ):
            track.materialize_shadow_cash_control(
                facts,
                arm_id="baseline",
                reports=self._reports(),
                available_cash=100_000.0,
                new_exposure_capacity=200_000.0,
                as_of=AS_OF,
                source_receipt=forged,
            )

        with patch.object(
            weekly_pipeline,
            "_allocate_cash_shadow",
            return_value={"cash_factor_stack": None},
        ):
            with self.assertRaisesRegex(
                track.MarginOverheatCashControlError, "shared allocation core"
            ):
                self._shadow(facts, "baseline")

        with self.assertRaisesRegex(
            track.MarginOverheatCashControlError, "explicit source receipt"
        ):
            track.materialize_shadow_cash_control(
                facts,
                arm_id="baseline",
                reports=self._reports(),
                available_cash=100_000.0,
                new_exposure_capacity=200_000.0,
                as_of=AS_OF,
            )

        with self.assertRaisesRegex(
            track.MarginOverheatCashControlError, "governance model cash"
        ):
            track.materialize_shadow_cash_control(
                facts,
                arm_id="baseline",
                reports=self._reports(),
                available_cash=99_999.0,
                new_exposure_capacity=200_000.0,
                as_of=AS_OF,
                source_receipt=facts["source_receipt"],
            )


class MarginOverheatCashControlKnife3Tests(unittest.TestCase):
    """Knife 3 capture, existing-cache settlement, and private/public gates."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "margin_overheat_private"
        self.sessions, self.predicate_facts = MarginOverheatCashControlKnife2Tests._predicate()
        self.candidate = _normalized()
        self.candidates = [copy.deepcopy(self.candidate)]
        self.reports = self._reports_with_one_frozen_build()
        self.identity = {
            "run_id": f"a-short-{AS_OF}-{'1' * 16}",
            "candidate_digest": "b" * 64,
            "run_date": "20260610",
            "price_data_through": AS_OF,
        }
        self.margin_facts = MarginOverheatCashControlKnife2Tests._margin_control_input(
            self.predicate_facts
        )
        self.cache = self._daily_cache()
        self.cache_path = Path(self.temp.name) / "approved_daily_cache.json"
        self.cache_path.write_text(
            json.dumps(self.cache, ensure_ascii=False, sort_keys=True), encoding="utf-8"
        )

    @staticmethod
    def _reports_with_one_frozen_build():
        reports = copy.deepcopy(MarginOverheatCashControlKnife2Tests._reports())
        report = reports[0]
        table = report["m67"]["table"]
        table["操作"] = "建仓"
        table["股数"] = 5000
        layer = report["machine"]["entry_exit_size_star"]
        layer["cash_allocation_star"] = 3
        layer["plan"] = {
            "entry_high": 2.90,
            "shares": 5000,
            "rr_at_entry_high": 2.0,
            "avg_amount_5d": 1_000_000.0,
        }
        return reports

    def _official_bundle(self, reports=None):
        weekly = {
            "as_of": AS_OF,
            "run_lineage": {
                "run_id": self.identity["run_id"],
                "candidate_digest": self.identity["candidate_digest"],
                "price_freshness": {
                    "run_date": self.identity["run_date"],
                    "price_data_through": AS_OF,
                },
            },
            "reports": copy.deepcopy(reports if reports is not None else self.reports),
        }
        receipt = {
            "run_id": self.identity["run_id"],
            "candidate_digest": self.identity["candidate_digest"],
        }
        weekly_bytes = json.dumps(
            weekly, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        return SimpleNamespace(
            weekly=weekly,
            receipt=receipt,
            weekly_bytes=weekly_bytes,
            markdown_bytes=b"validated markdown",
            receipt_bytes=b"validated receipt",
        )

    def _daily_cache(self):
        base = datetime.strptime(AS_OF, "%Y%m%d")
        dates = []
        cursor = base
        while len(dates) < 26:
            if cursor.weekday() < 5:
                dates.append(cursor.strftime("%Y%m%d"))
            cursor += timedelta(days=1)
        close0 = float(self.candidate["close"])
        stocks = []
        for index, trade_date in enumerate(dates):
            stocks.append({
                "ts_code": self.candidate["ts_code"],
                "trade_date": trade_date,
                "open": round(close0 + index * 0.01, 8),
                "close": round(close0 + index * 0.02, 8),
                "adj_factor": 1.0,
                "adj_factor_observed": True,
                "adj_factor_source": "fixed_test_cache",
                "corporate_action_verified": True,
            })
        return {
            "schema_name": "a_short_factor_comparison_v2_daily_cache",
            "schema_version": "1.0.0",
            "stocks": stocks,
            "limits": [],
            "meta": {"cache_kind": "knife3_test", "source": "fixed_test_cache"},
        }

    def _capture(self, **overrides):
        args = {
            "root": self.root,
            "decision_date": AS_OF,
            "run_identity": self.identity,
            "official_bundle": self._official_bundle(),
            "margin_facts": self.margin_facts,
            "daily_cache_document": self.cache,
            "candidates": self.candidates,
            "reports": self.reports,
            "predicate_facts": self.predicate_facts,
        }
        args.update(overrides)
        return track.capture_margin_overheat_week(**args)

    def _stored(self, name):
        return json.loads((self.root / name).read_text(encoding="utf-8"))

    def test_capture_settle_ledger_and_public_summary_are_private_and_complete(self):
        official_before = copy.deepcopy(self.reports)
        captured = self._capture()
        self.assertEqual(captured["status"], "captured")
        self.assertEqual(self.reports, official_before)

        settled = track.settle_margin_overheat_from_daily_cache(
            root=self.root, daily_cache_document=self.cache
        )
        self.assertEqual(settled["status"], "settled_from_existing_cache")
        ledger = self._stored("ledger.json")
        outcome = self._stored(f"weeks/{AS_OF}/outcome.json")
        adjudication = self._stored("adjudication.json")
        reminder = self._stored("reminder.json")
        track.validate_margin_ledger(ledger)
        track.validate_margin_outcome(outcome)
        track.validate_margin_adjudication(adjudication)
        track.validate_margin_reminder(reminder)
        self.assertEqual(ledger["entries"][0]["status"], "settled")
        self.assertEqual(outcome["payload"]["status"], "settled")
        self.assertEqual(len(outcome["payload"]["arms"]), 4)
        self.assertEqual(
            {row["horizon"] for row in outcome["payload"]["arms"][0]["horizons"]},
            {5, 10, 20},
        )

        public = track.settle_and_summarize_margin_overheat_weekly(
            root=self.root, daily_cache_path=self.cache_path, as_of=AS_OF
        )
        track.validate_margin_public_summary(public)
        self.assertEqual(public["status"], track.PUBLIC_STATUS_CURRENT)
        self.assertEqual(public["pending_user_receipt_count"], 0)
        self.assertEqual(set(public), {
            "schema_name", "schema_version", "track_id", "status", "evidence_status",
            "current_stage", "pending_user_receipt_count", "message", "production_unchanged",
        })
        public_text = json.dumps(public, ensure_ascii=False)
        for private_value in (self.candidate["ts_code"], "baseline", "payload_sha256", "private"):
            self.assertNotIn(private_value, public_text)

    def test_publish_gate_rejects_missing_validated_bundle_without_capture(self):
        with self.assertRaisesRegex(
            track.MarginOverheatCashControlError, "validated official M6.7 bundle"
        ):
            self._capture(official_bundle=None)
        self.assertFalse(self.root.exists())

    def test_weekly_order_and_missing_cache_are_nonblocking_and_clear_stale_reminder(self):
        source = Path(weekly_pipeline.__file__).read_text(encoding="utf-8")
        capture_marker = "if args.margin_overheat_cash_control_root:\n        _expect_sidecar(\"margin_overheat_cash_control_capture\")"
        self.assertLess(source.rfind("publish_weekly_bundle("), source.index(capture_marker))
        self._capture()
        settled = track.settle_margin_overheat_from_daily_cache(
            root=self.root, daily_cache_document=self.cache
        )
        reminder = settled["reminder"]
        reminder["reminders"] = [{
            "question_id": track.QUESTION_ID, "decision_date": AS_OF,
            "status": "no_count", "reason": "stale implant", "receipt_required": True,
        }]
        track.validate_margin_reminder(reminder)
        (self.root / "reminder.json").write_text(
            json.dumps(reminder, ensure_ascii=False, sort_keys=True), encoding="utf-8"
        )
        public = track.settle_and_summarize_margin_overheat_weekly(
            root=self.root,
            daily_cache_path=self.root / "missing-cache.json",
            as_of=AS_OF,
        )
        self.assertEqual(public["status"], track.PUBLIC_STATUS_UNAVAILABLE)
        self.assertEqual(self._stored("reminder.json")["reminders"], [])

    def test_same_day_drift_is_rejected_by_exact_replay_gate(self):
        self._capture()
        changed_facts = dict(self.margin_facts)
        changed_facts["ratio"] = float(changed_facts["ratio"]) + 0.001
        with self.assertRaisesRegex(
            track.MarginOverheatCashControlError,
            "margin-overheat capture replay input drifted",
        ):
            self._capture(margin_facts=changed_facts)

    def test_cross_batch_and_cross_epoch_artifact_tampering_are_rejected(self):
        self._capture()
        capture = self._stored(f"weeks/{AS_OF}/capture.json")
        capture["payload"]["experiment_batch_id"] = "foreign_batch"
        capture["payload_sha256"] = track._digest(capture["payload"])
        with self.assertRaisesRegex(
            track.MarginOverheatCashControlError, "crosses experiment batch"
        ):
            track._validate_margin_capture(capture)

        capture = self._stored(f"weeks/{AS_OF}/capture.json")
        capture["payload"]["epoch_id"] = "foreign_epoch"
        capture["payload_sha256"] = track._digest(capture["payload"])
        with self.assertRaisesRegex(
            track.MarginOverheatCashControlError, "crosses independent epoch"
        ):
            track._validate_margin_capture(capture)

    def test_forged_receipt_and_partial_write_are_rejected(self):
        self._capture()
        capture = self._stored(f"weeks/{AS_OF}/capture.json")
        receipt = self._stored(f"weeks/{AS_OF}/source_receipt.json")
        receipt["payload"]["capture_sha256"] = "0" * 64
        with self.assertRaisesRegex(
            track.MarginOverheatCashControlError, "capture_sha256 does not match capture"
        ):
            track.validate_margin_source_receipt(receipt, capture)

        (self.root / f"weeks/{AS_OF}/source_receipt.json").unlink()
        with self.assertRaisesRegex(
            track.MarginOverheatCashControlError, "partial margin-overheat capture artifact set"
        ):
            self._capture()

    def test_d1_d3_and_other_subtrack_namespace_contamination_turns_red(self):
        self._capture()
        capture = self._stored(f"weeks/{AS_OF}/capture.json")
        capture["payload"]["source_references"][-1] = "a_short.factor_comparison_v2"
        capture["payload_sha256"] = track._digest(capture["payload"])
        with self.assertRaisesRegex(
            track.MarginOverheatCashControlError,
            "source references are outside the dedicated contract",
        ):
            track._validate_margin_capture(capture)

        ledger = self._stored("ledger.json")
        ledger["track_id"] = "a_short.factor_comparison_v2"
        with self.assertRaisesRegex(
            track.MarginOverheatCashControlError, "invalid margin-overheat contract"
        ):
            track.validate_margin_ledger(ledger)

    def test_missing_adjustment_evidence_produces_question_week_no_count(self):
        bad_cache = copy.deepcopy(self.cache)
        bad_cache["stocks"][1]["adj_factor_observed"] = False
        self.cache = bad_cache
        self.root = Path(self.temp.name) / "missing_adjustment_private"
        captured = self._capture()
        self.assertEqual(captured["status"], "captured")
        settled = track.settle_margin_overheat_from_daily_cache(
            root=self.root, daily_cache_document=self.cache
        )
        self.assertEqual(
            settled["adjudication"]["payload"]["no_count_week_count"], 1
        )
        self.assertEqual(
            self._stored(f"weeks/{AS_OF}/outcome.json")["payload"]["status"], "no_count"
        )

    def test_settlement_schema_fault_returns_unavailable_without_retrying_contract_io(self):
        missing_schema = Path(self.temp.name) / "missing-public-summary.schema.json"
        with patch.object(track, "PUBLIC_SUMMARY_SCHEMA_PATH", missing_schema):
            with self.assertRaisesRegex(
                track.MarginOverheatCashControlError, "cannot read contract"
            ):
                track._public_margin_summary(track.PUBLIC_STATUS_UNAVAILABLE, as_of=AS_OF)
            public = track.settle_and_summarize_margin_overheat_weekly(
                root=self.root, daily_cache_path=self.cache_path, as_of=AS_OF
            )
        self.assertEqual(public["status"], track.PUBLIC_STATUS_UNAVAILABLE)
        self.assertEqual(public["pending_user_receipt_count"], 0)
        self.assertEqual(set(public), {
            "schema_name", "schema_version", "track_id", "status", "evidence_status",
            "current_stage", "pending_user_receipt_count", "message", "production_unchanged",
        })

    def test_wrapped_same_week_replay_drift_keeps_its_immutable_identity(self):
        try:
            try:
                raise track.MarginOverheatCashControlError(track.CAPTURE_REPLAY_DRIFT_MESSAGE)
            except track.MarginOverheatCashControlError as cause:
                raise RuntimeError("sidecar wrapper") from cause
        except RuntimeError as wrapped:
            self.assertTrue(track.is_capture_replay_drift(wrapped))


if __name__ == "__main__":
    unittest.main()

"""Knife 1 contract, namespace, state and freeze-boundary tests."""
from __future__ import annotations

import copy
import inspect
import json
import math
import subprocess
import tempfile
import unittest
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import jsonschema

from engine import a_short_evidence_epoch_mode as epoch_mode
from engine import a_short_factor_comparison as v1
from engine.a_short_factor_comparison_v2 import capture_v2_week
from engine import a_short_margin_overheat as production_margin
from engine import a_short_margin_overheat_cash_control as track
from runners.a_short_factor_comparison_v2_cache_build import materialize_incremental_cache
import runners.a_short_weekly_pipeline as weekly_pipeline
from runners.a_short_weekly_pipeline import build_weekly_report
from tests import test_a_short_margin_overheat_wiring as wiring_fixtures
from tests.test_a_short_factor_comparison_v2_cache_build import FakeTushare, _candidate as _v2_candidate
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
                         ("baseline", "change_rate_p90", "change_rate_p95"))
        self.assertEqual(track.stage_arm_ids(track.STAGE_B),
                         ("baseline", "cash_factor_0_9", "cash_factor_0_8", "cash_factor_0_7"))

    def test_governance_rejects_the_retired_level_arm(self):
        mutated = copy.deepcopy(self.governance)
        mutated["stage_a"]["challengers"].insert(0, {
            "arm_id": "level_p95",
            "kind": "challenger",
            "criterion_id": "level_percentile_p95",
            "margin_cash_factor": 0.8,
            "effect_surface": "margin_overheat_trigger",
            "one_change_only": True,
        })
        with self.assertRaisesRegex(
            track.MarginOverheatCashControlError,
            "invalid margin-overheat contract",
        ):
            track.validate_governance(mutated)

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

    def test_adjudication_has_no_unused_changed_counter(self):
        self.assertNotIn(
            "changed = 0",
            inspect.getsource(track.adjudicate_margin_overheat_cash_control),
        )

    def test_weekly_missing_margin_input_keeps_fail_closed_taxonomy(self):
        source = inspect.getsource(weekly_pipeline.main)
        self.assertIn('margin_status == "not_configured"', source)
        self.assertIn('progress_status="not_applicable"', source)
        self.assertIn('error_code="settlement_input_unavailable"', source)
        self.assertIn('progress_status="stalled"', source)
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

    def test_weekly_launcher_wires_margin_root_and_shared_cache_without_forward(self):
        launcher = (ROOT / "runners" / "weekly_screening.ps1").read_text(encoding="utf-8")
        self.assertIn(
            "$MarginOverheatCashControlRoot = Join-Path $ProjectRoot 'state\\a_short\\margin_overheat_cash_control_private\\v1'",
            launcher,
        )
        self.assertIn(
            "'--margin-overheat-cash-control-root', $MarginOverheatCashControlRoot",
            launcher,
        )
        self.assertIn(
            "'--margin-overheat-cash-control-daily-cache', $FactorComparisonV2Cache",
            launcher,
        )
        self.assertNotIn("--margin-overheat-cash-control-forward", launcher)

    def test_margin_private_root_is_gitignored(self):
        result = subprocess.run(
            [
                "git",
                "-C",
                str(ROOT),
                "check-ignore",
                "-q",
                "--",
                "state/a_short/margin_overheat_cash_control_private/v1",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_preliminary_calendar_gate_is_read_from_adjudication_contract(self):
        source = track.__file__
        text = Path(source).read_text(encoding="utf-8")
        self.assertIn('contract["preliminary_calendar_effective_weeks"]', text)
        self.assertNotIn("calendar_effective_weeks < 12", text)
        mutated = copy.deepcopy(self.governance)
        mutated["adjudication_contract"]["preliminary_calendar_effective_weeks"] = 13
        with patch.object(track, "_adjudication_contract",
                          return_value=mutated["adjudication_contract"]), \
                patch.object(epoch_mode, "_mode", return_value=track.FROZEN), \
                patch.object(epoch_mode, "evidence_counts_toward_clock", return_value=True):
            state = track.build_state(
                calendar_effective_weeks=12,
                trigger_effective_weeks=4,
                mode=track.FROZEN,
            )
        self.assertEqual((state["evidence_status"], state["clock_status"]),
                         ("accumulating", "running"))

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
        self.assertEqual(
            track.current_epoch_id(),
            "epoch-" + epoch_mode.pre_freeze_fingerprint(track.TRACK_ID)[:12],
        )
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
            price_data_through=facts["source_as_of"],
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

    def test_shadow_binds_predicate_to_price_data_through_not_decision_date(self):
        _, facts = self._predicate(jump=True)
        result = track.materialize_shadow_cash_control(
            facts,
            arm_id="change_rate_p90",
            reports=self._reports(),
            available_cash=100_000.0,
            new_exposure_capacity=200_000.0,
            as_of="20260610",
            price_data_through=facts["source_as_of"],
            source_receipt=facts["source_receipt"],
        )
        self.assertTrue(result["predicate_triggered"])

    def test_shadow_rejects_predicate_from_a_different_price_session(self):
        _, facts = self._predicate()
        with self.assertRaisesRegex(
            track.MarginOverheatCashControlError,
            "price_data_through is not bound",
        ):
            track.materialize_shadow_cash_control(
                facts,
                arm_id="baseline",
                reports=self._reports(),
                available_cash=100_000.0,
                new_exposure_capacity=200_000.0,
                as_of="20260610",
                price_data_through="20260608",
                source_receipt=facts["source_receipt"],
            )

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
        self.assertEqual(len(replay["by_arm"]), 2)
        self.assertEqual(
            tuple(row["arm_id"] for row in replay["by_arm"]),
            ("change_rate_p90", "change_rate_p95"),
        )
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

    def test_two_arm_replay_preserves_the_remaining_arm_statistics(self):
        old = json.loads((
            ROOT / "research" / "results" / "a_short"
            / "margin_overheat_cash_control_replay_frequency.json"
        ).read_text(encoding="utf-8"))
        new = json.loads((
            ROOT / "research" / "results" / "a_short"
            / "margin_overheat_cash_control_replay_frequency_two_arm_20260809.json"
        ).read_text(encoding="utf-8"))
        jsonschema.validate(
            new,
            json.loads(track.REPLAY_SCHEMA_PATH.read_text(encoding="utf-8")),
        )
        old_by_arm = {row["arm_id"]: row for row in old["by_arm"]}
        self.assertEqual(
            new["by_arm"],
            [old_by_arm["change_rate_p90"], old_by_arm["change_rate_p95"]],
        )
        self.assertEqual(
            {key: value for key, value in new.items() if key != "by_arm"},
            {key: value for key, value in old.items() if key != "by_arm"},
        )

    def test_removed_level_arm_materialization_fails_closed(self):
        _, facts = self._predicate(jump=True)
        with self.assertRaisesRegex(
            track.MarginOverheatCashControlError,
            "unknown stage-A shadow arm",
        ):
            self._shadow(facts, "level_p95")

    def test_removed_level_trigger_branch_reaches_the_unknown_arm_gate(self):
        _, facts = self._predicate(jump=True)
        with self.assertRaisesRegex(
            track.MarginOverheatCashControlError,
            "unknown stage-A shadow arm",
        ):
            track._shadow_trigger_percentile(facts, "level_p95")

    def test_shadow_non_trigger_is_field_identical_to_baseline(self):
        _, facts = self._predicate(rising=False)
        baseline = self._shadow(facts, "baseline")
        challenger = self._shadow(facts, "change_rate_p90")
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
        result = self._shadow(facts, "change_rate_p90")
        expected = weekly_pipeline._normalise_margin_overheat_control(
            self._margin_control_input(facts),
            AS_OF,
        )
        expected["cash_factor"] = min(expected["cash_factor"], result["shadow_cash_factor"])
        self.assertEqual(result["allocation_summary"]["margin_overheat_control"], expected)
        self.assertEqual(
            result["comparison_margin_overheat_control"],
            {
                "arm_id": "change_rate_p90",
                "criterion_id": "change_rate_20d_percentile_p90",
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
        for arm_id in ("change_rate_p90", "change_rate_p95"):
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
        result = self._shadow(facts, "change_rate_p90", pre_holiday_control=pre_holiday)
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
                price_data_through=facts["source_as_of"],
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
                price_data_through=facts["source_as_of"],
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
                price_data_through=facts["source_as_of"],
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
        self.assertEqual(len(outcome["payload"]["arms"]), 3)
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

    def test_unqualified_settlement_skips_revision_scoped_capture_without_guessing_revision(self):
        revision = "a" * 32
        captured = self._capture(run_revision_id=revision)
        self.assertEqual(captured["status"], "captured")
        revision_root = self.root / "weeks" / AS_OF / "revisions" / revision
        self.assertTrue((revision_root / "capture.json").is_file())
        self.assertTrue((revision_root / "source_receipt.json").is_file())
        self.assertFalse((self.root / "weeks" / AS_OF / "capture.json").exists())

        settled = track.settle_margin_overheat_from_daily_cache(
            root=self.root, daily_cache_document=self.cache,
        )
        self.assertEqual(settled["status"], "settled_from_existing_cache")
        self.assertEqual(settled["ledger"]["entries"], [])
        self.assertFalse((revision_root / "outcome.json").exists())

    def test_unqualified_settlement_still_rejects_flat_partial_capture(self):
        self._capture()
        (self.root / f"weeks/{AS_OF}/source_receipt.json").unlink()
        with self.assertRaisesRegex(
            track.MarginOverheatCashControlError,
            "partial margin-overheat capture artifact set",
        ):
            track.settle_margin_overheat_from_daily_cache(
                root=self.root, daily_cache_document=self.cache,
            )

    def test_unqualified_settlement_still_rejects_a_half_migrated_flat_partial(self):
        # A date root can carry BOTH a revisions/ container and a stray flat
        # artifact.  Only the revision-only shape means "this week was captured
        # under a revision"; a half-migrated root is still a partial flat set,
        # and the skip must not swallow it.
        self._capture()
        (self.root / "weeks" / AS_OF / "revisions" / ("c" * 32)).mkdir(parents=True)
        (self.root / f"weeks/{AS_OF}/source_receipt.json").unlink()
        with self.assertRaisesRegex(
            track.MarginOverheatCashControlError,
            "partial margin-overheat capture artifact set",
        ):
            track.settle_margin_overheat_from_daily_cache(
                root=self.root, daily_cache_document=self.cache,
            )

    def test_official_revision_partial_capture_still_rejects_missing_artifact(self):
        revision = "b" * 32
        self._capture(run_revision_id=revision)
        revision_root = self.root / "weeks" / AS_OF / "revisions" / revision
        (revision_root / "source_receipt.json").unlink()
        official_root = Path(self.temp.name) / "official-project"
        pointer = official_root / "research" / "results" / "a_short" / AS_OF / "official_revision.json"
        pointer.parent.mkdir(parents=True)
        pointer.write_text(json.dumps({
            "schema_name": "a_short_official_revision",
            "schema_version": "1.0.0",
            "decision_as_of": AS_OF,
            "selected_revision_id": revision,
            "selected_manifest_sha256": "0" * 64,
            "selected_content_digest": "1" * 64,
            "selection_status": "selected",
            "reason": "test",
            "supersedes_revision_id": None,
        }, ensure_ascii=False, sort_keys=True), encoding="utf-8")

        with self.assertRaisesRegex(
            track.MarginOverheatCashControlError,
            "partial margin-overheat capture artifact set",
        ):
            track.settle_margin_overheat_from_daily_cache(
                root=self.root,
                daily_cache_document=self.cache,
                run_revision_id=revision,
                official_project_root=official_root,
            )

    def test_p1_5_two_round_v2_cache_bootstrap_then_margin_capture(self):
        """Model P1-3's first capture and the next shared-cache consumer pass offline."""
        v2_root = Path(self.temp.name) / "state" / "a_short" / "factor_comparison_private" / "v2"
        run_date = self.identity["run_date"]
        v2_candidate = _v2_candidate(0)
        cursor = datetime.strptime(AS_OF, "%Y%m%d")
        v2_dates = []
        while len(v2_dates) < 20:
            if cursor.weekday() < 5:
                v2_dates.append(cursor.strftime("%Y%m%d"))
            cursor -= timedelta(days=1)
        original_series = list(v2_candidate["price_series"])
        v2_candidate["price_series"] = [
            {**row, "trade_date": date}
            for date, row in zip(reversed(v2_dates), original_series[-len(v2_dates):])
        ]
        sanitized = v1._safe_candidate(v2_candidate)
        v2_identity = {
            "run_id": "p1-5-v2-bootstrap",
            "run_date": run_date,
            "source_as_of": AS_OF,
            "price_data_through": AS_OF,
            "candidate_digest": v1._digest([sanitized]),
            "official_m67_digest": "c" * 64,
        }
        with patch(
            "runners.a_short_factor_comparison_v2_cache_build._today",
            return_value=run_date,
        ):
            first = materialize_incremental_cache(
                root=v2_root, run_date=run_date, pro=FakeTushare()
            )
        self.assertEqual(first["status"], "no_frozen_v2_captures")
        self.assertFalse((v2_root / "daily_cache.json").exists())

        capture_v2_week(
            root=v2_root,
            decision_date=AS_OF,
            candidates=[v2_candidate],
            run_identity=v2_identity,
            forward_eligible=False,
        )
        provider = FakeTushare()
        with patch(
            "runners.a_short_factor_comparison_v2_cache_build._today",
            return_value=run_date,
        ):
            second = materialize_incremental_cache(
                root=v2_root, run_date=run_date, pro=provider
            )
        self.assertEqual(second["status"], "cache_updated")
        self.assertTrue(provider.calls)
        shared_cache = json.loads((v2_root / "daily_cache.json").read_text(encoding="utf-8"))

        captured = track.capture_margin_overheat_week(
            root=self.root,
            decision_date=AS_OF,
            run_identity=self.identity,
            official_bundle=self._official_bundle(),
            margin_facts=self.margin_facts,
            daily_cache_document=shared_cache,
            candidates=self.candidates,
            reports=self.reports,
            predicate_facts=self.predicate_facts,
            forward_eligible=False,
        )
        self.assertEqual(captured["status"], "captured")
        self.assertFalse(captured["capture"]["payload"]["forward_eligible"])
        self.assertTrue((self.root / f"weeks/{AS_OF}/capture.json").is_file())
        self.assertTrue((self.root / f"weeks/{AS_OF}/source_receipt.json").is_file())
        settled = track.settle_margin_overheat_from_daily_cache(
            root=self.root, daily_cache_document=shared_cache,
        )
        self.assertEqual(settled["status"], "settled_from_existing_cache")

    def test_capture_accepts_decision_after_the_predicate_price_clock(self):
        lagged_sessions = tuple(
            (datetime.strptime(date, "%Y%m%d") - timedelta(days=1)).strftime("%Y%m%d")
            for date in self.sessions
        )
        predicate = track.build_predicate_facts(
            wiring_fixtures._margin_rows(lagged_sessions),
            wiring_fixtures._denominator_rows(lagged_sessions),
            requested_dates=lagged_sessions,
            source_as_of=lagged_sessions[0],
        )
        official = self._official_bundle()
        price_data_through = lagged_sessions[0]
        official.weekly["run_lineage"]["price_freshness"]["price_data_through"] = price_data_through
        official.weekly["price_data_through"] = price_data_through
        official.weekly_bytes = json.dumps(
            official.weekly, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        identity = dict(self.identity, price_data_through=price_data_through, run_date="20260610")
        captured = track.capture_margin_overheat_week(
            root=self.root,
            decision_date=AS_OF,
            run_identity=identity,
            official_bundle=official,
            margin_facts=MarginOverheatCashControlKnife2Tests._margin_control_input(predicate),
            daily_cache_document=self.cache,
            candidates=self.candidates,
            reports=self.reports,
            predicate_facts=predicate,
        )
        self.assertEqual(captured["status"], "captured")
        self.assertEqual(
            captured["capture"]["payload"]["predicate_facts"]["source_as_of"],
            price_data_through,
        )

    def test_capture_rejects_predicate_from_an_earlier_price_session(self):
        lagged_sessions = tuple(
            (datetime.strptime(date, "%Y%m%d") - timedelta(days=1)).strftime("%Y%m%d")
            for date in self.sessions
        )
        predicate = track.build_predicate_facts(
            wiring_fixtures._margin_rows(lagged_sessions),
            wiring_fixtures._denominator_rows(lagged_sessions),
            requested_dates=lagged_sessions,
            source_as_of=lagged_sessions[0],
        )
        with self.assertRaisesRegex(
            track.MarginOverheatCashControlError,
            "source_as_of is not price_data_through",
        ):
            self._capture(predicate_facts=predicate)

    def test_publication_lag_reason_is_bound_to_capture_and_settlement(self):
        lagged_margin_rows = [
            row for row in wiring_fixtures._margin_rows(self.sessions)
            if row["trade_date"] != self.sessions[0]
        ]
        lagged = track.build_predicate_facts(
            lagged_margin_rows,
            wiring_fixtures._denominator_rows(self.sessions),
            requested_dates=self.sessions,
            source_as_of=self.sessions[0],
        )
        self.assertEqual(
            (lagged["status"], lagged["unavailable_reason"]),
            ("unavailable", "coverage_incomplete"),
        )
        captured = self._capture(predicate_facts=lagged)
        payload = captured["capture"]["payload"]
        self.assertEqual(payload["predicate_unavailable_reason"], "coverage_incomplete")
        settled = track.settle_margin_overheat_from_daily_cache(
            root=self.root, daily_cache_document=self.cache
        )
        outcome = self._stored(f"weeks/{AS_OF}/outcome.json")["payload"]
        self.assertEqual(outcome["reason"], "coverage_incomplete")
        self.assertEqual(
            {arm["reason"] for arm in outcome["arms"]},
            {"coverage_incomplete"},
        )

        tampered = copy.deepcopy(captured["capture"])
        tampered["payload"]["predicate_unavailable_reason"] = "predicate_facts_missing"
        tampered["payload_sha256"] = track._digest(tampered["payload"])
        with self.assertRaisesRegex(
            track.MarginOverheatCashControlError,
            "predicate unavailable reason drifted",
        ):
            track._validate_margin_capture(tampered)

    def test_publish_gate_rejects_missing_validated_bundle_without_capture(self):
        with self.assertRaisesRegex(
            track.MarginOverheatCashControlError, "validated official M6.7 bundle"
        ):
            self._capture(official_bundle=None)
        self.assertFalse(self.root.exists())

    def test_weekly_order_and_missing_cache_are_nonblocking_and_clear_stale_reminder(self):
        source = Path(weekly_pipeline.__file__).read_text(encoding="utf-8")
        capture_marker = "if args.margin_overheat_cash_control_root and m67_stage_status == \"complete\":\n        _expect_sidecar(\"margin_overheat_cash_control_capture\")"
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

    def test_missing_official_capture_degrades_without_reminder_key_error(self):
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
            daily_cache_path=self.cache_path,
            as_of=AS_OF,
            strict=True,
            run_revision_id="a" * 32,
            official_project_root=Path(self.temp.name) / "official-project-without-pointer",
        )
        self.assertEqual(public["status"], track.PUBLIC_STATUS_UNAVAILABLE)
        self.assertNotIn("official_revision_id", public)
        self.assertEqual(self._stored("reminder.json")["reminders"], [])

    def test_official_revision_identity_mismatch_does_not_bind_unavailable_summary(self):
        self._capture()
        with patch.object(
            track, "resolve_official_revision",
            return_value={"selected_revision_id": "b" * 32},
        ):
            public = track.settle_and_summarize_margin_overheat_weekly(
                root=self.root,
                daily_cache_path=self.cache_path,
                as_of=AS_OF,
                strict=True,
                run_revision_id="a" * 32,
                official_project_root=Path(self.temp.name) / "official-project",
            )
        self.assertEqual(public["status"], track.PUBLIC_STATUS_UNAVAILABLE)
        self.assertNotIn("official_revision_id", public)

    def test_exact_official_revision_can_bind_unavailable_summary_without_capture(self):
        self._capture()
        week_root = self.root / "weeks" / AS_OF
        (week_root / "capture.json").unlink()
        (week_root / "source_receipt.json").unlink()
        week_root.rmdir()
        revision = "a" * 32
        with patch.object(
            track, "resolve_official_revision",
            return_value={"selected_revision_id": revision},
        ):
            public = track.settle_and_summarize_margin_overheat_weekly(
                root=self.root,
                daily_cache_path=self.cache_path,
                as_of=AS_OF,
                strict=True,
                run_revision_id=revision,
                official_project_root=Path(self.temp.name) / "official-project",
            )
        self.assertEqual(public["status"], track.PUBLIC_STATUS_UNAVAILABLE)
        self.assertEqual(public["official_revision_id"], revision)
        track.validate_margin_public_summary(public)

    def test_exact_official_revision_can_bind_evidence_current_summary(self):
        revision = "b" * 32
        self._capture(run_revision_id=revision)
        with patch.object(
            track, "resolve_official_revision",
            return_value={"selected_revision_id": revision},
        ):
            public = track.settle_and_summarize_margin_overheat_weekly(
                root=self.root,
                daily_cache_path=self.cache_path,
                as_of=AS_OF,
                strict=True,
                run_revision_id=revision,
                official_project_root=Path(self.temp.name) / "official-project",
            )
        self.assertEqual(public["status"], track.PUBLIC_STATUS_CURRENT)
        self.assertEqual(public["official_revision_id"], revision)
        track.validate_margin_public_summary(public)

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

    def test_capture_validator_rejects_arm_definition_and_snapshot_drift(self):
        self._capture()
        capture = self._stored(f"weeks/{AS_OF}/capture.json")
        definitions = capture["payload"]["arm_definitions"]
        definitions[0], definitions[1] = definitions[1], definitions[0]
        capture["payload_sha256"] = track._digest(capture["payload"])
        with self.assertRaisesRegex(
            track.MarginOverheatCashControlError, "arm definitions drifted"
        ):
            track._validate_margin_capture(capture)

        capture = self._stored(f"weeks/{AS_OF}/capture.json")
        snapshots = capture["payload"]["arms"]
        snapshots[0], snapshots[1] = snapshots[1], snapshots[0]
        capture["payload_sha256"] = track._digest(capture["payload"])
        with self.assertRaisesRegex(
            track.MarginOverheatCashControlError, "arm snapshots drifted"
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

    def test_missing_adjustment_evidence_keeps_question_week_pending(self):
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
            settled["adjudication"]["payload"]["no_count_week_count"], 0
        )
        self.assertEqual(
            self._stored(f"weeks/{AS_OF}/outcome.json")["payload"]["status"], "pending"
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
        with patch.object(track, "PUBLIC_SUMMARY_SCHEMA_PATH", missing_schema):
            with self.assertRaises(track.MarginOverheatCashControlError):
                track.settle_and_summarize_margin_overheat_weekly(
                    root=self.root, daily_cache_path=self.cache_path, as_of=AS_OF, strict=True
                )

    def test_wrapped_same_week_replay_drift_keeps_its_immutable_identity(self):
        try:
            try:
                raise track.MarginOverheatCashControlError(track.CAPTURE_REPLAY_DRIFT_MESSAGE)
            except track.MarginOverheatCashControlError as cause:
                raise RuntimeError("sidecar wrapper") from cause
        except RuntimeError as wrapped:
            self.assertTrue(track.is_capture_replay_drift(wrapped))


class MarginOverheatCashControlKnife4Tests(unittest.TestCase):
    """Knife 4: source-bound formal decisions, Stage-B admission, and freeze identity."""

    @contextmanager
    def _frozen_clock(self):
        with patch.object(epoch_mode, "_mode", return_value=track.FROZEN), \
                patch.object(epoch_mode, "evidence_counts_toward_clock", return_value=True), \
                patch.object(epoch_mode, "fingerprint_or_pre_freeze", return_value="f" * 64):
            yield

    @staticmethod
    def _risk_evidence(*, cash_drag_pct=10.0):
        return {
            "max_drawdown_pct": 5.0,
            "bad_name_rate": 0.20,
            "tail_loss_pct": -2.0,
            "loss_distribution_count": 2,
            "cash_drag_pct": cash_drag_pct,
            "unfilled_rate": 0.0,
            "fill_rate": 1.0,
            "turnover_pct": 25.0,
            "total_cost_pct": 0.08,
            "max_name_weight_pct": 25.0,
            "adjustment_coverage_pct": 100.0,
            "loss_distribution_basis": "filled_positions_only",
        }

    def _synthetic_evidence(self, *, calendar_weeks, trigger_weeks, primary_effect,
                            primary_cash_drag_pct=10.0, trigger_weeks_by_arm=None,
                            effects_by_arm=None):
        self.assertLessEqual(trigger_weeks, calendar_weeks)
        start = datetime(2026, 1, 5)
        challengers = track.stage_arm_ids(track.STAGE_A)[1:]
        trigger_weeks_by_arm = trigger_weeks_by_arm or {
            arm_id: trigger_weeks if arm_id == "change_rate_p90" else 0
            for arm_id in challengers
        }
        effects_by_arm = effects_by_arm or {"change_rate_p90": primary_effect}
        rows_by_arm = {arm_id: [] for arm_id in challengers}
        by_arm = {
            "baseline": {
                "settled_week_count": calendar_weeks,
                "pending_week_count": 0,
                "no_count_week_count": 0,
                "trigger_effective_week_count": 0,
                "source_bound_effective_week_count": calendar_weeks,
            },
        }
        for arm_id in challengers:
            by_arm[arm_id] = {
                "settled_week_count": calendar_weeks,
                "pending_week_count": 0,
                "no_count_week_count": 0,
                "trigger_effective_week_count": trigger_weeks_by_arm[arm_id],
                "source_bound_effective_week_count": calendar_weeks,
            }
        source_rows = []
        for index in range(calendar_weeks):
            decision = start + timedelta(days=14 * index)
            decision_date = decision.strftime("%Y%m%d")
            source_row = {"decision_date": decision_date, "arms": {}}
            for arm_id in challengers:
                triggered = index < trigger_weeks_by_arm[arm_id]
                effect = effects_by_arm.get(arm_id, 0.0) if triggered else 0.0
                risk = self._risk_evidence(
                    cash_drag_pct=(primary_cash_drag_pct if arm_id == "change_rate_p90" else 10.0)
                )
                row = {
                    "decision_date": decision_date,
                    "evaluation_exit_date": (decision + timedelta(days=10)).strftime("%Y%m%d"),
                    "epoch_id": "epoch-current",
                    "state": "triggered" if triggered and arm_id == "change_rate_p90" else "non_triggered",
                    "effect_pct": effect,
                    "risk_evidence": risk,
                    "baseline_risk_evidence": self._risk_evidence(),
                }
                rows_by_arm[arm_id].append(row)
                source_row["arms"][arm_id] = {"triggered": row["state"] == "triggered"}
            source_rows.append(source_row)
        return {
            "stage": track.STAGE_A,
            "capture_count": calendar_weeks,
            "settled_week_count": calendar_weeks,
            "pending_week_count": 0,
            "no_count_week_count": 0,
            "rows_by_arm": rows_by_arm,
            "by_arm": by_arm,
            "no_count_rates": {arm_id: 0.0 for arm_id in challengers},
            "source_rows": source_rows,
            "calendar_effective_weeks": calendar_weeks,
            "trigger_effective_weeks": trigger_weeks,
            "current_epoch_id": "epoch-current",
        }

    def test_synthetic_11_12_24_36_clock_and_verdict_boundaries(self):
        with self._frozen_clock():
            eleven = track.build_state(
                calendar_effective_weeks=11, trigger_effective_weeks=4, mode=track.FROZEN,
            )
            self.assertEqual((eleven["evidence_status"], eleven["comparison_verdict"]),
                             ("accumulating", "not_evaluated"))
            twelve = track.build_state(
                calendar_effective_weeks=12, trigger_effective_weeks=4, mode=track.FROZEN,
            )
            self.assertEqual((twelve["evidence_status"], twelve["comparison_verdict"]),
                             ("review_due", "not_evaluated"))
            self.assertEqual(
                track._formal_decision(self._synthetic_evidence(
                    calendar_weeks=11, trigger_weeks=4, primary_effect=2.0,
                ))["status"],
                "accumulating",
            )
            self.assertEqual(
                track._formal_decision(self._synthetic_evidence(
                    calendar_weeks=12, trigger_weeks=4, primary_effect=2.0,
                ))["status"],
                "preliminary_review_due",
            )
            for calendar_weeks in (24, 36):
                with self.subTest(calendar_weeks=calendar_weeks):
                    state = track.build_state(
                        calendar_effective_weeks=calendar_weeks,
                        trigger_effective_weeks=3,
                        mode=track.FROZEN,
                    )
                    formal = track._formal_decision(self._synthetic_evidence(
                        calendar_weeks=calendar_weeks, trigger_weeks=3, primary_effect=2.0,
                    ))
                    self.assertEqual((state["evidence_status"], state["comparison_verdict"]),
                                     ("insufficient_data", "not_evaluated"))
                    self.assertEqual((formal["status"], formal["verdict"]),
                                     ("insufficient_trigger_weeks", "not_evaluated"))

    def test_adjudicated_state_formal_gates_have_point_named_guards(self):
        with self._frozen_clock():
            with self.assertRaisesRegex(
                track.MarginOverheatCashControlError, "formal calendar checkpoint",
            ):
                track._build_adjudicated_state(
                    calendar_effective_weeks=23,
                    trigger_effective_weeks=4,
                    stage=track.STAGE_A,
                    comparison_verdict="supported",
                    reason="formal_supported",
                )
            with self.assertRaisesRegex(
                track.MarginOverheatCashControlError, "trigger opportunity floor",
            ):
                track._build_adjudicated_state(
                    calendar_effective_weeks=24,
                    trigger_effective_weeks=3,
                    stage=track.STAGE_A,
                    comparison_verdict="supported",
                    reason="formal_supported",
                )

        with patch.object(epoch_mode, "_mode", return_value=track.PRE_FREEZE):
            with self.assertRaisesRegex(
                track.MarginOverheatCashControlError, "frozen epoch mode",
            ):
                track._build_adjudicated_state(
                    calendar_effective_weeks=24,
                    trigger_effective_weeks=4,
                    stage=track.STAGE_A,
                    comparison_verdict="supported",
                    reason="formal_supported",
                )

        with self._frozen_clock():
            adjudication = self._supported_stage_a_adjudication()
            state = copy.deepcopy(adjudication["state"])
            payload = copy.deepcopy(adjudication["payload"])
            state["calendar_effective_weeks"] = 23
            payload["calendar_effective_weeks"] = 23
            with self.assertRaisesRegex(
                track.MarginOverheatCashControlError,
                "bypassed the formal calendar or trigger gate",
            ):
                track._validate_adjudicated_state(state, payload)

    def test_formal_support_inconclusive_and_reliable_harm_are_distinct(self):
        with self._frozen_clock():
            supported = track._formal_decision(self._synthetic_evidence(
                calendar_weeks=24, trigger_weeks=14, primary_effect=2.0,
            ))
            self.assertEqual(
                (supported["status"], supported["verdict"], supported["winner"]),
                ("formal_supported", "supported", "change_rate_p90"),
            )
            inconclusive = track._formal_decision(self._synthetic_evidence(
                calendar_weeks=24, trigger_weeks=14, primary_effect=2.0,
                primary_cash_drag_pct=99.0,
            ))
            self.assertEqual(
                (inconclusive["status"], inconclusive["verdict"]),
                ("formal_inconclusive", "inconclusive"),
            )
            harm = track._formal_decision(self._synthetic_evidence(
                calendar_weeks=36, trigger_weeks=12, primary_effect=-2.0,
                trigger_weeks_by_arm={arm_id: 12 for arm_id in track.stage_arm_ids(track.STAGE_A)[1:]},
                effects_by_arm={arm_id: -2.0 for arm_id in track.stage_arm_ids(track.STAGE_A)[1:]},
            ))
            self.assertEqual(
                (harm["status"], harm["verdict"], harm["winner"]),
                ("formal_not_supported", "not_supported", None),
            )

    def test_formal_not_supported_requires_all_challenger_arms_to_pass_trigger_floor(self):
        with self._frozen_clock():
            partial = track._formal_decision(self._synthetic_evidence(
                calendar_weeks=36, trigger_weeks=12, primary_effect=-2.0,
            ))
        self.assertEqual(
            (partial["status"], partial["verdict"], partial["winner"]),
            ("formal_inconclusive", "inconclusive", None),
        )

    def test_cross_epoch_random_effects_requires_qualified_epoch_blocks(self):
        contract = track._adjudication_contract()
        blocks = []
        for epoch_id, effect in (("epoch-old", 1.0), ("epoch-current", 1.5)):
            for index in range(4):
                blocks.append({
                    "epoch_id": epoch_id,
                    "effect_pct": effect,
                    "decision_date": f"20260{1 if epoch_id == 'epoch-old' else 2}{index + 1:02d}",
                    "evaluation_exit_date": f"20260{1 if epoch_id == 'epoch-old' else 2}{index + 2:02d}",
                })
        result = track._cross_epoch_random_effects(
            blocks, current_epoch_id="epoch-current", contract=contract,
        )
        self.assertEqual(result["method"], "random_effects_reml_hartung_knapp")
        self.assertTrue(result["epochs"]["epoch-current"]["qualified_for_cross_epoch"])

    def test_freeze_manifest_is_annotation_insensitive_and_decision_sensitive(self):
        capture_schema = json.loads(track.CAPTURE_SCHEMA_PATH.read_text(encoding="utf-8"))
        cosmetic = copy.deepcopy(capture_schema)
        cosmetic["description"] = "formatting-only annotation"
        self.assertEqual(
            track._schema_validation_projection(capture_schema),
            track._schema_validation_projection(cosmetic),
        )
        decision = copy.deepcopy(capture_schema)
        decision["properties"]["payload"]["properties"]["stage"]["enum"].append("forbidden")
        self.assertNotEqual(
            track._schema_validation_projection(capture_schema),
            track._schema_validation_projection(decision),
        )
        manifest = track.build_margin_overheat_freeze_manifest()
        track.validate_margin_overheat_freeze_manifest(manifest)
        self.assertIn("capture", manifest["payload"]["schema_contracts"])
        self.assertIn("margin_overheat_track", manifest["payload"]["python_contracts"])

    def _supported_stage_a_adjudication(self):
        payload = {
            "question_id": track.QUESTION_ID,
            "experiment_batch_id": track.load_governance()["namespace"]["experiment_batch_id"],
            "epoch_id": "epoch-stage-a",
            "stage": track.STAGE_A,
            "capture_count": 24,
            "settled_week_count": 24,
            "pending_week_count": 0,
            "no_count_week_count": 0,
            "calendar_effective_weeks": 24,
            "trigger_effective_weeks": 12,
            "current_epoch_id": "epoch-stage-a",
            "source_bound_record_count": 24,
            "evidence_sha256": "a" * 64,
            "formal_checkpoint": 24,
            "formal_status": "formal_supported",
            "formal_verdict": "supported",
            "winning_arm_id": "change_rate_p90",
            "by_arm": {},
            "arm_statistics": [],
            "finalist_comparisons": {},
        }
        state = track._build_adjudicated_state(
            calendar_effective_weeks=24,
            trigger_effective_weeks=12,
            stage=track.STAGE_A,
            comparison_verdict="supported",
            reason="formal_supported",
        )
        adjudication = {
            "schema_name": "a_short_margin_overheat_cash_control_adjudication",
            "schema_version": track.CAPTURE_SCHEMA_VERSION,
            "track_id": track.TRACK_ID,
            "comparison_only": True,
            "payload": payload,
            "payload_sha256": track._digest(payload),
            "state": state,
            "reminder_count": 1,
            "boundary": track._knife3_boundary(),
        }
        track.validate_margin_adjudication(adjudication)
        return adjudication

    @staticmethod
    def _weekly_capture_fixture():
        _sessions, predicate_facts = MarginOverheatCashControlKnife2Tests._predicate()
        candidate = _normalized()
        reports = MarginOverheatCashControlKnife3Tests._reports_with_one_frozen_build()
        identity = {
            "run_id": f"a-short-{AS_OF}-{'1' * 16}",
            "candidate_digest": "b" * 64,
            "run_date": "20260610",
            "price_data_through": AS_OF,
        }
        cache_owner = SimpleNamespace(candidate=candidate)
        cache = MarginOverheatCashControlKnife3Tests._daily_cache(cache_owner)
        bundle_owner = SimpleNamespace(identity=identity, reports=reports)
        official_bundle = MarginOverheatCashControlKnife3Tests._official_bundle(bundle_owner)
        return {
            "decision_date": AS_OF,
            "run_identity": identity,
            "official_bundle": official_bundle,
            "margin_facts": MarginOverheatCashControlKnife2Tests._margin_control_input(
                predicate_facts
            ),
            "daily_cache_document": cache,
            "candidates": [candidate],
            "reports": reports,
            "predicate_facts": predicate_facts,
            "forward_eligible": True,
        }

    def _register_stage_b_fixture(self, root, *, expires_on):
        root.mkdir(parents=True)
        adjudication = self._supported_stage_a_adjudication()
        (root / "adjudication.json").write_text(
            json.dumps(adjudication, ensure_ascii=False, sort_keys=True), encoding="utf-8",
        )
        accepted = track.accept_stage_a_transition_receipt(
            track.build_stage_a_transition_receipt(
                adjudication=adjudication, issued_on="20260601", expires_on=expires_on,
            ),
            accepted_on="20260602",
        )
        registration = track.register_stage_b_from_accepted_receipt(
            root=root, receipt=accepted, as_of="20260603",
        )
        return adjudication, accepted, registration

    def test_source_bound_collector_rejects_tampering_and_ignores_other_question_payload(self):
        with tempfile.TemporaryDirectory() as temp_root, self._frozen_clock():
            root = Path(temp_root) / "margin_overheat_private"
            args = self._weekly_capture_fixture()
            track.capture_margin_overheat_week(root=root, **args)
            track.settle_margin_overheat_from_daily_cache(
                root=root, daily_cache_document=args["daily_cache_document"],
            )
            ledger = json.loads((root / "ledger.json").read_text(encoding="utf-8"))
            capture = json.loads((root / f"weeks/{AS_OF}/capture.json").read_text(encoding="utf-8"))
            outcome = json.loads((root / f"weeks/{AS_OF}/outcome.json").read_text(encoding="utf-8"))
            receipt = json.loads((root / f"weeks/{AS_OF}/source_receipt.json").read_text(encoding="utf-8"))
            evidence = track._collect_source_bound_evidence(
                ledger, {AS_OF: capture}, {AS_OF: outcome}, {AS_OF: receipt},
            )
            self.assertEqual((evidence["calendar_effective_weeks"], len(evidence["source_rows"])), (1, 1))
            self.assertIsInstance(capture["payload"]["freeze_manifest"], dict)
            ineligible_ledger = copy.deepcopy(ledger)
            ineligible_ledger["entries"][0]["forward_eligible"] = False
            ineligible = track._collect_source_bound_evidence(
                ineligible_ledger, {AS_OF: capture}, {AS_OF: outcome}, {AS_OF: receipt},
            )
            self.assertEqual(
                (ineligible["capture_count"], ineligible["calendar_effective_weeks"],
                 ineligible["no_count_week_count"]),
                (1, 0, 0),
            )

            pre_freeze_capture = copy.deepcopy(capture)
            pre_freeze_capture["payload"]["epoch_id"] = "epoch-pre-freeze"
            pre_freeze_capture["payload"]["freeze_manifest_sha256"] = None
            pre_freeze_capture["payload"]["freeze_manifest"] = None
            pre_freeze_capture["payload_sha256"] = track._digest(pre_freeze_capture["payload"])
            pre_freeze_outcome = copy.deepcopy(outcome)
            pre_freeze_outcome["capture_sha256"] = pre_freeze_capture["payload_sha256"]
            pre_freeze_receipt = copy.deepcopy(receipt)
            pre_freeze_receipt["payload"]["capture_sha256"] = pre_freeze_capture["payload_sha256"]
            pre_freeze_receipt["payload"]["epoch_id"] = "epoch-pre-freeze"
            pre_freeze_ledger = copy.deepcopy(ledger)
            pre_freeze_ledger["entries"][0]["epoch_id"] = "epoch-pre-freeze"
            pre_freeze_ledger["entries"][0]["capture_sha256"] = pre_freeze_capture["payload_sha256"]
            pre_freeze_ledger["entries"][0]["source_receipt_sha256"] = track._digest(pre_freeze_receipt)
            pre_freeze = track._collect_source_bound_evidence(
                pre_freeze_ledger,
                {AS_OF: pre_freeze_capture},
                {AS_OF: pre_freeze_outcome},
                {AS_OF: pre_freeze_receipt},
            )
            self.assertEqual(
                (pre_freeze["capture_count"], pre_freeze["calendar_effective_weeks"],
                 pre_freeze["no_count_week_count"]),
                (1, 0, 0),
            )

            prior_capture = copy.deepcopy(capture)
            prior_capture["payload"]["epoch_id"] = "epoch-prior"
            prior_manifest = prior_capture["payload"]["freeze_manifest"]
            prior_manifest["payload"]["python_contracts"]["margin_overheat_track"]["semantic_ast_sha256"] = "d" * 64
            prior_manifest["payload_sha256"] = track._digest(prior_manifest["payload"])
            prior_capture["payload"]["freeze_manifest_sha256"] = prior_manifest["payload_sha256"]
            prior_capture["payload_sha256"] = track._digest(prior_capture["payload"])
            prior_outcome = copy.deepcopy(outcome)
            prior_outcome["capture_sha256"] = prior_capture["payload_sha256"]
            prior_receipt = copy.deepcopy(receipt)
            prior_receipt["payload"]["capture_sha256"] = prior_capture["payload_sha256"]
            prior_receipt["payload"]["epoch_id"] = "epoch-prior"
            prior_ledger = copy.deepcopy(ledger)
            prior_ledger["entries"][0]["epoch_id"] = "epoch-prior"
            prior_ledger["entries"][0]["capture_sha256"] = prior_capture["payload_sha256"]
            prior_ledger["entries"][0]["source_receipt_sha256"] = track._digest(prior_receipt)
            prior_evidence = track._collect_source_bound_evidence(
                prior_ledger, {AS_OF: prior_capture}, {AS_OF: prior_outcome}, {AS_OF: prior_receipt},
            )
            self.assertEqual(prior_evidence["source_rows"][0]["epoch_id"], "epoch-prior")
            changed_estimand_capture = copy.deepcopy(prior_capture)
            changed_estimand_manifest = changed_estimand_capture["payload"]["freeze_manifest"]
            changed_estimand_manifest["payload"]["estimand_sha256"] = "e" * 64
            changed_estimand_manifest["payload_sha256"] = track._digest(changed_estimand_manifest["payload"])
            changed_estimand_capture["payload"]["freeze_manifest_sha256"] = changed_estimand_manifest["payload_sha256"]
            changed_estimand_capture["payload_sha256"] = track._digest(changed_estimand_capture["payload"])
            changed_estimand_outcome = copy.deepcopy(prior_outcome)
            changed_estimand_outcome["capture_sha256"] = changed_estimand_capture["payload_sha256"]
            changed_estimand_receipt = copy.deepcopy(prior_receipt)
            changed_estimand_receipt["payload"]["capture_sha256"] = changed_estimand_capture["payload_sha256"]
            changed_estimand_ledger = copy.deepcopy(prior_ledger)
            changed_estimand_ledger["entries"][0]["capture_sha256"] = changed_estimand_capture["payload_sha256"]
            changed_estimand_ledger["entries"][0]["source_receipt_sha256"] = track._digest(changed_estimand_receipt)
            with self.assertRaisesRegex(
                track.MarginOverheatCashControlError,
                "estimand changed and requires a new experiment batch",
            ):
                track._collect_source_bound_evidence(
                    changed_estimand_ledger,
                    {AS_OF: changed_estimand_capture},
                    {AS_OF: changed_estimand_outcome},
                    {AS_OF: changed_estimand_receipt},
                )

            positive = self._synthetic_evidence(
                calendar_weeks=24, trigger_weeks=14, primary_effect=2.0,
            )
            baseline_formal = track._formal_decision(positive)
            contaminated = copy.deepcopy(positive)
            contaminated["other_comparison_ledger"] = {
                "question_id": "d1_entry_anchor",
                "extreme_return_pct": 999999.0,
                "verdict": "supported",
            }
            self.assertEqual(track._formal_decision(contaminated), baseline_formal)

            outcome_tamper = copy.deepcopy(outcome)
            outcome_tamper["payload"]["status"] = "pending"
            outcome_tamper["payload_sha256"] = track._digest(outcome_tamper["payload"])
            with self.assertRaisesRegex(track.MarginOverheatCashControlError, "settlement receipt"):
                track._collect_source_bound_evidence(
                    ledger, {AS_OF: capture}, {AS_OF: outcome_tamper}, {AS_OF: receipt},
                )

            ledger_tamper = copy.deepcopy(ledger)
            ledger_tamper["entries"][0]["outcome_sha256"] = "0" * 64
            with self.assertRaisesRegex(track.MarginOverheatCashControlError, "ledger source hash drift"):
                track._collect_source_bound_evidence(
                    ledger_tamper, {AS_OF: capture}, {AS_OF: outcome}, {AS_OF: receipt},
                )

            receipt_tamper = copy.deepcopy(receipt)
            receipt_tamper["payload"]["settlement"]["status"] = "pending"
            with self.assertRaisesRegex(track.MarginOverheatCashControlError, "settlement receipt"):
                track._collect_source_bound_evidence(
                    ledger, {AS_OF: capture}, {AS_OF: outcome}, {AS_OF: receipt_tamper},
                )

    def test_stage_b_requires_current_accepted_receipt_and_new_private_batch(self):
        with tempfile.TemporaryDirectory() as temp_root, self._frozen_clock():
            root = Path(temp_root) / "margin_overheat_private"
            root.mkdir()
            adjudication = self._supported_stage_a_adjudication()
            (root / "adjudication.json").write_text(
                json.dumps(adjudication, ensure_ascii=False, sort_keys=True), encoding="utf-8",
            )
            proposal = track.build_stage_a_transition_receipt(
                adjudication=adjudication, issued_on="20260601", expires_on="20260630",
            )
            with self.assertRaisesRegex(track.MarginOverheatCashControlError, "expired"):
                track.accept_stage_a_transition_receipt(proposal, accepted_on="20260701")
            accepted = track.accept_stage_a_transition_receipt(proposal, accepted_on="20260602")
            registration = track.register_stage_b_from_accepted_receipt(
                root=root, receipt=accepted, as_of="20260603",
            )
            self.assertEqual(registration["stage"], track.STAGE_B)
            self.assertTrue(registration["production_unchanged"])
            stage_root = root / "stage_b" / registration["experiment_batch_id"]
            self.assertTrue((stage_root / "program.json").is_file())
            ledger = json.loads((stage_root / "ledger.json").read_text(encoding="utf-8"))
            self.assertEqual((ledger["stage"], ledger["experiment_batch_id"]),
                             (track.STAGE_B, registration["experiment_batch_id"]))
            self.assertIsNone(production_margin.MARGIN_OVERHEAT_PERCENTILE_THRESHOLD)
            self.assertIsNone(production_margin.MARGIN_OVERHEAT_CASH_FACTOR)
            self.assertFalse(production_margin.MARGIN_OVERHEAT_PRODUCTION_EFFECT_ENABLED)

    def test_stage_b_capture_and_settlement_are_receipt_bound_and_private(self):
        with tempfile.TemporaryDirectory() as temp_root, self._frozen_clock():
            root = Path(temp_root) / "margin_overheat_private"
            root.mkdir()
            adjudication = self._supported_stage_a_adjudication()
            (root / "adjudication.json").write_text(
                json.dumps(adjudication, ensure_ascii=False, sort_keys=True), encoding="utf-8",
            )
            accepted = track.accept_stage_a_transition_receipt(
                track.build_stage_a_transition_receipt(
                    adjudication=adjudication, issued_on="20260601", expires_on="20261231",
                ),
                accepted_on="20260602",
            )
            registration = track.register_stage_b_from_accepted_receipt(
                root=root, receipt=accepted, as_of="20260603",
            )
            args = self._weekly_capture_fixture()
            official_before = copy.deepcopy(args["reports"])
            captured = track.capture_margin_overheat_week(
                root=root, stage=track.STAGE_B, **args,
            )
            payload = captured["capture"]["payload"]
            self.assertEqual(payload["stage"], track.STAGE_B)
            self.assertEqual(payload["experiment_batch_id"], registration["experiment_batch_id"])
            self.assertEqual(payload["stage_b_admission_sha256"], accepted["payload_sha256"])
            self.assertEqual(payload["stage_b_supported_arm_id"], "change_rate_p90")
            self.assertEqual(tuple(row["arm_id"] for row in payload["arms"]), track.stage_arm_ids(track.STAGE_B))
            self.assertEqual(args["reports"], official_before)
            stage_root = root / "stage_b" / registration["experiment_batch_id"]
            settled = track.settle_margin_overheat_from_daily_cache(
                root=root, stage=track.STAGE_B, daily_cache_document=args["daily_cache_document"],
                as_of="20260610",
            )
            self.assertEqual(settled["ledger"]["stage"], track.STAGE_B)
            self.assertTrue((stage_root / f"weeks/{AS_OF}/outcome.json").is_file())
            adjudicated = track.adjudicate_margin_overheat_cash_control(
                root=root, stage=track.STAGE_B, as_of="20260610",
            )
            self.assertEqual(
                adjudicated["status"], "adjudicated_margin_overheat_cash_control",
            )
            tampered_capture = copy.deepcopy(captured["capture"])
            tampered_capture["payload"]["stage_b_admission_sha256"] = "0" * 64
            tampered_capture["payload_sha256"] = track._digest(tampered_capture["payload"])
            with self.assertRaisesRegex(
                track.MarginOverheatCashControlError,
                "not source-bound to its accepted admission receipt",
            ):
                track._validate_stage_b_capture_admission(tampered_capture, accepted)

    def test_stage_b_rechecks_expiry_for_capture_settle_and_adjudicate(self):
        with tempfile.TemporaryDirectory() as temp_root, self._frozen_clock():
            root = Path(temp_root) / "margin_overheat_private"
            self._register_stage_b_fixture(root, expires_on="20260605")
            args = self._weekly_capture_fixture()
            for operation in ("capture", "settle", "adjudicate"):
                with self.subTest(operation=operation), self.assertRaisesRegex(
                    track.MarginOverheatCashControlError,
                    "stage-B admission receipt is expired",
                ):
                    if operation == "capture":
                        track.capture_margin_overheat_week(
                            root=root, stage=track.STAGE_B, **args,
                        )
                    elif operation == "settle":
                        track.settle_margin_overheat_from_daily_cache(
                            root=root,
                            stage=track.STAGE_B,
                            daily_cache_document=args["daily_cache_document"],
                            as_of="20260609",
                        )
                    else:
                        track.adjudicate_margin_overheat_cash_control(
                            root=root, stage=track.STAGE_B, as_of="20260609",
                        )

    def test_stage_b_rechecks_current_stage_a_supported_verdict_for_all_entries(self):
        with tempfile.TemporaryDirectory() as temp_root, self._frozen_clock():
            root = Path(temp_root) / "margin_overheat_private"
            adjudication, _accepted, _registration = self._register_stage_b_fixture(
                root, expires_on="20261231",
            )
            unsupported = copy.deepcopy(adjudication)
            unsupported["payload"]["formal_status"] = "formal_not_supported"
            unsupported["payload"]["formal_verdict"] = "not_supported"
            unsupported["payload"]["winning_arm_id"] = None
            unsupported["state"]["comparison_verdict"] = "not_supported"
            unsupported["state"]["reason"] = "formal_not_supported"
            unsupported["payload_sha256"] = track._digest(unsupported["payload"])
            track.validate_margin_adjudication(unsupported)
            (root / "adjudication.json").write_text(
                json.dumps(unsupported, ensure_ascii=False, sort_keys=True), encoding="utf-8",
            )
            args = self._weekly_capture_fixture()
            for operation in ("capture", "settle", "adjudicate"):
                with self.subTest(operation=operation), self.assertRaisesRegex(
                    track.MarginOverheatCashControlError,
                    "current supported Stage-A adjudication",
                ):
                    if operation == "capture":
                        track.capture_margin_overheat_week(
                            root=root, stage=track.STAGE_B, **args,
                        )
                    elif operation == "settle":
                        track.settle_margin_overheat_from_daily_cache(
                            root=root,
                            stage=track.STAGE_B,
                            daily_cache_document=args["daily_cache_document"],
                            as_of="20260610",
                        )
                    else:
                        track.adjudicate_margin_overheat_cash_control(
                            root=root, stage=track.STAGE_B, as_of="20260610",
                        )

    def test_stage_b_capture_rejects_pre_acceptance_backfill(self):
        with tempfile.TemporaryDirectory() as temp_root, self._frozen_clock():
            root = Path(temp_root) / "margin_overheat_private"
            root.mkdir()
            adjudication = self._supported_stage_a_adjudication()
            (root / "adjudication.json").write_text(
                json.dumps(adjudication, ensure_ascii=False, sort_keys=True), encoding="utf-8",
            )
            accepted = track.accept_stage_a_transition_receipt(
                track.build_stage_a_transition_receipt(
                    adjudication=adjudication, issued_on="20260601", expires_on="20260630",
                ),
                accepted_on="20260611",
            )
            track.register_stage_b_from_accepted_receipt(
                root=root, receipt=accepted, as_of="20260611",
            )
            with self.assertRaisesRegex(
                track.MarginOverheatCashControlError, "cannot backfill before its user acceptance",
            ):
                track.capture_margin_overheat_week(
                    root=root,
                    decision_date="20260610",
                    run_identity={
                        "run_id": "a-short-20260610-1111111111111111",
                        "candidate_digest": "b" * 64,
                        "run_date": "20260610",
                        "price_data_through": "20260610",
                    },
                    official_bundle=None,
                    margin_facts={},
                    daily_cache_document={},
                    candidates=[],
                    reports=[],
                    stage=track.STAGE_B,
                )


if __name__ == "__main__":
    unittest.main()

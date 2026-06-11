"""Tests for the V14.3 raw regime classifier (design slice 2a — pure logic, comparison-only).

Pins: each of the 4 raw regimes fires under crafted history; top-down priority
(defense > contraction > attack > shock-residual); attack requires ALL operands and any null
operand blocks it (never hard-judge attack); consecutive-day operands need the full streak with
no null; percentile thresholds resolve from the trailing window; insufficient-window and missing
CSI1000 are flagged honestly; the comparison record's divergence + forward-return backfill logic;
and code↔governance threshold parity. No data fetch, no production wiring.
"""
from __future__ import annotations

import sys
import json
import unittest
from pathlib import Path

import jsonschema

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.a_short_regime_classifier import (  # noqa: E402
    classify_raw_regime, build_comparison_record, resolve_percentiles,
    validate_comparison_record, _PERCENTILE_NEEDS, RAW_REGIMES, V14_2_REGIMES,
    FIRED_RULES_BY_REGIME, FORWARD_RETURN_BASIS, _load_governance,
)

COMP_SCHEMA = ROOT / "schemas" / "a_short_regime_comparison_weekly.schema.json"


def _benign(as_of: str) -> dict:
    """A row that triggers nothing (residual → shock)."""
    return {
        "schema_name": "a_short_market_regime_daily", "schema_version": "1.0.0",
        "as_of": as_of, "limit_up_count": 20, "limit_down_count": 5, "net_limit": 15,
        "max_limit_streak": 3, "promotion_rate": 0.30, "failed_limit_rate": 0.20,
        "iv_percentile_252d": 50.0, "csi300_ret_1d": 0.2, "csi1000_ret_1d": 0.3,
        "pct_above_ma20": 55.0, "csi1000_below_ma20": False, "data_quality_flags": [],
        "boundary": {"production": False, "comparison_only": True, "drives_phase5_risk_posture": False},
    }


def _history(n: int) -> list[dict]:
    return [_benign(f"{20240101 + i:08d}") for i in range(n)]


def _with_today(n: int, **overrides) -> list[dict]:
    rows = _history(n)
    rows[-1].update(overrides)
    return rows


class PercentileResolveTests(unittest.TestCase):
    def test_percentiles_from_window(self):
        rows = _history(252)
        pc = resolve_percentiles(rows)
        self.assertEqual(pc["_window_n"], 252)
        # all benign → every percentile equals the benign constant
        self.assertAlmostEqual(pc["limit_down_count"]["p95"], 5.0)
        self.assertAlmostEqual(pc["failed_limit_rate"]["p50"], 0.20)

    def test_nulls_excluded_from_percentile(self):
        rows = _history(10)
        rows[0]["promotion_rate"] = None
        pc = resolve_percentiles(rows)
        self.assertEqual(pc["promotion_rate"]["_n"], 9)


class RawRegimeFireTests(unittest.TestCase):
    def test_shock_residual_when_nothing_fires(self):
        out = classify_raw_regime(_history(252))
        self.assertEqual(out["raw_regime"], "shock")
        self.assertEqual(out["fired_rule"], "residual")

    def test_defense_iv_absolute_even_thin_history(self):
        out = classify_raw_regime(_with_today(3, iv_percentile_252d=95.0))
        self.assertEqual(out["raw_regime"], "defense")
        self.assertIn("iv_percentile_252d_gt_90", out["candidate_hits"]["defense"])

    def test_defense_broad_index_crash(self):
        out = classify_raw_regime(_with_today(252, csi1000_ret_1d=-4.0))
        self.assertEqual(out["raw_regime"], "defense")
        self.assertIn("broad_index_crash", out["candidate_hits"]["defense"])

    def test_defense_limit_down_floor(self):
        out = classify_raw_regime(_with_today(252, limit_down_count=120))
        self.assertEqual(out["raw_regime"], "defense")
        self.assertIn("limit_down_count_ge_max_p95_100", out["candidate_hits"]["defense"])

    def test_defense_exhaustion(self):
        out = classify_raw_regime(_with_today(
            252, promotion_rate=0.05, net_limit=-5, failed_limit_rate=0.40))
        self.assertEqual(out["raw_regime"], "defense")
        self.assertIn("exhaustion", out["candidate_hits"]["defense"])

    def test_contraction_streak_collapse(self):
        rows = _history(252)
        rows[-2]["max_limit_streak"] = 6   # recent_3d peak >= 5
        rows[-1]["max_limit_streak"] = 2   # <=3, drop = 6-2 = 4 >= 2
        out = classify_raw_regime(rows)
        self.assertEqual(out["raw_regime"], "contraction")
        self.assertIn("streak_collapse", out["candidate_hits"]["contraction"])

    def test_contraction_earning_effect_gone(self):
        rows = _history(252)
        rows[-2]["promotion_rate"] = 0.20   # 2 consecutive < 0.25
        rows[-1]["promotion_rate"] = 0.20
        rows[-1]["failed_limit_rate"] = 0.40   # > P75 (~0.20)
        out = classify_raw_regime(rows)
        self.assertEqual(out["raw_regime"], "contraction")
        self.assertIn("earning_effect_gone", out["candidate_hits"]["contraction"])

    def test_contraction_slow_bleed(self):
        rows = _history(252)
        for r in rows[-5:]:
            r["pct_above_ma20"] = 25.0   # 5 consecutive < 30
        rows[-1]["csi1000_below_ma20"] = True
        out = classify_raw_regime(rows)
        self.assertEqual(out["raw_regime"], "contraction")
        self.assertIn("slow_bleed", out["candidate_hits"]["contraction"])

    def test_attack_all_of(self):
        out = classify_raw_regime(_with_today(
            252, max_limit_streak=8, promotion_rate=0.60, net_limit=30,
            limit_down_count=3, failed_limit_rate=0.10, iv_percentile_252d=50.0))
        self.assertEqual(out["raw_regime"], "attack")
        self.assertEqual(out["fired_rule"], "attack_all_of")


class PriorityAndGuardTests(unittest.TestCase):
    def test_defense_beats_attack(self):
        # attack operands satisfied AND a defense trigger (index crash) → defense wins
        out = classify_raw_regime(_with_today(
            252, max_limit_streak=8, promotion_rate=0.60, net_limit=30,
            limit_down_count=3, failed_limit_rate=0.10, iv_percentile_252d=50.0,
            csi1000_ret_1d=-4.0))
        self.assertEqual(out["raw_regime"], "defense")
        self.assertTrue(out["candidate_hits"]["attack"])   # attack still recorded for slice 3

    def test_defense_beats_contraction(self):
        rows = _history(252)
        rows[-2]["max_limit_streak"] = 6
        rows[-1]["max_limit_streak"] = 2        # streak_collapse (contraction)
        rows[-1]["promotion_rate"] = 0.05       # + exhaustion (defense)
        rows[-1]["net_limit"] = -5
        rows[-1]["failed_limit_rate"] = 0.40
        out = classify_raw_regime(rows)
        self.assertEqual(out["raw_regime"], "defense")
        self.assertTrue(out["candidate_hits"]["contraction"])

    def test_attack_requires_all_operands(self):
        # flip net_limit to 0 → attack gate fails → residual shock
        out = classify_raw_regime(_with_today(
            252, max_limit_streak=8, promotion_rate=0.60, net_limit=0,
            limit_down_count=3, failed_limit_rate=0.10, iv_percentile_252d=50.0))
        self.assertEqual(out["raw_regime"], "shock")

    def test_attack_blocked_by_null_promotion(self):
        out = classify_raw_regime(_with_today(
            252, max_limit_streak=8, promotion_rate=None, net_limit=30,
            limit_down_count=3, failed_limit_rate=0.10, iv_percentile_252d=50.0))
        self.assertEqual(out["raw_regime"], "shock")

    def test_consecutive_breaks_on_null(self):
        rows = _history(252)
        for r in rows[-5:]:
            r["pct_above_ma20"] = 25.0
        rows[-3]["pct_above_ma20"] = None   # null breaks the 5-day streak
        rows[-1]["csi1000_below_ma20"] = True
        out = classify_raw_regime(rows)
        self.assertNotIn("slow_bleed", out["candidate_hits"]["contraction"])


class DataQualityTests(unittest.TestCase):
    def test_insufficient_window_flag(self):
        out = classify_raw_regime(_history(100))
        self.assertTrue(out["insufficient_window"])
        self.assertIn("insufficient_252d_window", out["data_quality_flags"])

    def test_sufficient_window_no_flag(self):
        out = classify_raw_regime(_history(252))
        self.assertFalse(out["insufficient_window"])
        self.assertNotIn("insufficient_252d_window", out["data_quality_flags"])

    def test_csi1000_null_flagged_and_blocks_slow_bleed(self):
        rows = _history(252)
        for r in rows[-5:]:
            r["pct_above_ma20"] = 25.0
        rows[-1]["csi1000_below_ma20"] = None
        out = classify_raw_regime(rows)
        self.assertIn("csi1000_unavailable", out["data_quality_flags"])
        self.assertNotIn("slow_bleed", out["candidate_hits"]["contraction"])

    def test_as_of_filter_ignores_later_rows(self):
        rows = _with_today(252, csi1000_ret_1d=-4.0)   # last row would be defense
        earlier = rows[-2]["as_of"]
        out = classify_raw_regime(rows, as_of=earlier)
        self.assertEqual(out["as_of"], earlier)
        self.assertEqual(out["raw_regime"], "shock")

    def test_empty_history_raises(self):
        with self.assertRaises(ValueError):
            classify_raw_regime([])


class ComparisonRecordTests(unittest.TestCase):
    def _schema(self):
        return json.loads(COMP_SCHEMA.read_text(encoding="utf-8"))

    def test_record_validates_and_divergence_true(self):
        rec = build_comparison_record(
            _with_today(252, csi1000_ret_1d=-4.0), v14_2_regime="unknown",
            generated_at="2026-06-11T15:00:00+08:00")
        jsonschema.validate(rec, self._schema())
        self.assertEqual(rec["v14_3_raw_regime"], "defense")
        self.assertTrue(rec["divergence"])
        self.assertFalse(rec["backfill_complete"])
        self.assertEqual(set(rec["forward_returns_pending"]), {"h1", "h3", "h5", "h10"})

    def test_record_no_divergence_when_equal(self):
        rec = build_comparison_record(_history(252), v14_2_regime="shock")
        self.assertEqual(rec["v14_3_raw_regime"], "shock")
        self.assertFalse(rec["divergence"])

    def test_partial_backfill(self):
        rec = build_comparison_record(
            _history(252), v14_2_regime="shock",
            forward_returns={"h1": 0.5, "h3": 1.2})
        jsonschema.validate(rec, self._schema())
        self.assertEqual(rec["forward_returns"]["h1"], 0.5)
        self.assertIsNone(rec["forward_returns"]["h5"])
        self.assertEqual(set(rec["forward_returns_pending"]), {"h5", "h10"})
        self.assertFalse(rec["backfill_complete"])

    def test_full_backfill_complete(self):
        rec = build_comparison_record(
            _history(252), v14_2_regime="shock",
            forward_returns={"h1": 0.1, "h3": 0.2, "h5": 0.3, "h10": 0.4})
        self.assertTrue(rec["backfill_complete"])
        self.assertEqual(rec["forward_returns_pending"], [])

    def test_schema_rejects_fabricated_production_boundary(self):
        rec = build_comparison_record(_history(252), v14_2_regime="shock")
        rec["boundary"]["drives_phase5_risk_posture"] = True   # const False
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(rec, self._schema())


class HistoryMaskTests(unittest.TestCase):
    """R-V143-SLICE2B-FEATURES-HISTORY-INCOMPLETE-OPERANDS-CONSUMED: a row flagged
    stk_limit_history_incomplete must not fire history-dependent rules (the classifier honours the
    producer's data-quality flag); only today-only defense + shock remain reachable."""

    FLAG = "stk_limit_history_incomplete"

    def test_slow_bleed_masked_when_history_incomplete(self):
        rows = _history(252)
        for r in rows[-5:]:
            r["pct_above_ma20"] = 25.0
        rows[-1]["csi1000_below_ma20"] = True
        rows[-1]["data_quality_flags"] = [self.FLAG]
        out = classify_raw_regime(rows)
        self.assertTrue(out["history_masked"])
        self.assertEqual(out["raw_regime"], "shock")                 # slow_bleed suppressed
        self.assertEqual(out["candidate_hits"]["contraction"], [])

    def test_streak_collapse_masked_when_history_incomplete(self):
        rows = _history(252)
        rows[-2]["max_limit_streak"] = 6
        rows[-1]["max_limit_streak"] = 2
        rows[-1]["data_quality_flags"] = [self.FLAG]
        out = classify_raw_regime(rows)
        self.assertEqual(out["raw_regime"], "shock")

    def test_attack_masked_when_history_incomplete(self):
        rows = _with_today(252, max_limit_streak=8, promotion_rate=0.60, net_limit=30,
                           limit_down_count=3, failed_limit_rate=0.10, iv_percentile_252d=50.0)
        rows[-1]["data_quality_flags"] = [self.FLAG]
        out = classify_raw_regime(rows)
        self.assertEqual(out["raw_regime"], "shock")                 # attack suppressed

    def test_defense_not_masked_when_history_incomplete(self):
        rows = _with_today(252, csi1000_ret_1d=-4.0)                 # broad-index crash (today-only)
        rows[-1]["data_quality_flags"] = [self.FLAG]
        out = classify_raw_regime(rows)
        self.assertEqual(out["raw_regime"], "defense")              # safety-first rule stays active


class ComparisonInvariantTests(unittest.TestCase):
    """R-V143-SLICE2A-COMPARISON-INVARIANTS: cross-field contradictions must be rejected by
    validate_comparison_record (and enum/basis ones also by the schema)."""

    def _schema(self):
        return json.loads(COMP_SCHEMA.read_text(encoding="utf-8"))

    def _valid(self, **fr):
        # a built record is self-validated; use it as the clean base then mutate per probe.
        return build_comparison_record(_history(252), v14_2_regime="shock", forward_returns=fr or None)

    def test_builder_self_validates_and_schema_passes(self):
        rec = self._valid(h1=0.1, h3=0.2, h5=0.3, h10=0.4)
        self.assertTrue(validate_comparison_record(rec))
        jsonschema.validate(rec, self._schema())
        self.assertEqual(rec["forward_return_basis"], FORWARD_RETURN_BASIS)

    def test_reject_equal_regime_with_divergence_true(self):
        rec = self._valid()
        rec["divergence"] = True   # v14_2==v14_3_raw=="shock" → must be False
        with self.assertRaises(ValueError):
            validate_comparison_record(rec)

    def test_reject_nonnull_horizon_in_pending(self):
        rec = self._valid(h1=0.5)            # h1 non-null
        rec["forward_returns_pending"] = ["h1", "h3", "h5", "h10"]  # but lists h1 as pending
        with self.assertRaises(ValueError):
            validate_comparison_record(rec)

    def test_reject_allnull_with_backfill_complete_true(self):
        rec = self._valid()                  # all null
        rec["backfill_complete"] = True
        with self.assertRaises(ValueError):
            validate_comparison_record(rec)

    def test_reject_allnull_with_empty_pending(self):
        rec = self._valid()                  # all null
        rec["forward_returns_pending"] = []
        with self.assertRaises(ValueError):
            validate_comparison_record(rec)

    def test_reject_fired_rule_regime_mismatch(self):
        rec = self._valid()                  # shock → fired_rule must be "residual"
        rec["v14_3_fired_rule"] = "attack_all_of"
        with self.assertRaises(ValueError):
            validate_comparison_record(rec)

    def test_reject_nonsense_v14_2_regime_validator_and_schema(self):
        rec = self._valid()
        rec["v14_2_regime"] = "nonsense_status"
        with self.assertRaises(ValueError):
            validate_comparison_record(rec)
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(rec, self._schema())

    def test_builder_rejects_nonsense_v14_2_regime(self):
        with self.assertRaises(ValueError):
            build_comparison_record(_history(252), v14_2_regime="nonsense_status")

    def test_reject_basis_mismatch_validator_and_schema(self):
        rec = self._valid()
        rec["forward_return_basis"]["unit"] = "decimal"   # not the pinned 'percent'
        with self.assertRaises(ValueError):
            validate_comparison_record(rec)
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(rec, self._schema())

    def test_schema_requires_basis(self):
        rec = self._valid()
        del rec["forward_return_basis"]
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(rec, self._schema())

    def test_builder_rejects_non_number_forward_return(self):
        # R-V143-SLICE2A-BUILDER-SCHEMA-INVALID-OUTPUT: the producer must not return a
        # schema-invalid record (string forward return) by trusting cross-field checks only.
        with self.assertRaises(ValueError):
            build_comparison_record(_history(252), v14_2_regime="shock",
                                    forward_returns={"h1": "not-a-number"})

    def test_validator_rejects_non_number_forward_return(self):
        rec = self._valid(h1=0.5)
        rec["forward_returns"]["h1"] = "not-a-number"
        with self.assertRaises(ValueError):
            validate_comparison_record(rec)

    def test_validator_rejects_missing_horizon_key(self):
        rec = self._valid()
        del rec["forward_returns"]["h5"]
        with self.assertRaises(ValueError):
            validate_comparison_record(rec)

    def test_validator_rejects_extra_horizon_key(self):
        rec = self._valid()
        rec["forward_returns"]["h2"] = 0.5   # additionalProperties:false
        with self.assertRaises(ValueError):
            validate_comparison_record(rec)

    def test_builder_rejects_non_finite_forward_return(self):
        # R-V143-SLICE2A-NONFINITE-FORWARD-RETURNS: NaN/+Inf/-Inf pass jsonschema "number" but are
        # not valid observations and must be rejected at the producer.
        for bad in (float("nan"), float("inf"), float("-inf")):
            with self.assertRaises(ValueError):
                build_comparison_record(_history(252), v14_2_regime="shock",
                                        forward_returns={"h1": bad})

    def test_validator_rejects_non_finite_forward_return(self):
        for bad in (float("nan"), float("inf"), float("-inf")):
            rec = self._valid(h1=0.5)
            rec["forward_returns"]["h1"] = bad
            with self.assertRaises(ValueError):
                validate_comparison_record(rec)

    def test_fired_rules_cover_classifier_outputs(self):
        # every fired_rule the classifier can emit is a declared rule of its regime
        cases = [
            _with_today(3, iv_percentile_252d=95.0),
            _with_today(252, csi1000_ret_1d=-4.0),
            _with_today(252, limit_down_count=120),
            _with_today(252, max_limit_streak=8, promotion_rate=0.60, net_limit=30,
                        limit_down_count=3, failed_limit_rate=0.10, iv_percentile_252d=50.0),
            _history(252),
        ]
        for h in cases:
            out = classify_raw_regime(h)
            self.assertIn(out["fired_rule"], FIRED_RULES_BY_REGIME[out["raw_regime"]])


class GovernanceParityTests(unittest.TestCase):
    """The code's threshold formulas must mirror the const-pinned governance strings."""

    def setUp(self):
        self.gov = _load_governance()

    def test_attack_threshold_strings(self):
        a = self.gov["thresholds"]["attack_all_of_confirm_3d"]
        self.assertEqual(a["max_limit_streak_ge"], "max(P75_252, 5)")
        self.assertEqual(a["promotion_rate_ge"], "max(P60_252, 0.50)")
        self.assertEqual(a["limit_down_count_le"], "min(50, max(P25_252, 10))")
        self.assertEqual(a["failed_limit_rate_le"], "P50_252")
        self.assertEqual(a["net_limit_gt"], 0)
        self.assertEqual(a["iv_percentile_252d_le"], 80.0)

    def test_defense_threshold_values(self):
        d = self.gov["thresholds"]["defense_any_of"]
        self.assertEqual(d["iv_percentile_252d_gt"], 90.0)
        self.assertEqual(d["limit_down_count_ge"], "max(P95_252, 100)")
        self.assertEqual(d["csi1000_ret_1d_le"], -3.5)
        self.assertEqual(d["csi300_ret_1d_le"], -3.0)

    def test_percentile_needs_cover_referenced_metrics(self):
        # the metrics the code computes percentiles for == the metrics the governance formulas cite
        self.assertEqual(
            set(_PERCENTILE_NEEDS),
            {"limit_down_count", "failed_limit_rate", "max_limit_streak", "promotion_rate"})
        self.assertEqual(set(RAW_REGIMES), {"defense", "contraction", "attack", "shock"})


if __name__ == "__main__":
    unittest.main()

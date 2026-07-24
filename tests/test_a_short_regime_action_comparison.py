import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from engine.a_short_regime_action_comparison import (
    build_action_record, m67_provenance, merge_action_records, summarize_action_records,
    validate_action_record, candidate_effect_eligibility, build_candidate_effect_record,
    summarize_candidate_effect_records, candidate_effect_policy_fingerprint, validate_candidate_effect_summary,
)
from engine.a_short_regime_classifier import FORWARD_RETURN_BASIS


def _regime_record(*, as_of="20260714", raw="defense", returns=None):
    values = {"h1": None, "h3": None, "h5": None, "h10": None}
    values.update(returns or {})
    pending = [h for h in ("h1", "h3", "h5", "h10") if values[h] is None]
    return {"as_of": as_of, "v14_3_raw_regime": raw, "v14_3_fired_rule": "broad_index_crash" if raw == "defense" else "residual", "forward_returns": values, "forward_returns_pending": pending, "backfill_complete": not pending, "forward_return_basis": dict(FORWARD_RETURN_BASIS)}


class RegimeActionComparisonTests(unittest.TestCase):
    def _source(self):
        return {"source_schema_name": "a_short_weekly_report", "source_as_of": "20260714", "source_sha256": "a" * 64, "candidate_build_count": 2}

    def _origin(self, *, decision_as_of="20260714", run_date=None, **overrides):
        origin = {"decision_as_of": decision_as_of, "run_date": run_date or decision_as_of}
        origin.update(overrides)
        return origin

    def test_sunday_to_monday_canonical_is_forward_when_friday_is_latest_settled_price(self):
        row = build_action_record(
            regime_record=_regime_record(), raw_v14_2_regime="shock",
            effective_v14_2_regime="shock", m67_source=self._source(),
            forward_origin=self._origin(
                decision_as_of="20260720", run_date="20260719",
                price_data_through="20260717", capture_mode="live",
                source_receipt_complete=True, price_day_latest_settled=True,
            ),
        )
        self.assertTrue(row["forward_eligible"])

    def test_freezes_unknown_raw_and_effective_fallback_separately(self):
        row = build_action_record(regime_record=_regime_record(), raw_v14_2_regime="unknown", effective_v14_2_regime="shock", m67_source=self._source(), forward_origin=self._origin())
        self.assertEqual(row["raw_v14_2_regime"], "unknown")
        self.assertEqual(row["effective_v14_2_regime"], "shock")
        self.assertTrue(row["action_diverges"])
        self.assertEqual(row["baseline_action"]["max_exposure_pct"], 60)
        self.assertEqual(row["candidate_action"]["max_exposure_pct"], 0)

    def test_pending_and_action_relations_fail_closed(self):
        row = build_action_record(regime_record=_regime_record(), raw_v14_2_regime="shock", effective_v14_2_regime="shock", m67_source=self._source(), forward_origin=self._origin())
        row["action_diverges"] = False
        with self.assertRaises(ValueError):
            validate_action_record(row)

    def test_forward_eligibility_is_derived_and_cannot_be_self_labelled(self):
        row = build_action_record(regime_record=_regime_record(), raw_v14_2_regime="shock",
                                  effective_v14_2_regime="shock", m67_source=self._source(),
                                  forward_origin=self._origin(run_date="20260715"))
        self.assertFalse(row["forward_eligible"])
        row["forward_eligible"] = True
        with self.assertRaises(ValueError):
            validate_action_record(row)

    def test_same_week_conflict_is_rejected(self):
        a = build_action_record(regime_record=_regime_record(), raw_v14_2_regime="shock", effective_v14_2_regime="shock", m67_source=self._source(), forward_origin=self._origin())
        b = dict(a)
        b["raw_v14_2_regime"] = "attack"
        with self.assertRaises(ValueError):
            merge_action_records([a], b)

    def test_summary_needs_full_forward_gate(self):
        rows = []
        for i in range(12):
            as_of = f"202607{i+1:02d}"
            row = build_action_record(regime_record=_regime_record(as_of=as_of, returns={"h1": 1.0, "h3": 1.0, "h5": 1.0, "h10": -1.0}), raw_v14_2_regime="shock", effective_v14_2_regime="shock", m67_source=self._source(), forward_origin=self._origin(decision_as_of=as_of))
            rows.append(row)
        self.assertEqual(summarize_action_records(rows)["status"], "review_candidate_preferred")

    def test_summary_rejects_multiple_forward_records_from_one_run_date(self):
        rows = []
        for i in range(2):
            as_of = f"202607{i + 1:02d}"
            rows.append(build_action_record(
                regime_record=_regime_record(as_of=as_of), raw_v14_2_regime="shock",
                effective_v14_2_regime="shock", m67_source=self._source(),
                forward_origin=self._origin(decision_as_of="20260714", run_date="20260714")))
        with self.assertRaises(ValueError):
            summarize_action_records(rows)

    def test_historical_replay_is_never_counted_as_forward_evidence(self):
        row = build_action_record(
            regime_record=_regime_record(returns={"h1": 1.0, "h3": 1.0, "h5": 1.0, "h10": 1.0}),
            raw_v14_2_regime="shock", effective_v14_2_regime="shock", m67_source=self._source(),
            forward_origin=self._origin(run_date="20260715"))
        summary = summarize_action_records([row])
        self.assertEqual(summary["total_forward_weeks"], 0)
        self.assertEqual(summary["historical_not_counted"], 1)
        self.assertEqual(summary["status"], "accumulating")

    def test_m67_provenance_persists_digest_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "weekly.json"
            path.write_text(json.dumps({"schema_name": "a_short_weekly_report", "as_of": "20260714", "reports": [{"row_source": "egs_candidate", "m67": {"table": {"操作": "建仓"}}}]}), encoding="utf-8")
            result = m67_provenance(path, as_of="20260714")
        self.assertEqual(result["candidate_build_count"], 1)
        self.assertEqual(result["source_as_of"], "20260714")
        self.assertEqual(len(result["source_sha256"]), 64)


def _candidate(as_of, ts_code, **overrides):
    row = {"as_of": as_of, "ts_code": ts_code, "row_source": "egs_candidate", "m67_action": "建仓"}
    row.update(overrides)
    return row


def _state(as_of, regime="defense", evaluable=True):
    return {"as_of": as_of, "stateful_regime": regime if evaluable else None, "state_evaluable": evaluable}


def _returns(stock, benchmark=0.0, h20=None):
    return {
        "stock_net_returns": {"h5": stock, "h10": stock, "h20": stock if h20 is None else h20},
        "csi1000_returns": {"h5": benchmark, "h10": benchmark, "h20": benchmark},
    }


def _candidate_record(as_of, ts_code, stock, *, h20=None, mode="live", regime="defense"):
    return build_candidate_effect_record(
        candidate=_candidate(as_of, ts_code), stateful_regime=_state(as_of, regime),
        forward_returns=_returns(stock, h20=h20),
        evidence_origin={"capture_mode": mode, "decision_as_of": as_of},
    )


class CandidateEffectTests(unittest.TestCase):
    def test_public_admission_rejects_private_or_result_payload_fields(self):
        summary = summarize_candidate_effect_records([])
        for field in ("ts_code", "account", "holding", "price", "return"):
            bad = copy.deepcopy(summary)
            bad["admission"]["p1_regime_action_proxy"][field] = "private"
            with self.assertRaises(ValueError):
                validate_candidate_effect_summary(bad)
        stale = copy.deepcopy(summary)
        stale["policy"]["policy_fingerprint"] = "0" * 64
        with self.assertRaises(ValueError):
            validate_candidate_effect_summary(stale)

    def _twelve_weeks(self, stock, *, h20=None):
        start = __import__("datetime").date(2026, 7, 6)
        rows = []
        for week in range(12):
            as_of = (start + __import__("datetime").timedelta(days=week * 7)).strftime("%Y%m%d")
            rows.extend([
                _candidate_record(as_of, f"000{week:02d}.SZ", stock, h20=h20),
                _candidate_record(as_of, f"001{week:02d}.SZ", stock, h20=h20),
            ])
        return rows

    def test_defense_and_contraction_forbid_new_build_with_cash_proxy(self):
        for regime in ("defense", "contraction"):
            row = _candidate_record("20260706", "000001.SZ", -2.0, regime=regime)
            self.assertTrue(row["candidate_new_build_forbidden"])
            self.assertEqual(row["candidate_net_returns"]["h10"], 0.0)
            self.assertEqual(row["operation_improvement_pp"]["h10"], 2.0)

    def test_holding_watch_veto_and_manual_rows_never_enter(self):
        for overrides in (
            {"row_source": "egs_candidate_with_position"}, {"is_watch": True},
            {"is_vetoed": True}, {"manual_review": True},
        ):
            candidate = _candidate("20260706", "000001.SZ", **overrides)
            eligible, _ = candidate_effect_eligibility(candidate)
            self.assertFalse(eligible)
            self.assertIsNone(build_candidate_effect_record(
                candidate=candidate, stateful_regime=_state("20260706"),
                forward_returns=_returns(-1.0),
                evidence_origin={"capture_mode": "live", "decision_as_of": "20260706"},
            ))

    def test_same_week_multiple_stocks_are_one_equal_weighted_week_sample(self):
        rows = [
            _candidate_record("20260706", "000001.SZ", -1.0),
            _candidate_record("20260706", "000002.SZ", -3.0),
        ]
        summary = summarize_candidate_effect_records(rows)
        self.assertEqual(summary["evidence_progress"]["valid_divergence_weeks"], 1)
        self.assertEqual(summary["evidence_progress"]["valid_divergence_stocks"], 2)
        self.assertEqual(summary["operation_effect"]["weekly_mean_improvement_pp"], 2.0)

    def test_avoiding_falling_stocks_is_candidate_better_when_gate_is_complete(self):
        summary = summarize_candidate_effect_records(self._twelve_weeks(-1.0, h20=-1.0))
        self.assertTrue(summary["evidence_progress"]["ready_for_verdict"])
        self.assertEqual(summary["verdict"], "candidate_better")
        self.assertEqual(summary["selection_accuracy"]["status"], "supportive")

    def test_missing_rising_stocks_is_baseline_better_when_gate_is_complete(self):
        summary = summarize_candidate_effect_records(self._twelve_weeks(1.0, h20=1.0))
        self.assertEqual(summary["verdict"], "baseline_better")
        self.assertEqual(summary["selection_accuracy"]["status"], "not_supportive")

    def test_mixed_results_are_no_material_difference(self):
        rows = self._twelve_weeks(-1.0, h20=-1.0)
        for row in rows[12:]:  # latter six weeks miss comparable upside instead
            row["baseline_net_returns"] = {"h5": 1.0, "h10": 1.0, "h20": 1.0}
            row["candidate_net_returns"] = {"h5": 0.0, "h10": 0.0, "h20": 0.0}
            row["csi1000_returns"] = {"h5": 0.0, "h10": 0.0, "h20": 0.0}
            row["operation_improvement_pp"] = {"h5": -1.0, "h10": -1.0, "h20": -1.0}
            row["baseline_excess_csi1000_pp"] = {"h5": 1.0, "h10": 1.0, "h20": 1.0}
            row["candidate_excess_csi1000_pp"] = {"h5": 0.0, "h10": 0.0, "h20": 0.0}
        summary = summarize_candidate_effect_records(rows)
        self.assertEqual(summary["verdict"], "no_material_difference")

    def test_historical_or_immature_returns_do_not_count_as_zero(self):
        historical = _candidate_record("20260706", "000001.SZ", -1.0, mode="historical_replay")
        immature = _candidate_record("20260713", "000002.SZ", -1.0)
        immature["baseline_net_returns"]["h10"] = None
        immature["candidate_net_returns"]["h10"] = None
        immature["operation_improvement_pp"]["h10"] = None
        immature["baseline_excess_csi1000_pp"]["h10"] = None
        immature["candidate_excess_csi1000_pp"]["h10"] = None
        summary = summarize_candidate_effect_records([historical, immature])
        self.assertEqual(summary["evidence_progress"]["historical_not_counted"], 1)
        self.assertEqual(summary["evidence_progress"]["valid_divergence_weeks"], 0)
        self.assertEqual(summary["verdict"], "insufficient_data")

    def test_policy_fingerprint_mismatch_cannot_mix(self):
        rows = self._twelve_weeks(-1.0, h20=-1.0)
        rows[-1]["policy_fingerprint"] = "0" * 64
        with self.assertRaises(ValueError):
            summarize_candidate_effect_records(rows)

    def test_runtime_source_drift_changes_p1_policy_fingerprint(self):
        baseline = candidate_effect_policy_fingerprint()
        with patch("engine.a_short_regime_action_comparison._runtime_policy_source_fingerprint",
                   return_value="runtime-source-drift"):
            self.assertNotEqual(candidate_effect_policy_fingerprint(), baseline)

    def test_duplicate_asof_and_stock_cannot_double_count(self):
        row = _candidate_record("20260706", "000001.SZ", -1.0)
        with self.assertRaises(ValueError):
            summarize_candidate_effect_records([row, dict(row)])

    def test_non_evaluable_state_never_invents_cash_action(self):
        row = build_candidate_effect_record(
            candidate=_candidate("20260706", "000001.SZ"),
            stateful_regime=_state("20260706", evaluable=False), forward_returns=_returns(-1.0),
            evidence_origin={"capture_mode": "live", "decision_as_of": "20260706"},
        )
        self.assertFalse(row["candidate_new_build_forbidden"])
        self.assertIsNone(row["stateful_regime"])


if __name__ == "__main__":
    unittest.main()

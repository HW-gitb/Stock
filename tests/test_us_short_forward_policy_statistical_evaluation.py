# -*- coding: utf-8 -*-
"""Cut D-analysis: offline verdict consumer for the frozen A1 statistical plan."""
from __future__ import annotations

import copy
from datetime import date, timedelta
import unittest
from unittest import mock

from engine import us_short_forward_policy_decision_diff as decision_diff
from engine import us_short_forward_policy_statistical_evaluation as evaluation
from engine import us_short_paper_scorecard_comparison as scorecard_comparison
from engine.us_short_forward_policy_heads import SELECTION_POLICY_IDS


POLICIES = tuple(SELECTION_POLICY_IDS)
SHADOW = "theme_plus"
CANDIDATES = ["T%02d" % index for index in range(30)]
BALANCED = CANDIDATES[:15]


def _net_result(value: float) -> dict:
    return {
        "outcome": "filled_tp_exit" if value >= 0.0 else "filled_stopped",
        "realized": True,
        "gross_return": value,
        "cost_fraction": 0.0,
        "net_return": value,
        "unfilled_cash": False,
    }


def _cash_unfilled() -> dict:
    return {
        "outcome": "cash_unfilled",
        "realized": True,
        "gross_return": 0.0,
        "cost_fraction": 0.0,
        "net_return": 0.0,
        "unfilled_cash": True,
    }


def _capture(decision_date: str, *, shadow_replacement: str | None = "T15", source_digest: str) -> dict:
    decision = date(int(decision_date[:4]), int(decision_date[4:6]), int(decision_date[6:8]))
    selections = {name: list(BALANCED) for name in POLICIES}
    if shadow_replacement is not None:
        selections[SHADOW] = BALANCED[1:] + [shadow_replacement]
    return {
        "schema_name": "us_short_forward_policy_shadow_selection",
        "schema_version": "1.0.0",
        "decision_date": decision_date,
        "price_basis_date": (decision - timedelta(days=3)).strftime("%Y%m%d"),
        "generated_at": "2026-07-12T08:00:00-04:00",
        "source_context_sha256": source_digest,
        "selection_policies": list(POLICIES),
        "selection_decisions": {
            name: {
                "out_of_window": False,
                "decision_date": decision_date,
                "price_basis_date": (decision - timedelta(days=3)).strftime("%Y%m%d"),
                "run_date": (decision - timedelta(days=1)).strftime("%Y%m%d"),
                "cheap_eligible": list(CANDIDATES),
                "candidates": list(CANDIDATES),
                "recall_available": False,
                "recall_added": [],
                "recall_excluded": [],
                "exclusion_records": [],
                "admitted": selections[name],
                "selection_seats": {},
                "theme_selection_mode": "industry_heat_v1_cross_industry_disabled",
                "full_analysis_leader_upgrades": [],
                "selection_details": [],
                "holdings": [],
            }
            for name in POLICIES
        },
        "boundary": {
            "track": "comparison_non_production",
            "evidence_level": "shadow_selection_only",
            "shadow_counts_ship_gate": False,
            "full_size_ship_gate_allowed": False,
            "provider_calls_added": False,
            "broker_or_order_automation_allowed": False,
        },
    }


def _scorecard(capture: dict, candidate_values: dict[str, float], *, fills: dict[str, int] | None = None) -> dict:
    fills = fills or {}
    net_results = {}
    for name, decision in capture["selection_decisions"].items():
        filled_count = fills.get(name, len(decision["admitted"]))
        net_results[name] = {
            ticker: _net_result(candidate_values[ticker]) if index < filled_count else _cash_unfilled()
            for index, ticker in enumerate(decision["admitted"])
        }
    return scorecard_comparison.build_policy_scorecard_comparison_from_capture(capture, net_results)


def _week(
    index: int,
    *,
    shadow_replacement: str | None = "T15",
    values: dict[str, float] | None = None,
    fills: dict[str, int] | None = None,
) -> dict:
    decision = date(2026, 7, 13) + timedelta(weeks=index)
    decision_date = decision.strftime("%Y%m%d")
    capture = _capture(
        decision_date,
        shadow_replacement=shadow_replacement,
        source_digest=format(index + 1, "064x"),
    )
    candidate_values = {ticker: 0.0 for ticker in CANDIDATES}
    candidate_values.update(values or {})
    return {
        "capture": capture,
        "decision_diff": decision_diff.build_forward_policy_decision_diff_log(capture)["private"],
        "scorecard_comparison": _scorecard(capture, candidate_values, fills=fills),
        "outcome_as_of": (decision + timedelta(days=4)).strftime("%Y%m%d"),
        "candidate_net_benchmark_excess": candidate_values,
        "outcome_metric": "net_benchmark_excess",
        "outcome_basis": "same_decision_week_benchmark_and_cost_model",
        "forward_evidence": {
            "recording_mode": "same_run_live_capture_only",
            "historical_replay_counts_as_forward": False,
            "backfill_allowed": False,
        },
    }


def _weeks(count: int, **kwargs) -> list[dict]:
    return [_week(index, **kwargs) for index in range(count)]


def _as_of(weeks: list[dict]) -> str:
    return weeks[-1]["outcome_as_of"] if weeks else "20260712"


class ForwardPolicyStatisticalEvaluationTests(unittest.TestCase):
    def test_zero_real_weeks_emits_no_forward_evidence(self):
        result = evaluation.evaluate_forward_policy_statistical_evaluation([], as_of="20260712")

        self.assertEqual(result["evaluated_decision_week_count"], 0)
        self.assertFalse(result["boundary"]["produces_forward_evidence"])
        self.assertTrue(all(block["verdict"] == "accumulating" for block in result["policy_verdicts"].values()))
        self.assertTrue(all(block["outcome_gate"]["evaluated"] is False for block in result["policy_verdicts"].values()))

    def test_under_minimum_is_outcome_blind_and_deidentified(self):
        weeks = _weeks(11, values={"T15": 0.03})
        result = evaluation.evaluate_forward_policy_statistical_evaluation(weeks, as_of=_as_of(weeks))
        block = result["policy_verdicts"][SHADOW]

        self.assertEqual(block["divergence_week_count"], 11)
        self.assertEqual(block["verdict"], "accumulating")
        self.assertFalse(block["outcome_gate"]["evaluated"])
        self.assertIsNone(block["outcome_gate"]["mean_paired_advantage"])
        self.assertNotIn("T15", repr(result))

    def test_promotion_requires_all_three_frozen_gates_and_is_deterministic(self):
        weeks = _weeks(12, values={"T15": 0.03})
        first = evaluation.evaluate_forward_policy_statistical_evaluation(weeks, as_of=_as_of(weeks))
        second = evaluation.evaluate_forward_policy_statistical_evaluation(weeks, as_of=_as_of(weeks))
        block = first["policy_verdicts"][SHADOW]

        self.assertEqual(first, second)
        self.assertEqual(block["verdict"], "promotion_eligible")
        self.assertTrue(block["outcome_gate"]["gate_a_mean_advantage"])
        self.assertTrue(block["outcome_gate"]["gate_b_paired_wins"])
        self.assertTrue(block["outcome_gate"]["gate_c_placebo"])
        self.assertGreater(block["outcome_gate"]["mean_paired_advantage"], block["outcome_gate"]["placebo_95th_percentile"])

    def test_each_promotion_gate_can_fail_alone(self):
        gate_a_weeks = _weeks(12, values={"T15": 0.0005})
        gate_a = evaluation.evaluate_forward_policy_statistical_evaluation(gate_a_weeks, as_of=_as_of(gate_a_weeks))["policy_verdicts"][SHADOW]
        self.assertEqual(gate_a["verdict"], "not_eligible")
        self.assertFalse(gate_a["outcome_gate"]["gate_a_mean_advantage"])
        self.assertTrue(gate_a["outcome_gate"]["gate_b_paired_wins"])
        self.assertTrue(gate_a["outcome_gate"]["gate_c_placebo"])

        gate_b_weeks = [
            _week(index, values={"T15": 0.03 if index < 7 else -0.005})
            for index in range(12)
        ]
        gate_b = evaluation.evaluate_forward_policy_statistical_evaluation(gate_b_weeks, as_of=_as_of(gate_b_weeks))["policy_verdicts"][SHADOW]
        self.assertEqual(gate_b["verdict"], "not_eligible")
        self.assertTrue(gate_b["outcome_gate"]["gate_a_mean_advantage"])
        self.assertFalse(gate_b["outcome_gate"]["gate_b_paired_wins"])
        self.assertTrue(gate_b["outcome_gate"]["gate_c_placebo"])

        gate_c_weeks = _weeks(12, values={"T15": 0.03, "T16": 0.6})
        gate_c = evaluation.evaluate_forward_policy_statistical_evaluation(gate_c_weeks, as_of=_as_of(gate_c_weeks))["policy_verdicts"][SHADOW]
        self.assertEqual(gate_c["verdict"], "not_eligible")
        self.assertTrue(gate_c["outcome_gate"]["gate_a_mean_advantage"])
        self.assertTrue(gate_c["outcome_gate"]["gate_b_paired_wins"])
        self.assertFalse(gate_c["outcome_gate"]["gate_c_placebo"])

    def test_outcome_blind_futility_and_structural_harm_flags(self):
        futility_weeks = [_week(index, shadow_replacement="T15" if index == 0 else None) for index in range(8)]
        futility = evaluation.evaluate_forward_policy_statistical_evaluation(
            futility_weeks, as_of=_as_of(futility_weeks),
        )["policy_verdicts"][SHADOW]
        self.assertEqual(futility["verdict"], "futility_flag")
        self.assertTrue(futility["review_flags"]["futility"])
        self.assertFalse(futility["outcome_gate"]["evaluated"])

        turnover_weeks = [
            _week(index, shadow_replacement=replacement)
            for index, replacement in enumerate(("T15", "T16", "T17"))
        ]
        turnover = evaluation.evaluate_forward_policy_statistical_evaluation(
            turnover_weeks, as_of=_as_of(turnover_weeks),
        )["policy_verdicts"][SHADOW]
        self.assertEqual(turnover["verdict"], "harm_flag")
        self.assertTrue(turnover["review_flags"]["harm_turnover"])
        self.assertFalse(turnover["outcome_gate"]["evaluated"])

        fill_weeks = _weeks(2, fills={SHADOW: 7})
        fill = evaluation.evaluate_forward_policy_statistical_evaluation(fill_weeks, as_of=_as_of(fill_weeks))["policy_verdicts"][SHADOW]
        self.assertEqual(fill["verdict"], "harm_flag")
        self.assertTrue(fill["review_flags"]["harm_fill"])
        self.assertFalse(fill["outcome_gate"]["evaluated"])

    def test_manifest_loader_is_the_threshold_source(self):
        weeks = _weeks(12, values={"T15": 0.03})
        altered = copy.deepcopy(evaluation.statistical_plan.load_forward_policy_statistical_plan())
        altered["statistics"]["comparison_win_margin"] = 0.04
        with mock.patch.object(
            evaluation.statistical_plan,
            "load_forward_policy_statistical_plan",
            return_value=altered,
        ):
            result = evaluation.evaluate_forward_policy_statistical_evaluation(weeks, as_of=_as_of(weeks))
        block = result["policy_verdicts"][SHADOW]

        self.assertEqual(block["verdict"], "not_eligible")
        self.assertFalse(block["outcome_gate"]["gate_a_mean_advantage"])

    def test_rejects_replay_duplicate_stale_and_lookahead_inputs(self):
        week = _week(0)
        with self.assertRaises(evaluation.ForwardPolicyStatisticalEvaluationError):
            evaluation.evaluate_forward_policy_statistical_evaluation([week, copy.deepcopy(week)], as_of=_as_of([week]))

        out_of_order = _weeks(2)
        with self.assertRaises(evaluation.ForwardPolicyStatisticalEvaluationError):
            evaluation.evaluate_forward_policy_statistical_evaluation(
                list(reversed(out_of_order)), as_of=_as_of(out_of_order),
            )

        stale = copy.deepcopy(week)
        stale["scorecard_comparison"]["as_of"] = "20260720"
        stale["scorecard_comparison"]["capture_binding"]["decision_date"] = "20260720"
        with self.assertRaises(evaluation.ForwardPolicyStatisticalEvaluationError):
            evaluation.evaluate_forward_policy_statistical_evaluation([stale], as_of="20260720")

        replay = copy.deepcopy(week)
        replay["forward_evidence"]["backfill_allowed"] = True
        with self.assertRaises(evaluation.ForwardPolicyStatisticalEvaluationError):
            evaluation.evaluate_forward_policy_statistical_evaluation([replay], as_of=_as_of([replay]))

        lookahead = copy.deepcopy(week)
        lookahead["outcome_as_of"] = "20260712"
        with self.assertRaises(evaluation.ForwardPolicyStatisticalEvaluationError):
            evaluation.evaluate_forward_policy_statistical_evaluation([lookahead], as_of="20260712")


if __name__ == "__main__":
    unittest.main()

# -*- coding: utf-8 -*-
"""Cut B: six-policy selection, paper, multi-week, and lifecycle comparison contract."""
from __future__ import annotations

import copy
from datetime import date, timedelta
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine import us_short_lifecycle_eval as lifecycle  # noqa: E402
from engine import us_short_paper_multiweek_comparison as multi_cmp  # noqa: E402
from engine import us_short_paper_multiweek_scorecard as multi_score  # noqa: E402
from engine import us_short_paper_scorecard as scorecard  # noqa: E402
from engine import us_short_paper_scorecard_comparison as score_cmp  # noqa: E402
from engine import us_short_forward_policy_decision_diff as decision_diff  # noqa: E402
from engine import us_short_shadow_compare as selection_cmp  # noqa: E402
from engine.us_short_forward_policy_heads import SELECTION_POLICY_IDS  # noqa: E402
from engine.us_short_forward_policy_statistical_plan import statistical_plan_sha256  # noqa: E402
from engine.us_short_forward_policy_effect_surface import baseline_epoch_sha256  # noqa: E402

POLICIES = tuple(SELECTION_POLICY_IDS)


def _capture(decision_date="20260713", *, source_digest="a" * 64) -> dict:
    decision = date(int(decision_date[:4]), int(decision_date[4:6]), int(decision_date[6:8]))
    price_basis_date = (decision - timedelta(days=3)).strftime("%Y%m%d")
    selections = {
        "balanced": ["AAA", "BBB"],
        "theme_plus": ["AAA", "CCC"],
        "theme_aggressive": ["CCC", "DDD"],
        "theme_off": ["AAA", "DDD"],
        "catalyst_off": ["BBB", "DDD"],
        "overextension_selection_off": ["AAA", "BBB"],
    }
    common_pool = ["AAA", "BBB", "CCC", "DDD"]
    return {
        "schema_name": "us_short_forward_policy_shadow_selection",
        "schema_version": "2.1.0",
        "decision_date": decision_date,
        "price_basis_date": price_basis_date,
        "generated_at": "2026-07-12T08:00:00-04:00",
        "source_context_sha256": source_digest,
        "comparison_contract_sha256": statistical_plan_sha256(),
        "baseline_epoch_sha256": baseline_epoch_sha256(),
        "common_selection_pool": common_pool,
        "common_selection_pool_sha256": __import__("hashlib").sha256(
            __import__("json").dumps(common_pool, separators=(",", ":")).encode("utf-8")
        ).hexdigest(),
        "selection_policies": list(POLICIES),
        "selection_decisions": {
            name: {
                "out_of_window": False,
                "decision_date": decision_date,
                "price_basis_date": price_basis_date,
                "run_date": (decision - timedelta(days=1)).strftime("%Y%m%d"),
                "cheap_eligible": list(common_pool),
                "candidates": list(common_pool),
                "recall_available": [],
                "recall_added": [],
                "recall_excluded": [],
                "exclusion_records": [],
                "admitted": tickers,
                "selection_seats": {},
                "theme_selection_mode": "industry_heat_v1_cross_industry_disabled",
                "full_analysis_leader_upgrades": [],
                "selection_details": [],
                "holdings": [],
            }
            for name, tickers in selections.items()
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


def _net_result(value: float) -> dict:
    return {
        "outcome": "filled_tp_exit" if value >= 0 else "filled_stopped",
        "realized": True,
        "gross_return": value,
        "cost_fraction": 0.0,
        "net_return": value,
        "unfilled_cash": False,
    }


def _score(value: float) -> dict:
    results = {"a": _net_result(value), "b": _net_result(-0.01)}
    return scorecard.build_paper_scorecard(results, selected_tickers=["a", "b"])


def _policy_scorecards() -> dict:
    return {name: _score(0.01 + index / 100.0) for index, name in enumerate(POLICIES)}


def _weekly_policy_comparisons() -> list[dict]:
    start = date(2026, 7, 13)
    weekly = []
    for index in range(12):
        capture = _capture(
            (start + timedelta(weeks=index)).strftime("%Y%m%d"),
            source_digest=format(index + 1, "064x"),
        )
        net_results = {
            name: {
                ticker: _net_result(0.01 + policy_index / 100.0 + index / 1000.0)
                for ticker in decision["admitted"]
            }
            for policy_index, (name, decision) in enumerate(capture["selection_decisions"].items())
        }
        weekly.append(score_cmp.build_policy_scorecard_comparison_from_capture(capture, net_results))
    return weekly


def _policy_multiweek(weekly=None) -> dict:
    weekly = weekly or _weekly_policy_comparisons()
    return {
        name: multi_score.build_multiweek_scorecard([
            {"as_of": comparison["as_of"], "scorecard": comparison["policies"][name]}
            for comparison in weekly
        ])
        for name in POLICIES
    }


class SelectionComparison(unittest.TestCase):
    def test_consumes_cut_a_capture_as_exact_six_policy_namespace(self):
        result = selection_cmp.build_policy_shadow_comparison(_capture())
        self.assertEqual(tuple(result["policies"]), POLICIES)
        self.assertEqual(result["primary_policy"], "balanced")
        self.assertEqual(
            result["vs_balanced"]["theme_plus"],
            {"balanced_only": ["BBB"], "policy_only": ["CCC"], "overlap_count": 1},
        )
        self.assertFalse(result["boundary"]["shadow_counts_ship_gate"])
        self.assertFalse(result["boundary"]["changes_primary_selection"])

    def test_missing_policy_second_wave_or_tamper_fails_closed(self):
        for mutate in (
            lambda value: value["selection_decisions"].pop("catalyst_off"),
            lambda value: value["selection_decisions"].__setitem__(
                "overextension_execution_off", value["selection_decisions"]["balanced"]
            ),
            lambda value: value["boundary"].__setitem__("shadow_counts_ship_gate", True),
            lambda value: value["selection_decisions"]["theme_plus"].__setitem__("admitted", ["AAA"]),
        ):
            bad = copy.deepcopy(_capture())
            mutate(bad)
            with self.assertRaises(selection_cmp.ShadowCompareError):
                selection_cmp.build_policy_shadow_comparison(bad)

    def test_capture_clock_identity_and_source_digest_fail_closed(self):
        for key, bad_value in (
            ("decision_date", "20260231"),
            ("price_basis_date", "20260713"),
            ("source_context_sha256", "bad"),
            ("schema_version", "1.0.0"),
        ):
            bad = _capture()
            bad[key] = bad_value
            with self.assertRaises(selection_cmp.ShadowCompareError):
                selection_cmp.build_policy_shadow_comparison(bad)
        nested_extra = _capture()
        nested_extra["selection_decisions"]["balanced"]["smuggled"] = True
        with self.assertRaises(selection_cmp.ShadowCompareError):
            selection_cmp.build_policy_shadow_comparison(nested_extra)


class DecisionDiffLog(unittest.TestCase):
    def test_builds_private_per_ticker_diff_and_deidentified_summary(self):
        result = decision_diff.build_forward_policy_decision_diff_log(_capture())
        self.assertEqual(result["private"]["schema_name"], "us_short_forward_policy_decision_diff_log")
        self.assertEqual(tuple(result["private"]["diffs_vs_balanced"]), POLICIES[1:])
        rows = {
            row["ticker"]: row
            for row in result["private"]["diffs_vs_balanced"]["theme_plus"]["ticker_diffs"]
        }
        self.assertEqual(rows["BBB"]["top15_membership_change"], "balanced_only")
        self.assertEqual(rows["BBB"]["selection_gate_pass_change"], "dropped_from_top15")
        self.assertIsNone(rows["BBB"]["policy_rank"])
        self.assertEqual(rows["CCC"]["top15_membership_change"], "policy_only")
        self.assertEqual(rows["CCC"]["selection_gate_pass_change"], "added_to_top15")
        self.assertEqual(rows["AAA"]["rank_delta"], 0)
        self.assertEqual(rows["AAA"]["action_change"], "not_available_in_cut_a_capture")
        self.assertEqual(rows["AAA"]["size_change"], "not_available_in_cut_a_capture")

        summary_text = repr(result["summary"])
        self.assertEqual(result["summary"]["schema_name"], "us_short_forward_policy_decision_diff_summary")
        self.assertEqual(result["summary"]["diff_counts_vs_balanced"]["theme_plus"]["top15_membership_changed_count"], 2)
        self.assertNotIn("AAA", summary_text)
        self.assertNotIn("BBB", summary_text)
        self.assertNotIn("CCC", summary_text)
        self.assertFalse(result["summary"]["boundary"]["shadow_counts_ship_gate"])

    def test_rejects_second_wave_boundary_and_non_selection_gate_drift(self):
        for mutate in (
            lambda value: value["selection_decisions"].__setitem__(
                "overextension_execution_off", value["selection_decisions"]["balanced"]
            ),
            lambda value: value["boundary"].__setitem__("shadow_counts_ship_gate", True),
            lambda value: value["selection_decisions"]["theme_plus"].__setitem__("candidates", ["AAA"]),
        ):
            bad = copy.deepcopy(_capture())
            mutate(bad)
            with self.assertRaises(decision_diff.ForwardPolicyDecisionDiffError):
                decision_diff.build_forward_policy_decision_diff_log(bad)

    def test_validator_rederives_counts_and_refuses_action_or_size_fabrication(self):
        result = decision_diff.build_forward_policy_decision_diff_log(_capture())
        result["private"]["diffs_vs_balanced"]["theme_plus"]["counts"]["rank_changed_count"] = 99
        with self.assertRaises(decision_diff.ForwardPolicyDecisionDiffError):
            decision_diff.validate_forward_policy_decision_diff_log(result["private"])

        fabricated = decision_diff.build_forward_policy_decision_diff_log(_capture())["private"]
        fabricated["diffs_vs_balanced"]["theme_plus"]["ticker_diffs"][0]["action_change"] = "changed"
        with self.assertRaises(decision_diff.ForwardPolicyDecisionDiffError):
            decision_diff.validate_forward_policy_decision_diff_log(fabricated)


class ScorecardComparison(unittest.TestCase):
    def test_six_policy_full_caliber_and_ship_gate_isolation(self):
        result = score_cmp.build_policy_scorecard_comparison(
            _policy_scorecards(), as_of="20260713", source_context_sha256="a" * 64,
        )
        self.assertEqual(tuple(result["policies"]), POLICIES)
        self.assertEqual(set(result["vs_balanced"]), set(POLICIES[1:]))
        self.assertIn("catalyst_off", result["vs_balanced"])
        self.assertIn("overextension_selection_off", result["vs_balanced"])
        self.assertFalse(result["boundary"]["shadow_counts_ship_gate"])
        self.assertFalse(result["boundary"]["full_size_ship_gate_allowed"])
        self.assertEqual(result["source_context_sha256"], "a" * 64)

    def test_direct_capture_consumer_builds_scorecards_from_exact_selected_tickers(self):
        capture = _capture()
        net_results = {
            name: {ticker: _net_result(0.01) for ticker in decision["admitted"]}
            for name, decision in capture["selection_decisions"].items()
        }
        result = score_cmp.build_policy_scorecard_comparison_from_capture(capture, net_results)
        self.assertEqual(result["as_of"], capture["decision_date"])
        self.assertEqual(result["source_context_sha256"], capture["source_context_sha256"])
        bad = copy.deepcopy(net_results)
        bad["catalyst_off"]["EXTRA"] = _net_result(0.01)
        with self.assertRaises(score_cmp.ScorecardComparisonError):
            score_cmp.build_policy_scorecard_comparison_from_capture(capture, bad)

    def test_doctored_policy_delta_fails_closed(self):
        result = score_cmp.build_policy_scorecard_comparison(
            _policy_scorecards(), as_of="20260713", source_context_sha256="a" * 64,
        )
        result["vs_balanced"]["catalyst_off"]["loss_count_delta"] = 99
        with self.assertRaises(score_cmp.ScorecardComparisonError):
            score_cmp.validate_policy_scorecard_comparison(result)

    def test_policy_coverage_and_source_digest_fail_closed(self):
        missing = _policy_scorecards()
        missing.pop("catalyst_off")
        with self.assertRaises(score_cmp.ScorecardComparisonError):
            score_cmp.build_policy_scorecard_comparison(
                missing, as_of="20260713", source_context_sha256="a" * 64,
            )
        with self.assertRaises(score_cmp.ScorecardComparisonError):
            score_cmp.build_policy_scorecard_comparison(
                _policy_scorecards(), as_of="20260713", source_context_sha256="bad",
            )


class MultiweekComparison(unittest.TestCase):
    def test_six_policy_twelve_week_window(self):
        weekly = _weekly_policy_comparisons()
        result = multi_cmp.build_policy_multiweek_comparison(
            _policy_multiweek(weekly), weekly_policy_comparisons=weekly,
        )
        self.assertEqual(tuple(result["policies"]), POLICIES)
        self.assertEqual(set(result["vs_balanced"]), set(POLICIES[1:]))
        self.assertFalse(result["boundary"]["shadow_counts_ship_gate"])
        self.assertEqual(list(result["source_context_sha256_by_as_of"]), [row["as_of"] for row in weekly])

    def test_one_week_or_misaligned_policy_fails_closed(self):
        one_week = multi_score.build_multiweek_scorecard([
            {"as_of": "20260713", "scorecard": _score(0.01)},
        ])
        bad = _policy_multiweek()
        bad["catalyst_off"] = one_week
        with self.assertRaises(multi_cmp.MultiweekComparisonError):
            multi_cmp.build_policy_multiweek_comparison(
                bad, weekly_policy_comparisons=_weekly_policy_comparisons(),
            )

    def test_multiweek_rejects_free_form_weekly_comparison_without_capture_binding(self):
        weekly = _weekly_policy_comparisons()
        weekly[0] = score_cmp.build_policy_scorecard_comparison(
            weekly[0]["policies"], as_of=weekly[0]["as_of"], source_context_sha256="f" * 64,
        )
        with self.assertRaises(multi_cmp.MultiweekComparisonError):
            multi_cmp.build_policy_multiweek_comparison(
                _policy_multiweek(), weekly_policy_comparisons=weekly,
            )

    def test_multiweek_validator_rederives_both_digest_maps(self):
        weekly = _weekly_policy_comparisons()
        result = multi_cmp.build_policy_multiweek_comparison(
            _policy_multiweek(weekly), weekly_policy_comparisons=weekly,
        )
        first_week = weekly[0]["as_of"]
        for field in ("source_context_sha256_by_as_of", "weekly_comparison_sha256_by_as_of"):
            bad = copy.deepcopy(result)
            bad[field][first_week] = "f" * 64
            with self.assertRaises(multi_cmp.MultiweekComparisonError):
                multi_cmp.validate_policy_multiweek_comparison(bad)
        bad_weekly = copy.deepcopy(result)
        bad_weekly["weekly_comparisons"][0]["boundary"]["shadow_counts_ship_gate"] = True
        with self.assertRaises(multi_cmp.MultiweekComparisonError):
            multi_cmp.validate_policy_multiweek_comparison(bad_weekly)


class LifecycleMapping(unittest.TestCase):
    def test_verified_single_week_comparison_maps_item_28_without_forging_item_36_trigger(self):
        capture = _capture()
        net_results = {
            name: {ticker: _net_result(0.01) for ticker in decision["admitted"]}
            for name, decision in capture["selection_decisions"].items()
        }
        comparison = score_cmp.build_policy_scorecard_comparison_from_capture(capture, net_results)
        update = lifecycle.policy_comparison_lifecycle_observation(comparison, capture=capture)
        self.assertEqual(update["decision_date"], "20260713")
        self.assertEqual(update["observations"], {28: {"forward_contribution": 1}})
        self.assertNotIn(36, update["observations"])
        self.assertNotIn("upgrade_margin_frozen", update["observations"][28])

    def test_tampered_ship_gate_boundary_cannot_enter_lifecycle(self):
        capture = _capture()
        net_results = {
            name: {ticker: _net_result(0.01) for ticker in decision["admitted"]}
            for name, decision in capture["selection_decisions"].items()
        }
        comparison = score_cmp.build_policy_scorecard_comparison_from_capture(capture, net_results)
        comparison["boundary"]["shadow_counts_ship_gate"] = True
        with self.assertRaises(lifecycle.LifecycleObservationError):
            lifecycle.policy_comparison_lifecycle_observation(comparison, capture=capture)

    def test_free_form_policy_comparison_cannot_earn_lifecycle_observation(self):
        comparison = score_cmp.build_policy_scorecard_comparison(
            _policy_scorecards(), as_of="20260713", source_context_sha256="a" * 64,
        )
        with self.assertRaises(lifecycle.LifecycleObservationError):
            lifecycle.policy_comparison_lifecycle_observation(comparison, capture=_capture())


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import ast
import copy
from datetime import date, timedelta
from decimal import Decimal
import json
from pathlib import Path
import unittest

from jsonschema import Draft7Validator

import engine.us_short_market_diagnostic as diagnostic
from engine.us_short_market_diagnostic import (
    MarketDiagnosticError,
    compound_wealth,
    construct_simple_return,
    construct_weekly_return,
    evaluate_window_trigger,
    information_ratio,
    newey_west_hac_t,
    segment_epoch_and_ruleset,
    summarize_window,
    validate_window,
    window_containing_week,
    window_for_week,
)


ROOT = Path(__file__).resolve().parents[1]
BENCHMARKS = ("VTI", "IWB", "SPY", "QQQ")
BOUNDARY = {
    "diagnostic_only": True,
    "comparison_only": True,
    "counts_ship_gate": False,
    "changes_selection_or_action": False,
    "automatic_policy_switch": False,
    "broker_or_order_automation": False,
}


def _schema(name: str) -> dict:
    return json.loads((ROOT / "schemas" / name).read_text(encoding="utf-8"))


def _money(value: Decimal) -> str:
    return f"{value:.6f}"


def _weekly_rows(
    *,
    price_only: bool = False,
    paper_false_weeks: set[int] | None = None,
    no_count_week: int | None = None,
    ruleset_cut: int | None = None,
) -> list[dict]:
    paper_false_weeks = set() if paper_false_weeks is None else set(paper_false_weeks)
    rows: list[dict] = []
    previous_nav = Decimal("100000.000000")
    decision_start = date(2026, 1, 2)
    cumulative_cost = Decimal("0.000000")
    for week in range(1, 27):
        no_count = week == no_count_week
        paper_evaluable = week not in paper_false_weeks
        factor = Decimal("1.0020") if week % 2 else Decimal("1.0028")
        current_nav = previous_nav if no_count else (previous_nav * factor).quantize(Decimal("0.000001"))
        weekly_return = None if no_count else construct_weekly_return(_money(previous_nav), _money(current_nav))
        if not no_count:
            cumulative_cost += Decimal("10.000000")
        strategy_evaluable = paper_evaluable and not no_count
        strategy_status = "evaluable" if strategy_evaluable else "diagnostic_data_degraded"
        strategy = {
            "paper_evaluable": paper_evaluable,
            "performance_status": strategy_status,
            "strategy_evaluable": strategy_evaluable,
            "initial_capital": "100000.000000",
            "prior_nav": None if week == 1 else _money(previous_nav),
            "nav": _money(current_nav),
            "weekly_return": weekly_return,
            "cumulative_return": None,
            "cash": _money((current_nav * Decimal("0.600000")).quantize(Decimal("0.000001"))),
            "market_value": _money((current_nav * Decimal("0.400000")).quantize(Decimal("0.000001"))),
            "cumulative_cost_paid": _money(cumulative_cost),
            "turnover": 0.10,
            "unfilled_order_count": 0,
            "no_count": no_count,
            "no_count_reason": "no_settled_observation" if no_count else None,
            "source_sha256": f"{week:064x}",
            "degradation_reasons": (["no_settled_observation"] if no_count else []),
        }
        benchmarks = {}
        benchmark_bases = {"VTI": 0.0005, "IWB": 0.0007, "SPY": 0.0004, "QQQ": 0.0009}
        for symbol in BENCHMARKS:
            benchmark_evaluable = True
            benchmark_return = benchmark_bases[symbol] + (0.0001 if week % 3 == 0 else 0.0)
            quality = "price_return_diagnostic" if price_only else "total_return_evaluable"
            benchmarks[symbol] = {
                "return_quality": quality,
                "benchmark_evaluable": benchmark_evaluable,
                "joint_evaluable": strategy_evaluable,
                "weekly_return": benchmark_return,
                "cumulative_return": None,
                "raw_excess": None,
                "relative_wealth": None,
                "price_date": (decision_start + timedelta(days=7 * (week - 1)) - timedelta(days=1)).strftime("%Y%m%d"),
                "price_source": "synthetic_price_packet",
                "price_packet_sha256": f"{(100 + week):064x}",
                "dividend_sidecar_sha256": None if price_only else f"{(200 + week):064x}",
                "data_quality_reasons": ["dividend_sidecar_not_complete"] if price_only else [],
            }
        decision = decision_start + timedelta(days=7 * (week - 1))
        evaluable_count = sum(
            int(previous["strategy"]["strategy_evaluable"]) for previous in rows
        ) + int(strategy_evaluable)
        ruleset = "a" * 64 if ruleset_cut is None or week <= ruleset_cut else "b" * 64
        rows.append(
            {
                "schema_name": "us_short_market_diagnostic_weekly_record",
                "schema_version": "1.0.0",
                "decision_date": decision.strftime("%Y%m%d"),
                "valuation_date": (decision - timedelta(days=1)).strftime("%Y%m%d"),
                "calendar_week_index": week,
                "window_id": "26w-1-26",
                "diagnostic_epoch": "us_short_market_diagnostic_26w_v1",
                "diagnostic_policy_sha256": "b" * 64,
                "strategy_ruleset_fingerprint": ruleset,
                "strategy": strategy,
                "benchmarks": benchmarks,
                "v1_1_reminder": {
                    "status": "pending" if evaluable_count < 4 else "ready_for_v1_1_implementation",
                    "evaluable_week_count": evaluable_count,
                    "text": "v1.1 reminder is pending." if evaluable_count < 4 else "v1.1 is ready for implementation.",
                },
                "source_refs": [f"{(300 + week):064x}"],
                "boundary": dict(BOUNDARY),
            }
        )
        previous_nav = current_nav
    return rows


def _assert_schema_valid(test: unittest.TestCase, name: str, payload: dict) -> None:
    errors = sorted(Draft7Validator(_schema(name)).iter_errors(payload), key=lambda error: error.path)
    test.assertEqual([], errors)


class UsShortMarketDiagnosticEngineTest(unittest.TestCase):
    def test_return_construction_and_no_implicit_zero_fill(self) -> None:
        self.assertAlmostEqual(construct_simple_return(100, 110), 0.1)
        self.assertAlmostEqual(construct_weekly_return(None, "101000.000000"), 0.01)
        self.assertAlmostEqual(compound_wealth([0.1, -0.1]), 0.99)
        with self.assertRaises(MarketDiagnosticError):
            construct_simple_return(None, 100)
        with self.assertRaises(MarketDiagnosticError):
            compound_wealth([0.1, None])

    def test_hac_is_recomputed_with_fixed_newey_west_lag(self) -> None:
        values = [0.010, 0.020, 0.000, 0.015, -0.005, 0.012]
        mean = sum(values) / len(values)
        centered = [value - mean for value in values]
        lag = min(4, len(values) - 1)
        long_run = sum(value * value for value in centered) / len(values)
        for offset in range(1, lag + 1):
            covariance = sum(
                centered[index] * centered[index - offset] for index in range(offset, len(values))
            ) / len(values)
            long_run += 2 * (1 - offset / (lag + 1)) * covariance
        expected = mean / (long_run / len(values)) ** 0.5
        self.assertAlmostEqual(newey_west_hac_t(values), expected)
        self.assertGreater(information_ratio(values), 0)

    def test_26_week_summary_calculates_metrics_and_validates_schema(self) -> None:
        rows = _weekly_rows()
        summary = summarize_window(rows)
        self.assertEqual(summary["window_id"], "26w-1-26")
        self.assertEqual(summary["calendar_weeks"], 26)
        self.assertEqual(summary["overall_status"], "ahead_diagnostic")
        self.assertEqual(summary["strategy"]["status"], "evaluable")
        self.assertEqual(summary["strategy"]["strategy_evaluable_weeks"], 26)
        self.assertAlmostEqual(summary["strategy"]["turnover"], 2.6)
        self.assertEqual(summary["strategy"]["unfilled_order_count"], 0)
        self.assertIsNotNone(summary["benchmarks"]["VTI"]["information_ratio"])
        self.assertIsNotNone(summary["benchmarks"]["VTI"]["hac_t"])
        strategy_cumulative = summary["strategy"]["cumulative_return"]
        benchmark_cumulative = summary["benchmarks"]["VTI"]["cumulative_return"]
        expected_relative = (1 + strategy_cumulative) / (1 + benchmark_cumulative) - 1
        self.assertAlmostEqual(summary["benchmarks"]["VTI"]["relative_wealth"], expected_relative)
        self.assertAlmostEqual(
            summary["benchmarks"]["VTI"]["raw_excess"],
            (1 + strategy_cumulative) - (1 + benchmark_cumulative),
        )
        _assert_schema_valid(self, "us_short_market_diagnostic_summary.schema.json", summary)
        for row in rows:
            _assert_schema_valid(self, "us_short_market_diagnostic_weekly_record.schema.json", row)

    def test_price_only_data_is_degraded_and_not_relabelled_total_return(self) -> None:
        summary = summarize_window(_weekly_rows(price_only=True))
        self.assertEqual(summary["overall_status"], "data_degraded")
        for symbol in BENCHMARKS:
            benchmark = summary["benchmarks"][symbol]
            self.assertEqual(benchmark["status"], "data_degraded")
            self.assertEqual(benchmark["total_return_evaluable_weeks"], 0)
            self.assertEqual(benchmark["price_only_weeks"], 26)
            self.assertIsNotNone(benchmark["cumulative_return"])

    def test_less_than_20_joint_weeks_cannot_claim_direction(self) -> None:
        rows = _weekly_rows(paper_false_weeks=set(range(1, 8)))
        summary = summarize_window(rows)
        self.assertEqual(summary["overall_status"], "data_insufficient")
        self.assertEqual(summary["strategy"]["status"], "diagnostic_data_degraded")
        self.assertEqual(summary["strategy"]["paper_degraded_weeks"], 7)
        for symbol in BENCHMARKS:
            self.assertEqual(summary["benchmarks"][symbol]["joint_evaluable_weeks"], 19)
            self.assertEqual(summary["benchmarks"][symbol]["status"], "data_insufficient")
            self.assertNotIn(summary["benchmarks"][symbol]["status"], {"ahead_diagnostic", "behind_diagnostic"})

    def test_no_count_remains_in_denominator_and_missing_return_stays_null(self) -> None:
        rows = _weekly_rows(no_count_week=5)
        summary = summarize_window(rows)
        self.assertEqual(summary["calendar_weeks"], 26)
        self.assertEqual(summary["strategy"]["no_count_weeks"], 1)
        self.assertEqual(summary["strategy"]["strategy_evaluable_weeks"], 25)
        self.assertAlmostEqual(summary["strategy"]["data_coverage"], 25 / 26)
        self.assertIsNone(summary["strategy"]["cumulative_return"])
        self.assertEqual(summary["overall_status"], "ahead_diagnostic")
        _assert_schema_valid(self, "us_short_market_diagnostic_summary.schema.json", summary)

        without_execution_metrics = _weekly_rows()
        for row in without_execution_metrics:
            row["strategy"].pop("turnover")
            row["strategy"].pop("unfilled_order_count")
        summary_without_execution_metrics = summarize_window(without_execution_metrics)
        self.assertIsNone(summary_without_execution_metrics["strategy"]["turnover"])
        self.assertIsNone(summary_without_execution_metrics["strategy"]["unfilled_order_count"])
        _assert_schema_valid(self, "us_short_market_diagnostic_summary.schema.json", summary_without_execution_metrics)

        bad = _weekly_rows(no_count_week=5)
        bad[4]["strategy"]["weekly_return"] = 0.0
        with self.assertRaises(MarketDiagnosticError):
            summarize_window(bad)

    def test_ruleset_segments_epoch_gate_and_mixed_window_flag(self) -> None:
        rows = _weekly_rows(ruleset_cut=10)
        segments = segment_epoch_and_ruleset(rows)
        self.assertEqual(len(segments), 2)
        self.assertEqual([segment["calendar_weeks"] for segment in segments], [10, 16])
        summary = summarize_window(rows)
        self.assertTrue(summary["mixed_ruleset_window"])
        self.assertEqual(summary["ruleset_fingerprints"], ["a" * 64, "b" * 64])

        mixed_epoch = copy.deepcopy(rows)
        mixed_epoch[12]["diagnostic_epoch"] = "us_short_market_diagnostic_26w_v2"
        self.assertEqual(
            {segment["diagnostic_epoch"] for segment in segment_epoch_and_ruleset(mixed_epoch)},
            {"us_short_market_diagnostic_26w_v1", "us_short_market_diagnostic_26w_v2"},
        )
        with self.assertRaises(MarketDiagnosticError):
            summarize_window(mixed_epoch)

    def test_window_boundaries_are_non_overlapping_and_idempotent(self) -> None:
        self.assertFalse(evaluate_window_trigger(25)["trigger"])
        first = evaluate_window_trigger(26)
        self.assertTrue(first["trigger"])
        self.assertEqual(first["window"]["window_id"], "26w-1-26")
        rerun = evaluate_window_trigger(26, emitted_window_ids=["26w-1-26"])
        self.assertFalse(rerun["trigger"])
        self.assertTrue(rerun["already_emitted"])
        second = evaluate_window_trigger(52, emitted_window_ids=["26w-1-26"])
        self.assertTrue(second["trigger"])
        self.assertEqual(second["window"]["window_id"], "26w-27-52")
        self.assertEqual(second["window"]["window_start_week"], 27)
        self.assertEqual(second["window"]["window_end_week"], 52)

    def test_window_containing_week_is_the_single_boundary_source(self) -> None:
        original = diagnostic.WINDOW_WEEKS
        try:
            diagnostic.WINDOW_WEEKS = 13
            containing = window_containing_week(26)
            self.assertEqual(
                {
                    "window_id": "26w-14-26",
                    "window_start_week": 14,
                    "window_end_week": 26,
                    "calendar_weeks": 13,
                },
                containing,
            )
            self.assertEqual(containing, window_for_week(26))
            self.assertIsNone(window_for_week(25))
        finally:
            diagnostic.WINDOW_WEEKS = original

    def test_wrong_clock_date_and_future_inputs_fail_closed(self) -> None:
        bad_clock = _weekly_rows()
        bad_clock[0]["window_id"] = "26w-2-27"
        with self.assertRaises(MarketDiagnosticError):
            validate_window(bad_clock)

        bad_date = _weekly_rows()
        bad_date[3]["decision_date"] = "20260230"
        with self.assertRaises(MarketDiagnosticError):
            validate_window(bad_date)

        with self.assertRaises(MarketDiagnosticError):
            validate_window(_weekly_rows(), as_of_date="20260101")

    def test_noncanonical_window_anchor_fails_on_the_compute_path(self) -> None:
        shifted = _weekly_rows()
        for row in shifted:
            row["calendar_week_index"] += 4
            row["window_id"] = "26w-5-30"
        with self.assertRaises(MarketDiagnosticError):
            validate_window(shifted)
        with self.assertRaises(MarketDiagnosticError):
            summarize_window(shifted)

    def test_second_canonical_window_is_accepted_on_the_compute_path(self) -> None:
        second_window = _weekly_rows()
        for row in second_window:
            row["calendar_week_index"] += 26
            row["window_id"] = "26w-27-52"
        identity = validate_window(second_window)
        self.assertEqual(identity["window_id"], "26w-27-52")
        self.assertEqual(summarize_window(second_window)["window_end_week"], 52)

    def test_reverse_direction_is_not_hardcoded_to_ahead(self) -> None:
        rows = _weekly_rows()
        for row in rows:
            for symbol in BENCHMARKS:
                row["benchmarks"][symbol]["weekly_return"] = 0.01
        summary = summarize_window(rows)
        self.assertEqual(summary["overall_status"], "behind_diagnostic")
        self.assertLess(summary["benchmarks"]["VTI"]["raw_excess"], 0)

    def test_single_benchmark_exact_tie_uses_flat_status_not_cross_benchmark_mixed(self) -> None:
        rows = _weekly_rows()
        for row in rows:
            row["benchmarks"]["VTI"]["weekly_return"] = row["strategy"]["weekly_return"]
        summary = summarize_window(rows)
        self.assertEqual(summary["benchmarks"]["VTI"]["status"], "flat_diagnostic")
        self.assertAlmostEqual(summary["benchmarks"]["VTI"]["raw_excess"], 0.0)
        self.assertAlmostEqual(summary["benchmarks"]["VTI"]["relative_wealth"], 0.0)
        self.assertNotEqual(summary["benchmarks"]["VTI"]["status"], "mixed_across_benchmarks")
        _assert_schema_valid(self, "us_short_market_diagnostic_summary.schema.json", summary)

    def test_all_four_flat_benchmarks_use_an_explicit_overall_reason(self) -> None:
        rows = _weekly_rows()
        for row in rows:
            for symbol in BENCHMARKS:
                row["benchmarks"][symbol]["weekly_return"] = row["strategy"]["weekly_return"]
        summary = summarize_window(rows)
        self.assertEqual(summary["overall_status"], "mixed_across_benchmarks")
        self.assertEqual(summary["status_reason"], "all_four_benchmarks_show_flat_diagnostic_excess")
        for symbol in BENCHMARKS:
            self.assertEqual(summary["benchmarks"][symbol]["status"], "flat_diagnostic")
        _assert_schema_valid(self, "us_short_market_diagnostic_summary.schema.json", summary)

    def test_unavailable_benchmark_wins_status_priority_without_zero_fill(self) -> None:
        rows = _weekly_rows()
        for row in rows:
            benchmark = row["benchmarks"]["VTI"]
            benchmark["return_quality"] = "unavailable"
            benchmark["benchmark_evaluable"] = False
            benchmark["joint_evaluable"] = False
            benchmark["weekly_return"] = None
            benchmark["data_quality_reasons"] = ["price_packet_missing"]
        summary = summarize_window(rows)
        self.assertEqual(summary["overall_status"], "unavailable")
        self.assertEqual(summary["benchmarks"]["VTI"]["status"], "unavailable")
        self.assertIsNone(summary["benchmarks"]["VTI"]["cumulative_return"])
        self.assertEqual(summary["benchmarks"]["VTI"]["unavailable_weeks"], 26)

    def test_module_has_no_external_or_io_imports(self) -> None:
        source = (ROOT / "engine" / "us_short_market_diagnostic.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        imports = [node for node in ast.walk(tree) if isinstance(node, (ast.Import, ast.ImportFrom))]
        external = []
        for node in imports:
            if isinstance(node, ast.Import):
                names = [alias.name.split(".")[0] for alias in node.names]
            else:
                names = [node.module.split(".")[0]] if node.module else []
            for name in names:
                if name not in {"__future__", "collections", "datetime", "decimal", "math", "re", "typing"}:
                    external.append(name)
        self.assertEqual([], external)
        self.assertNotIn("open(", source)
        self.assertNotIn("requests", source)
        self.assertNotIn("urllib", source)


if __name__ == "__main__":
    unittest.main()

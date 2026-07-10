from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine import us_short_yfinance_analyst_grades as g  # noqa: E402
from engine.us_short_analyst_grade_risk import project_analyst_grade_risk_downgrade  # noqa: E402
from engine.us_short_risk_downgrade import ANALYST_DOWNGRADE_PENALTY  # noqa: E402


AS_OF = "2026-07-10"
PREOPEN = "2026-07-10T08:00:00-04:00"


def prov(*, coverage="full", parser="ok", source_as_of=AS_OF, observed_at=PREOPEN, rid="aapl"):
    return {
        "provider_id": "yfinance",
        "endpoint_or_filing_type": "upgrades_downgrades",
        "source_as_of": source_as_of,
        "observed_at": observed_at,
        "coverage_status": coverage,
        "parser_status": parser,
        "lineage_ref": f"yfinance:upgrades_downgrades:{source_as_of}#{rid}",
    }


def row(*, ticker="AAPL", date="2026-07-01", action="up", firm="BankA", to_grade="Buy", from_grade="Hold"):
    return {
        "symbol": ticker,
        "GradeDate": date,
        "Action": action,
        "Firm": firm,
        "ToGrade": to_grade,
        "FromGrade": from_grade,
    }


def source(records, **provenance_kwargs):
    return {"records": list(records), "provenance": prov(**provenance_kwargs)}


class YFinanceGradesResolverTest(unittest.TestCase):
    def test_direction_from_yfinance_action_and_same_output_shape(self):
        out = g.resolve_yfinance_grade_actions(
            as_of=AS_OF,
            grades_by_ticker={
                "AAPL": source([
                    row(action="up", firm="A"),
                    row(action="down", firm="B", date="2026-07-02"),
                    row(action="init", firm="C", date="2026-07-03"),
                    row(action="main", firm="D", date="2026-07-04"),
                    row(action="reit", firm="E", date="2026-07-05"),
                ])
            },
        )

        summary = out["signals"]["AAPL"]["analyst_actions_recent"]
        self.assertEqual(set(out), {"signals", "records", "provenance", "excluded", "checked"})
        self.assertEqual((summary["upgrades"], summary["downgrades"], summary["neutrals"]), (1, 1, 3))
        self.assertEqual(summary["net"], 0)
        self.assertEqual(summary["distinct_downgrading_firms"], 1)
        self.assertEqual({item["direction"] for item in out["records"]["AAPL"]}, {"up", "down", "neutral"})

    def test_collective_downgrade_shape_feeds_existing_risk_consumer(self):
        actions = g.resolve_yfinance_grade_actions(
            as_of=AS_OF,
            grades_by_ticker={
                "AAPL": source([
                    row(action="down", firm="BankA", to_grade="Sell"),
                    row(action="down", firm="BankB", date="2026-07-02", to_grade="Underperform"),
                ])
            },
        )
        projected = project_analyst_grade_risk_downgrade(
            target_tickers=["AAPL"],
            analyst_grade_actions=actions,
        )

        self.assertEqual(projected["risk_downgrade_by_ticker"]["AAPL"]["points"], ANALYST_DOWNGRADE_PENALTY)
        self.assertTrue(projected["analyst_collective_downgrade_by_ticker"]["AAPL"])

    def test_non_down_or_single_firm_does_not_create_collective_downgrade(self):
        actions = g.resolve_yfinance_grade_actions(
            as_of=AS_OF,
            grades_by_ticker={
                "AAPL": source([
                    row(action="down", firm="BankA", to_grade="Sell"),
                    row(action="main", firm="BankB", date="2026-07-02"),
                ])
            },
        )
        projected = project_analyst_grade_risk_downgrade(
            target_tickers=["AAPL"],
            analyst_grade_actions=actions,
        )
        self.assertEqual(projected["risk_downgrade_by_ticker"]["AAPL"]["points"], 0.0)

    def test_future_and_stale_rows_are_excluded_or_counted_without_lookahead(self):
        actions = g.resolve_yfinance_grade_actions(
            as_of=AS_OF,
            grades_by_ticker={
                "AAPL": source([
                    row(date="2026-07-01"),
                    row(date="2026-07-11", firm="Future"),
                    row(date="2026-01-01", firm="Stale"),
                ])
            },
        )
        self.assertEqual(len(actions["records"]["AAPL"]), 1)
        self.assertEqual(actions["provenance"]["AAPL"]["future_excluded_count"], 1)
        self.assertEqual(actions["provenance"]["AAPL"]["out_of_window_count"], 1)

    def test_zero_in_window_records_emit_checked_coverage(self):
        actions = g.resolve_yfinance_grade_actions(
            as_of=AS_OF,
            grades_by_ticker={"AAPL": source([row(date="2026-01-01")])},
        )
        self.assertEqual(actions["signals"], {})
        self.assertEqual(actions["checked"]["AAPL"]["disposition"], "checked_no_recent_activity")

    def test_missing_or_failed_source_is_excluded_neutral_not_scored(self):
        actions = g.resolve_yfinance_grade_actions(
            as_of=AS_OF,
            grades_by_ticker={"AAPL": source([], coverage="missing", parser="failed")},
        )
        projected = project_analyst_grade_risk_downgrade(
            target_tickers=["AAPL", "MSFT"],
            analyst_grade_actions=actions,
        )
        self.assertEqual(projected["risk_downgrade_by_ticker"]["AAPL"]["points"], 0.0)
        self.assertEqual(projected["risk_downgrade_by_ticker"]["MSFT"]["points"], 0.0)
        self.assertIn("AAPL", actions["excluded"])

    def test_composite_duplicate_fails_closed_after_firm_casefold(self):
        with self.assertRaises(g.YFinanceGradesError):
            g.resolve_yfinance_grade_actions(
                as_of=AS_OF,
                grades_by_ticker={
                    "AAPL": source([
                        row(firm=" BankA "),
                        row(firm="banka"),
                    ])
                },
            )

    def test_malformed_values_raise_typed_error_not_bare_typeerror(self):
        for bad_action in (["up"], {"action": "up"}, True):
            with self.subTest(bad_action=bad_action):
                with self.assertRaises(g.YFinanceGradesError):
                    g.resolve_yfinance_grade_actions(
                        as_of=AS_OF,
                        grades_by_ticker={"AAPL": source([row(action=bad_action)])},
                    )
        for bad_coverage in (["full"], {"x": "full"}, True):
            with self.subTest(bad_coverage=bad_coverage):
                with self.assertRaises(g.YFinanceGradesError):
                    g.resolve_yfinance_grade_actions(
                        as_of=AS_OF,
                        grades_by_ticker={"AAPL": source([], coverage=bad_coverage)},
                    )

    def test_bad_dates_and_symbol_mismatch_fail_closed(self):
        for bad_date in ("2026-13-01", "20260701", 20260701):
            with self.subTest(bad_date=bad_date):
                with self.assertRaises(g.YFinanceGradesError):
                    g.resolve_yfinance_grade_actions(
                        as_of=AS_OF,
                        grades_by_ticker={"AAPL": source([row(date=bad_date)])},
                    )
        with self.assertRaises(g.YFinanceGradesError):
            g.resolve_yfinance_grade_actions(
                as_of=AS_OF,
                grades_by_ticker={"AAPL": source([row(ticker="MSFT")])},
            )

    def test_observed_at_half_open_boundary_and_boundary_year_fail_closed(self):
        for observed_at in ("2026-07-10T09:30:00-04:00", "9999-12-31T23:59:59-14:00"):
            with self.subTest(observed_at=observed_at):
                with self.assertRaises(g.YFinanceGradesError):
                    g.resolve_yfinance_grade_actions(
                        as_of=AS_OF,
                        grades_by_ticker={"AAPL": source([row()], observed_at=observed_at)},
                    )

    def test_ticker_alias_collision_raises(self):
        with self.assertRaises(g.YFinanceGradesError):
            g.resolve_yfinance_grade_actions(
                as_of=AS_OF,
                grades_by_ticker={
                    "AAPL": source([row()]),
                    "aapl": source([row(ticker="aapl")], rid="aapl2"),
                },
            )


class YFinanceGradesBindingConstTest(unittest.TestCase):
    def test_module_consts_equal_binding(self):
        binding = g.load_binding()
        self.assertEqual(binding["provider_id"], g.PROVIDER_ID)
        self.assertEqual(binding["endpoint_or_filing_type"], g.ENDPOINT)
        self.assertEqual(binding["decision_timezone"], g._DECISION_TZ_NAME)
        self.assertEqual(binding["recency_window_days"], g._RECENCY_WINDOW_DAYS)
        self.assertEqual(tuple(binding["record_fields_required"]), g._RECORD_REQUIRED)
        self.assertEqual(set(binding["provenance_fields"]), g._PROVENANCE_FIELDS)
        direction = dict(binding["direction_map"])
        self.assertEqual(direction.pop("_default"), g._DIRECTION_DEFAULT)
        self.assertEqual(direction, g._DIRECTION_MAP)
        self.assertEqual(tuple(binding["summary_contract"]["fields"]), g._SUMMARY_FIELDS)
        self.assertEqual(tuple(binding["duplicate_policy"]["source_row_identity"]), g._DUPLICATE_IDENTITY)
        self.assertEqual(binding["authorization_boundary"], g._AUTHORIZATION_BOUNDARY)


if __name__ == "__main__":
    unittest.main()

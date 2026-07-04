import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.us_short_analyst_grade_risk import (  # noqa: E402
    COVERAGE_EXCLUDED,
    COVERAGE_MISSING,
    COVERAGE_NEUTRAL_CHECKED,
    COVERAGE_SCORED,
    project_analyst_grade_risk_downgrade,
)
from engine.us_short_fmp_analyst_grades import resolve_analyst_grade_actions  # noqa: E402
from engine.us_short_risk_downgrade import ANALYST_DOWNGRADE_PENALTY  # noqa: E402
from engine.us_short_seam_score import compose_score_inputs  # noqa: E402


AS_OF = "2026-06-30"


def _result(*, signals=None, checked=None, excluded=None):
    return {
        "signals": signals or {},
        "records": {},
        "provenance": {},
        "checked": checked or {},
        "excluded": excluded or {},
    }


def _signal(
    *,
    upgrades=0,
    downgrades=0,
    neutrals=0,
    distinct_firms=2,
    distinct_downgrading_firms=None,
    net=None,
):
    if distinct_downgrading_firms is None:
        distinct_downgrading_firms = min(distinct_firms, downgrades)
    return {
        "analyst_actions_recent": {
            "upgrades": upgrades,
            "downgrades": downgrades,
            "neutrals": neutrals,
            "net": upgrades - downgrades if net is None else net,
            "distinct_firms": distinct_firms,
            "distinct_downgrading_firms": distinct_downgrading_firms,
            "window_days": 90,
        }
    }


def _grade(*, date="2026-06-01", action="downgrade", company="BankA", new="Sell", prev="Hold"):
    return {
        "symbol": "AAPL",
        "date": date,
        "gradingCompany": company,
        "newGrade": new,
        "previousGrade": prev,
        "action": action,
    }


def _prov():
    return {
        "provider_id": "fmp",
        "endpoint_or_filing_type": "grades",
        "source_as_of": AS_OF,
        "observed_at": "2026-06-30T08:00:00-04:00",
        "coverage_status": "full",
        "parser_status": "ok",
        "lineage_ref": f"fmp:grades:{AS_OF}#aapl1",
    }


def _source(records):
    return {"records": records, "provenance": _prov()}


def _block_projection(key, score):
    return {
        key: {"AAPL": score},
        "neutral_fill_tickers": [],
        "coverage": {"AAPL": "scored"},
        "target_count": 1,
        "scored_count": 1,
    }


class AnalystGradeRiskProjectionTest(unittest.TestCase):
    def test_collective_downgrade_maps_to_soft_analyst_penalty_only(self):
        projection = project_analyst_grade_risk_downgrade(
            target_tickers=["AAPL"],
            analyst_grade_actions=_result(
                signals={"AAPL": _signal(upgrades=0, downgrades=2, distinct_firms=2)}
            ),
        )

        risk = projection["risk_downgrade_by_ticker"]["AAPL"]
        self.assertEqual(risk["components"], {
            "history": 0.0,
            "current_event": 0.0,
            "analyst": ANALYST_DOWNGRADE_PENALTY,
        })
        self.assertEqual(risk["points"], ANALYST_DOWNGRADE_PENALTY)
        self.assertFalse(risk["hard_veto"])
        self.assertEqual(projection["coverage_by_ticker"]["AAPL"], COVERAGE_SCORED)
        self.assertTrue(projection["analyst_collective_downgrade_by_ticker"]["AAPL"])

    def test_single_firm_or_nonnegative_net_is_not_collective_downgrade(self):
        projection = project_analyst_grade_risk_downgrade(
            target_tickers=["AAPL", "MSFT"],
            analyst_grade_actions=_result(signals={
                "AAPL": _signal(upgrades=0, downgrades=2, distinct_firms=1),
                "MSFT": _signal(upgrades=2, downgrades=2, distinct_firms=3),
            }),
        )

        self.assertEqual(projection["risk_downgrade_by_ticker"]["AAPL"]["points"], 0.0)
        self.assertEqual(projection["risk_downgrade_by_ticker"]["MSFT"]["points"], 0.0)
        self.assertFalse(projection["analyst_collective_downgrade_by_ticker"]["AAPL"])
        self.assertFalse(projection["analyst_collective_downgrade_by_ticker"]["MSFT"])

    def test_neutral_second_firm_does_not_make_single_firm_downgrade_collective(self):
        projection = project_analyst_grade_risk_downgrade(
            target_tickers=["AAPL"],
            analyst_grade_actions=_result(signals={
                "AAPL": _signal(
                    upgrades=0,
                    downgrades=2,
                    neutrals=1,
                    distinct_firms=2,
                    distinct_downgrading_firms=1,
                )
            }),
        )

        self.assertEqual(projection["risk_downgrade_by_ticker"]["AAPL"]["points"], 0.0)
        self.assertFalse(projection["analyst_collective_downgrade_by_ticker"]["AAPL"])

    def test_checked_excluded_and_missing_are_distinct_coverage_states(self):
        projection = project_analyst_grade_risk_downgrade(
            target_tickers=["AAPL", "MSFT", "JPM"],
            analyst_grade_actions=_result(
                checked={"AAPL": {"disposition": "checked_no_recent_activity"}},
                excluded={"MSFT": "coverage=partial/parser=ok"},
            ),
        )

        self.assertEqual(projection["risk_downgrade_by_ticker"]["AAPL"]["points"], 0.0)
        self.assertEqual(projection["risk_downgrade_by_ticker"]["MSFT"]["points"], 0.0)
        self.assertEqual(projection["risk_downgrade_by_ticker"]["JPM"]["points"], 0.0)
        self.assertEqual(projection["coverage_by_ticker"], {
            "AAPL": COVERAGE_NEUTRAL_CHECKED,
            "MSFT": COVERAGE_EXCLUDED,
            "JPM": COVERAGE_MISSING,
        })

    def test_malformed_signal_fails_closed_not_neutralized(self):
        with self.assertRaises(ValueError):
            project_analyst_grade_risk_downgrade(
                target_tickers=["AAPL"],
                analyst_grade_actions=_result(
                    signals={"AAPL": {"analyst_actions_recent": {"downgrades": "2"}}}
                ),
            )

    def test_real_fmp_grade_source_feeds_score_composer_soft_penalty(self):
        analyst_grade_actions = resolve_analyst_grade_actions(
            as_of=AS_OF,
            grades_by_ticker={
                "AAPL": _source([
                    _grade(company="BankA", new="Sell"),
                    _grade(date="2026-06-02", company="BankB", new="Underperform"),
                ])
            },
        )
        projection = project_analyst_grade_risk_downgrade(
            target_tickers=["AAPL"],
            analyst_grade_actions=analyst_grade_actions,
        )

        composed = compose_score_inputs(
            target_tickers=["AAPL"],
            momentum_projection=_block_projection("momentum_by_ticker", 50.0),
            theme_projection={
                **_block_projection("theme_block_by_ticker", 50.0),
                "coverage": {"AAPL": "scored_theme_base"},
            },
            catalyst_projection={
                **_block_projection("catalyst_block_by_ticker", 50.0),
                "coverage": {"AAPL": "scored_realized_catalyst"},
            },
            risk_downgrade_by_ticker=projection["risk_downgrade_by_ticker"],
            theme_opportunity_state="strong",
        )

        self.assertEqual(
            composed["analysis_by_ticker"]["AAPL"]["risk_downgrade"]["components"]["analyst"],
            ANALYST_DOWNGRADE_PENALTY,
        )
        self.assertAlmostEqual(composed["selection_inputs"]["per_ticker"]["AAPL"]["core_score"], 42.0)


if __name__ == "__main__":
    unittest.main()

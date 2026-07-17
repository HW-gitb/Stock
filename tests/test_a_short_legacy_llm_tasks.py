"""Offline regression tests for the A-short six-task legacy closure."""
from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.a_short_effect_contract import build_effect_contract_ledger  # noqa: E402
from engine.a_short_industry_theme import classify_industry_trend  # noqa: E402
from engine.a_short_legacy_llm_tasks import (  # noqa: E402
    TASK_TYPES, build_earnings_bad_reaction_result, build_task_configs, build_task_results,
)
from engine.egs_industry_heat import load_governance  # noqa: E402
from runners.a_short_weekly_pipeline import (  # noqa: E402
    _attach_llm_task_results, _validate_legacy_task_closure, build_weekly_report,
    normalize_candidate, validate_weekly_report,
)
from runners.run_analysis_report import (  # noqa: E402
    apply_enrichment, build_legacy_task_enrichment, build_report, validate_enrichment, validate_report,
)
from tests.support.analysis_input_payload import load_minimal_analysis_input_payload  # noqa: E402
from tests.test_a_short_weekly_pipeline import (  # noqa: E402
    AS_OF, GEN, _egs_candidate, _feed, _overlay_row, _series,
)


def _prices(closes: list[float]) -> list[dict]:
    dates = ["20260601", "20260602", "20260603", "20260604", "20260605", "20260606"]
    return [{"trade_date": date, "close": close, "vol": 100.0 + index}
            for index, (date, close) in enumerate(zip(dates, closes))]


def _earnings_evidence() -> dict:
    return {
        "provider_status": "ready",
        "announcement_date": "20260601",
        "report_period": "20260331",
        "financial_outcome": True,
        "stock_prices": _prices([100, 95, 94, 90, 90, 90]),
        "csi1000_prices": _prices([100, 99, 99, 98, 98, 98]),
        "industry_prices": [],
    }


class LegacyTaskConfigAndPITTests(unittest.TestCase):
    def test_configs_are_exactly_six_and_candidate_date_bound(self) -> None:
        candidate = {"ts_code": "600000.SH", "name": "fixture", "industry": {}, "scores": {}}
        configs = build_task_configs(candidate, "20260606")
        self.assertEqual([item["task_type"] for item in configs], list(TASK_TYPES))
        self.assertEqual([item["task_id"] for item in configs],
                         [f"600000.SH_{task_type}" for task_type in TASK_TYPES])
        self.assertTrue(all(item["inputs"]["as_of"] == "20260606" for item in configs))

    def test_earnings_future_rows_are_excluded_and_negative_result_is_advisory(self) -> None:
        candidate = {"ts_code": "600000.SH"}
        evidence = _earnings_evidence()
        evidence["stock_prices"].append({"trade_date": "20260607", "close": 1.0, "vol": 1.0})
        evidence["csi1000_prices"].append({"trade_date": "20260607", "close": 1000.0, "vol": 1.0})
        result = build_earnings_bad_reaction_result(candidate, "20260606", evidence)
        self.assertEqual((result["status"], result["result_code"], result["effect"]),
                         ("completed", "negative_manual_review", "manual_review"))
        self.assertAlmostEqual(result["facts"]["post_3d_return"], -0.10)


class LegacyTaskPhase4Tests(unittest.TestCase):
    def test_six_results_make_a_schema_valid_deterministic_phase4_enrichment(self) -> None:
        payload = load_minimal_analysis_input_payload()
        candidate = copy.deepcopy(payload["candidates"][0])
        candidate["llm_tasks"] = build_task_configs(candidate, payload["trade_date"])
        results = build_task_results(candidate, payload["trade_date"], official_structured={
            "status": "checked", "had_pit_announcements": False, "events": [],
        }, earnings_evidence={"provider_status": "failed"})

        report = build_report(payload, candidate, generated_at="2026-05-25T00:00:00+08:00")
        enrichment = build_legacy_task_enrichment(report, results)
        validate_enrichment(enrichment)
        merged = apply_enrichment(report, enrichment)
        validate_report(merged)
        self.assertEqual(len(merged["llm_notes"]["sections"]), len(TASK_TYPES))
        self.assertEqual(merged["data_lineage"]["enrichment_source"]["kind"], "deterministic")


class LegacyTaskWeeklyClosureTests(unittest.TestCase):
    def test_headwind_is_already_single_star_down_and_all_six_results_close(self) -> None:
        signal = classify_industry_trend(
            score=20.0, sw_l2_code="801080", sw_l2_name="fixture-industry",
            source_as_of=AS_OF, expected_as_of=AS_OF, governance=load_governance(),
        )
        candidate = _egs_candidate(
            _weekly_as_of=AS_OF,
            scores={"esp_score": 60, "l4_score": 70, "industry_heat_score": 20.0},
            industry={
                "sw_l2_code": "801080", "sw_l2_name": "fixture-industry",
                "industry_trend": "headwind", "industry_trend_signal": signal,
            },
        )
        normalized = normalize_candidate(
            candidate, _series(), _overlay_row(), 55.0, {"available_cash": 500000.0}, "shock")
        weekly = build_weekly_report([normalized], AS_OF, GEN)
        report = weekly["reports"][0]
        before = (report["machine"]["entry_exit_size_star"]["star"], report["m67"]["table"]["操作"])

        results = build_task_results(candidate, AS_OF, official_structured={
            "status": "checked", "had_pit_announcements": False, "events": [],
        }, earnings_evidence=_earnings_evidence())
        _attach_llm_task_results(report, results)
        _validate_legacy_task_closure(report)
        weekly["effect_contract_ledger"] = build_effect_contract_ledger(weekly)
        validate_weekly_report(weekly, _feed())

        self.assertEqual((report["machine"]["entry_exit_size_star"]["star"], report["m67"]["table"]["操作"]), before)
        self.assertEqual(report["machine"]["industry_trend"]["effect"], "star_down")
        self.assertEqual(
            next(row for row in weekly["effect_contract_ledger"]["records"] if row["id"] == "llm_tasks")["status"],
            "applied",
        )
        deferred = [row for row in results if row["task_type"] in {
            "policy_news", "cross_market_linkage", "hidden_risk"}]
        self.assertTrue(all(row["status"] == "provider_unavailable" and row["effect"] == "none"
                            for row in deferred))
        impact = next(row for row in report["machine"]["operation_impact"]
                      if row["source_field"] == "earnings_bad_reaction")
        self.assertFalse(impact["production_effect_enabled"])


if __name__ == "__main__":
    unittest.main()

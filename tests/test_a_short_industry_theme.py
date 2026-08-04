"""Regression tests for deterministic A-short industry trend and theme comparison."""
from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path

import jsonschema
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.a_short_industry_theme import (  # noqa: E402
    classify_industry_trend,
    classify_theme_taxonomy,
    complete_stock_concepts,
    load_theme_taxonomy,
)
from engine.egs_industry_heat import load_governance  # noqa: E402
from runners.a_short_phase5_engine import classify_risk_families, compute_star  # noqa: E402
from runners.a_short_weekly_pipeline import _allocate_cash, normalize_candidate  # noqa: E402
from runners.forward_tracker import _candidate_row  # noqa: E402


class IndustryTrendTests(unittest.TestCase):
    def setUp(self):
        self.governance = load_governance()

    def _signal(self, score, **over):
        values = {"score": score, "sw_l2_code": "801080", "sw_l2_name": "industry",
                  "source_as_of": "20260715", "expected_as_of": "20260715",
                  "governance": self.governance}
        values.update(over)
        return classify_industry_trend(**values)

    def test_governed_edges_and_unknown_are_explicit(self):
        self.assertEqual(self._signal(20.0)["industry_trend"], "headwind")
        self.assertEqual(self._signal(20.01)["industry_trend"], "neutral")
        self.assertEqual(self._signal(80.0)["industry_trend"], "tailwind")
        unknown = self._signal(None)
        self.assertEqual(unknown["industry_trend"], "unknown")
        self.assertEqual(unknown["validation_status"], "unavailable")
        self.assertEqual(self._signal(20.0, sw_l2_code=None)["unavailable_reason"],
                         "sw_l2_unavailable")

    def test_boolean_and_huge_industry_heat_scores_are_unavailable(self):
        for value in (True, 10 ** 1000):
            with self.subTest(value=repr(value)[:20]):
                signal = self._signal(value)
                self.assertEqual(signal["classification"], "unknown")
                self.assertEqual(signal["unavailable_reason"], "industry_heat_score_invalid")

    def test_only_deterministic_industry_trend_can_change_star_or_risk_family(self):
        fam = {name: {"action": None, "hit": False, "reasons": []}
               for name in ("overheat_crowding", "portfolio_concentration", "market_regime")}
        self.assertEqual(compute_star({"industry_trend": "headwind",
                                       "industry_fundamental_trend": "tailwind"}, fam, eligible=True), 2)
        self.assertEqual(compute_star({"industry_trend": "tailwind",
                                       "industry_fundamental_trend": "headwind"}, fam, eligible=True), 3)
        risks = classify_risk_families(
            {"derived": {}, "event": {}, "liquidity": {"avg_amount_5d": 1e9},
             "overlay": {"crowding_hit": True}}, {})
        self.assertFalse(risks["overheat_crowding"]["hit"])

    def test_industry_trend_star_is_not_a_cash_allocation_input(self):
        def report(code, star, egs):
            return {"ts_code": code,
                    "m67": {"table": {"操作": "建仓", "EGS分": egs, "股数": 1000}, "精简结论区": {"操作建议": "x"}},
                    "machine": {"entry_exit_size_star": {
                        "star": star, "cash_allocation_star": 3,
                        "plan": {"entry_high": 10.0, "shares": 1000, "rr_at_entry_high": 2.0,
                                 "avg_amount_5d": 1e8}}}}
        headwind = report("000001.SZ", star=2, egs=90)
        neutral = report("000002.SZ", star=3, egs=80)
        _allocate_cash([headwind, neutral], 20000.0, as_of="20260609")
        self.assertEqual(headwind["machine"]["entry_exit_size_star"]["plan"]["cash_allocation_rank"], 1)
        self.assertEqual(neutral["machine"]["entry_exit_size_star"]["plan"]["cash_allocation_rank"], 2)

    def test_d15e_industry_trend_signal_is_formally_wired(self):
        signal = self._signal(20.0)
        normalized = normalize_candidate(
            {"ts_code": "000001.SZ", "_weekly_as_of": "20260715",
             "quote": {"source_trade_date": "20260715"}, "scores": {"industry_heat_score": 20.0},
             "industry": {"sw_l2_code": "801080", "sw_l2_name": "industry",
                          "industry_trend": "headwind", "industry_trend_signal": signal,
                          "industry_fundamental_trend": "pending_llm"}},
            [], None, None, {}, "neutral",
        )
        self.assertEqual(normalized["industry_trend"], "headwind")
        self.assertEqual(normalized["industry_fundamental_trend"], "pending_llm")
        tracker_row = _candidate_row(
            "20260715", "2026-07-15T10:00:00+08:00", "run", "b" * 64,
            {"ts_code": "000001.SZ", "industry": {"industry_trend_signal": signal}}, l3_mode="today",
        )
        self.assertEqual(tracker_row["industry_trend"], "headwind")
        self.assertEqual(tracker_row["industry_heat_score"], 20.0)

    def test_stale_d15e_industry_trend_signal_fails_closed(self):
        signal = self._signal(20.0, source_as_of="20260714")
        normalized = normalize_candidate(
            {"ts_code": "000001.SZ", "_weekly_as_of": "20260715",
             "quote": {"source_trade_date": "20260715"}, "scores": {"industry_heat_score": 20.0},
             "industry": {"sw_l2_code": "801080", "sw_l2_name": "industry",
                          "industry_trend": "headwind", "industry_trend_signal": signal}},
            [], None, None, {}, "neutral",
        )
        self.assertEqual(normalized["industry_trend"], "unknown")
        self.assertEqual(normalized["industry_trend_detail"]["effect_reason"],
                         "source_as_of_mismatch")

    def test_monday_decision_accepts_friday_price_clock_industry_signal(self):
        signal = self._signal(20.0, source_as_of="20260717", expected_as_of="20260717")
        normalized = normalize_candidate(
            {"ts_code": "000001.SZ", "_weekly_as_of": "20260717",
             "quote": {"source_trade_date": "20260717"}, "scores": {"industry_heat_score": 20.0},
             "industry": {"sw_l2_code": "801080", "sw_l2_name": "industry",
                          "industry_trend": "headwind", "industry_trend_signal": signal}},
            [], None, None, {}, "neutral",
        )
        self.assertEqual(normalized["industry_trend"], "headwind")

    def test_weekly_recomputes_score_classification_before_m67_consumes_signal(self):
        for score, forged_label in ((50.0, "headwind"), (10.0, "tailwind")):
            with self.subTest(score=score, forged_label=forged_label):
                signal = self._signal(score)
                signal["classification"] = forged_label
                signal["industry_trend"] = forged_label
                normalized = normalize_candidate(
                    {"ts_code": "000001.SZ", "_weekly_as_of": "20260715",
                     "quote": {"source_trade_date": "20260715"},
                     "scores": {"industry_heat_score": score},
                     "industry": {"sw_l2_code": "801080", "sw_l2_name": "industry",
                                  "industry_trend": forged_label,
                                  "industry_trend_signal": signal}},
                    [], None, None, {}, "neutral",
                )
                self.assertEqual(normalized["industry_trend"], "unknown")
                self.assertEqual(normalized["industry_trend_detail"]["effect_reason"],
                                 "industry_trend_score_classification_mismatch")

    def test_weekly_huge_score_fails_closed_without_overflow(self):
        signal = self._signal(20.0)
        signal["industry_heat_score"] = 10 ** 1000
        normalized = normalize_candidate(
            {"ts_code": "000001.SZ", "_weekly_as_of": "20260715",
             "quote": {"source_trade_date": "20260715"},
             "scores": {"industry_heat_score": 10 ** 1000},
             "industry": {"sw_l2_code": "801080", "sw_l2_name": "industry",
                          "industry_trend": "headwind", "industry_trend_signal": signal}},
            [], None, None, {}, "neutral",
        )
        self.assertEqual(normalized["industry_trend"], "unknown")
        self.assertEqual(normalized["industry_trend_detail"]["effect_reason"],
                         "industry_heat_score_mismatch_or_invalid")


class ThemeTaxonomyTests(unittest.TestCase):
    def setUp(self):
        self.taxonomy = copy.deepcopy(load_theme_taxonomy())
        self.l3_coverage = {
            "catalog_digest": "a" * 64,
            "complete": True,
            "scoring_universe": "a_share_main_board",
        }
        theme = self.taxonomy["canonical_themes"][0]
        theme["included_raw_concept_ids"] = ["c1", "c6"]
        theme["included_raw_concept_names"] = []
        for subtheme in theme["subthemes"]:
            subtheme["included_raw_concept_ids"] = ["c6"]
            subtheme["included_raw_concept_names"] = []

    def test_inverse_membership_prevents_sixth_concept_loss(self):
        full = complete_stock_concepts({"000001.SZ": ["c1", "c2", "c3", "c4", "c5"]},
                                       {"c6": ["000001.SZ"]})
        self.assertEqual(full["000001.SZ"], ["c1", "c2", "c3", "c4", "c5", "c6"])
        result = classify_theme_taxonomy(
            ts_code="000001.SZ", stock_concepts=full, concept_members={},
            concepts_df=pd.DataFrame([{"code": f"c{i}", "name": f"concept-{i}"} for i in range(1, 7)]),
            as_of="20260715", taxonomy=self.taxonomy,
            l3_provider="hithink_finance", l3_snapshot_date="20260715",
            l3_coverage=self.l3_coverage,
            business_evidence=[{"ts_code": "000001.SZ", "role": "core", "source_id": "local_structured",
                                "observed_at": "20260714", "checked_at": "20260715", "finding_id": "f-1"}],
        )
        self.assertEqual([raw["concept_id"] for raw in result["raw_concepts"]],
                         ["c1", "c2", "c3", "c4", "c5", "c6"])
        self.assertEqual(result["canonical_themes"][0]["role"], "core")
        self.assertEqual(result["l3_provenance"]["provider"], "hithink_finance")
        self.assertEqual(result["l3_provenance"]["validation_status"], "verified_complete")
        self.assertEqual(result["l3_provenance"]["raw_membership_source"],
                         "hithink_complete_concept_members")
        self.assertEqual(result["raw_concepts"][0]["source_id"], "hithink_finance.concept_graph")
        self.assertEqual(result["raw_concepts"][0]["source_as_of"], "20260715")
        self.assertFalse(result["production_effect_enabled"])
        self.assertFalse(result["automatic_promotion"])

    def test_taxonomy_config_schema_is_pinned(self):
        schema = json.loads((ROOT / "schemas" / "a_short_theme_taxonomy.schema.json").read_text(encoding="utf-8"))
        jsonschema.validate(load_theme_taxonomy(), schema)

    def test_a_second_theme_is_added_by_json_only(self):
        second = copy.deepcopy(self.taxonomy["canonical_themes"][0])
        second.update({"theme_id": "second_theme", "name_en": "second_theme",
                       "included_raw_concept_ids": ["c7"], "included_raw_concept_names": []})
        self.taxonomy["canonical_themes"].append(second)
        result = classify_theme_taxonomy(
            ts_code="000001.SZ", stock_concepts={"000001.SZ": ["c7"]}, concept_members={},
            concepts_df=pd.DataFrame([{"code": "c7", "name": "second"}]),
            as_of="20260715", taxonomy=self.taxonomy,
            l3_provider="hithink_finance", l3_snapshot_date="20260715",
            l3_coverage=self.l3_coverage,
        )
        self.assertEqual(result["primary_canonical_theme_id"], "second_theme")

    def test_taxonomy_never_falls_back_to_an_unbound_tushare_label(self):
        result = classify_theme_taxonomy(
            ts_code="000001.SZ", stock_concepts={"000001.SZ": ["c1"]}, concept_members={},
            concepts_df=pd.DataFrame([{"code": "c1", "name": "concept-1"}]),
            as_of="20260715", taxonomy=self.taxonomy,
        )
        self.assertEqual(result["comparison_status"], "unknown_or_unavailable")
        self.assertEqual(result["unavailable_reason"], "l3_provenance_unavailable")

    def test_legacy_snapshot_is_explicitly_noncomplete_and_uses_its_receipt_clock(self):
        result = classify_theme_taxonomy(
            ts_code="000001.SZ", stock_concepts={"000001.SZ": ["c1"]}, concept_members={},
            concepts_df=pd.DataFrame([{"code": "c1", "name": "concept-1"}]),
            as_of="20260715", taxonomy=self.taxonomy,
            l3_provider="legacy_tushare_snapshot", l3_snapshot_date="20260714",
            l3_coverage=None,
        )
        self.assertEqual(result["l3_provenance"]["validation_status"], "legacy_snapshot")
        self.assertEqual(result["l3_provenance"]["raw_membership_source"],
                         "legacy_snapshot_concept_members")
        self.assertEqual(result["raw_concepts"][0]["source_as_of"], "20260714")
        self.assertEqual(result["raw_concepts"][0]["source_snapshot_date"], "20260714")
        self.assertFalse(result["production_effect_enabled"])


if __name__ == "__main__":
    unittest.main()


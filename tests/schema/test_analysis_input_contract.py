from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

import engine.data.analysis_input_contract as analysis_input_contract
from engine.data.analysis_input_contract import (
    AnalysisInputContractError,
    is_official_a_short_analysis_input_path,
    validate_analysis_input_contract,
    validate_analysis_input_file,
)
from engine.a_short_industry_theme import (
    classify_industry_trend,
    classify_theme_taxonomy,
    unavailable_theme_taxonomy,
)
from engine.egs_industry_heat import load_governance
from tests.support.analysis_input_payload import (
    cloned_minimal_analysis_input_payload,
    current_hithink_analysis_input_payload,
)


ROOT = Path(__file__).resolve().parents[2]


class AnalysisInputContractTest(unittest.TestCase):
    def test_jsonschema_is_declared_as_runtime_validation_dependency(self) -> None:
        runtime_requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")
        dev_requirements = (ROOT / "requirements-dev.txt").read_text(encoding="utf-8")

        self.assertIn("jsonschema>=4.0", runtime_requirements)
        self.assertIn("-r requirements.txt", dev_requirements)

    def test_valid_minimal_payload_passes_schema_and_pit_contract(self) -> None:
        payload = cloned_minimal_analysis_input_payload()

        validate_analysis_input_contract(payload)

    def test_missing_required_field_fails_schema_validation(self) -> None:
        payload = cloned_minimal_analysis_input_payload()
        payload.pop("candidates")

        with self.assertRaisesRegex(ValueError, "schema validation failed"):
            validate_analysis_input_contract(payload)

    def test_pit_mode_requires_snapshot_date(self) -> None:
        payload = cloned_minimal_analysis_input_payload()
        payload["source"]["l3_mode"] = "pit"
        payload["source"]["l3_snapshot_date"] = None

        with self.assertRaisesRegex(AnalysisInputContractError, "l3_snapshot_date is required"):
            validate_analysis_input_contract(payload)

    def test_pit_snapshot_date_must_not_be_after_trade_date(self) -> None:
        payload = cloned_minimal_analysis_input_payload()
        payload["source"]["l3_mode"] = "pit"
        payload["source"]["l3_snapshot_date"] = "20260523"

        with self.assertRaisesRegex(AnalysisInputContractError, "after trade_date"):
            validate_analysis_input_contract(payload)

    def test_live_hithink_coverage_receipt_must_be_complete(self) -> None:
        payload = cloned_minimal_analysis_input_payload()
        payload["schema_version"] = "1.2.0"
        payload["source"].update({
            "data_provider": "mixed",
            "l3_provider": "hithink_finance",
            "l3_coverage": {
                "source": "hithink_finance",
                "catalog_tag": "cn_concept",
                "catalog_digest": "a" * 64,
                "catalog_board_count": 389,
                "received_board_count": 389,
                "verified_empty_board_count": 0,
                "scope_filtered_empty_board_count": 0,
                "raw_member_row_count": 69755,
                "unique_member_pair_count": 69755,
                "main_board_member_pair_count": 69000,
                "excluded_non_main_board_member_count": 755,
                "out_of_a_share_member_count": 1,
                "market_suffix_counts": {"NQ": 1, "SH": 30000, "SZ": 39754},
                "scoring_universe": "a_share_main_board",
                "complete": True,
            },
        })
        validate_analysis_input_contract(payload)

        payload["source"]["l3_coverage"]["received_board_count"] = 388
        with self.assertRaisesRegex(ValueError, "schema validation failed"):
            validate_analysis_input_contract(payload)

        payload["source"]["l3_coverage"]["catalog_board_count"] = 1
        payload["source"]["l3_coverage"]["received_board_count"] = 1
        with self.assertRaisesRegex(ValueError, "schema validation failed"):
            validate_analysis_input_contract(payload)

        payload = current_hithink_analysis_input_payload()
        payload["source"]["l3_coverage"]["main_board_member_pair_count"] += 1
        with self.assertRaisesRegex(AnalysisInputContractError, "do not reconcile"):
            validate_analysis_input_contract(payload)

    def test_current_live_hithink_receipt_is_mandatory(self) -> None:
        payload = cloned_minimal_analysis_input_payload()
        payload["schema_version"] = "1.2.0"
        payload["source"]["data_provider"] = "mixed"
        payload["source"].pop("l3_provider", None)
        payload["source"].pop("l3_coverage", None)

        with self.assertRaisesRegex(ValueError, "schema validation failed"):
            validate_analysis_input_contract(payload)

    def test_unknown_schema_version_fails_closed(self) -> None:
        payload = cloned_minimal_analysis_input_payload()
        payload["schema_version"] = "9.9.9"

        with self.assertRaisesRegex(ValueError, "schema validation failed"):
            validate_analysis_input_contract(payload)

    def test_current_moneyflow_coverage_receipt_is_required_and_clock_bound(self) -> None:
        payload = cloned_minimal_analysis_input_payload()
        payload["schema_version"] = "1.4.0"
        payload["price_data_through"] = payload["trade_date"]
        payload["source"].update({
            "l3_mode": "neutralize",
            "l3_pit_strict": False,
            "l3_snapshot_date": None,
            "l3_provider": "neutralized",
        })
        payload["market_context"]["margin_coverage"] = {
            "reference_date": payload["trade_date"],
            "effective_ref_date": None,
            "row_count": 0,
            "universe_size": 0,
            "coverage_complete": False,
            "status": "unavailable",
        }
        payload["market_context"]["moneyflow_coverage"] = {
            "reference_date": payload["trade_date"],
            "effective_ref_date": None,
            "lag_sessions": None,
            "fallback_applied": False,
            "fallback_reason": None,
            "requested_trade_dates": ["20260522", "20260521", "20260520", "20260519", "20260518"],
            "observed_trade_dates": [],
            "row_count": 0,
            "universe_size": 0,
            "target_universe_size": 2,
            "target_complete_count": 0,
            "coverage_complete": False,
            "status": "unavailable",
        }

        validate_analysis_input_contract(payload)

        payload["market_context"]["moneyflow_coverage"]["reference_date"] = "20260521"
        with self.assertRaisesRegex(AnalysisInputContractError, "reference_date must equal price_data_through"):
            validate_analysis_input_contract(payload)

    def test_complete_moneyflow_receipt_requires_target_and_window_reconciliation(self) -> None:
        payload = cloned_minimal_analysis_input_payload()
        payload["schema_version"] = "1.4.0"
        payload["price_data_through"] = payload["trade_date"]
        payload["source"].update({
            "l3_mode": "neutralize",
            "l3_pit_strict": False,
            "l3_snapshot_date": None,
            "l3_provider": "neutralized",
        })
        payload["market_context"]["margin_coverage"] = {
            "reference_date": payload["trade_date"],
            "effective_ref_date": None,
            "row_count": 0,
            "universe_size": 0,
            "coverage_complete": False,
            "status": "unavailable",
        }
        dates = ["20260522", "20260521", "20260520", "20260519", "20260518"]
        payload["market_context"]["moneyflow_coverage"] = {
            "reference_date": payload["trade_date"],
            "effective_ref_date": payload["trade_date"],
            "lag_sessions": 0,
            "fallback_applied": False,
            "fallback_reason": None,
            "requested_trade_dates": dates,
            "observed_trade_dates": dates,
            "row_count": 10,
            "universe_size": 2,
            "target_universe_size": 2,
            "target_complete_count": 2,
            "coverage_complete": True,
            "status": "complete",
        }

        validate_analysis_input_contract(payload)

        payload["market_context"]["moneyflow_coverage"]["target_complete_count"] = 1
        with self.assertRaisesRegex(AnalysisInputContractError, "complete moneyflow coverage is inconsistent"):
            validate_analysis_input_contract(payload)

    def test_today_hithink_snapshot_date_must_not_be_after_trade_date(self) -> None:
        payload = current_hithink_analysis_input_payload()
        payload["source"]["l3_snapshot_date"] = "20260523"

        with self.assertRaisesRegex(AnalysisInputContractError, "snapshot date .*after trade_date"):
            validate_analysis_input_contract(payload)

    def test_legacy_1_1_today_payload_remains_readable_without_hithink_receipt(self) -> None:
        payload = cloned_minimal_analysis_input_payload()
        payload["schema_version"] = "1.1.0"
        payload["source"].pop("l3_provider", None)
        payload["source"].pop("l3_coverage", None)

        validate_analysis_input_contract(payload)

    def test_theme_taxonomy_l3_receipt_must_match_the_analysis_input_source(self) -> None:
        payload = current_hithink_analysis_input_payload()
        payload["candidates"][0]["catalyst"]["theme_taxonomy"] = unavailable_theme_taxonomy(
            payload["trade_date"],
            "synthetic_test",
            l3_provider=payload["source"]["l3_provider"],
            l3_snapshot_date=payload["source"]["l3_snapshot_date"],
            l3_coverage=payload["source"]["l3_coverage"],
        )
        validate_analysis_input_contract(payload)

        payload["candidates"][0]["catalyst"]["theme_taxonomy"]["l3_provenance"]["provider"] = "legacy_tushare_snapshot"
        with self.assertRaisesRegex(AnalysisInputContractError, "does not match source receipt"):
            validate_analysis_input_contract(payload)

    def test_raw_theme_concepts_must_keep_the_upstream_l3_receipt_clock(self) -> None:
        payload = current_hithink_analysis_input_payload()
        payload["candidates"][0]["catalyst"]["theme_taxonomy"] = classify_theme_taxonomy(
            ts_code=payload["candidates"][0]["ts_code"],
            stock_concepts={payload["candidates"][0]["ts_code"]: ["c1"]},
            concept_members={},
            concepts_df=pd.DataFrame([{"code": "c1", "name": "concept-1"}]),
            as_of=payload["trade_date"],
            l3_provider=payload["source"]["l3_provider"],
            l3_snapshot_date=payload["source"]["l3_snapshot_date"],
            l3_coverage=payload["source"]["l3_coverage"],
        )
        validate_analysis_input_contract(payload)

        payload["candidates"][0]["catalyst"]["theme_taxonomy"]["raw_concepts"][0]["source_as_of"] = "20260521"
        with self.assertRaisesRegex(AnalysisInputContractError, "raw theme concept 0 does not match L3 receipt"):
            validate_analysis_input_contract(payload)

    def test_theme_taxonomy_may_use_an_earlier_l3_snapshot_when_receipt_is_bound(self) -> None:
        payload = current_hithink_analysis_input_payload()
        payload["run_date"] = payload["trade_date"]
        payload["source"]["l3_snapshot_date"] = "20260521"
        payload["candidates"][0]["catalyst"]["theme_taxonomy"] = classify_theme_taxonomy(
            ts_code=payload["candidates"][0]["ts_code"],
            stock_concepts={payload["candidates"][0]["ts_code"]: ["c1"]},
            concept_members={},
            concepts_df=pd.DataFrame([{"code": "c1", "name": "concept-1"}]),
            as_of=payload["trade_date"],
            l3_provider=payload["source"]["l3_provider"],
            l3_snapshot_date=payload["source"]["l3_snapshot_date"],
            l3_coverage=payload["source"]["l3_coverage"],
        )
        validate_analysis_input_contract(payload)

        payload["candidates"][0]["catalyst"]["theme_taxonomy"]["source_as_of"] = payload["trade_date"]
        with self.assertRaisesRegex(AnalysisInputContractError, "must equal L3 snapshot_date"):
            validate_analysis_input_contract(payload)

    def test_theme_l3_snapshot_after_physical_run_is_rejected(self) -> None:
        payload = current_hithink_analysis_input_payload()
        payload["run_date"] = "20260521"
        payload["source"]["l3_snapshot_date"] = payload["trade_date"]
        with self.assertRaisesRegex(AnalysisInputContractError, "after run_date"):
            validate_analysis_input_contract(payload)

    def test_unavailable_theme_taxonomy_cannot_be_relabelled_as_available(self) -> None:
        payload = cloned_minimal_analysis_input_payload()
        taxonomy = unavailable_theme_taxonomy(
            payload["trade_date"], "synthetic_unavailable",
            l3_snapshot_date=payload["source"].get("l3_snapshot_date"),
        )
        taxonomy.pop("comparison_status")
        payload["candidates"][0]["catalyst"]["theme_taxonomy"] = taxonomy
        with self.assertRaisesRegex(AnalysisInputContractError, "must remain unavailable"):
            validate_analysis_input_contract(payload)

    def test_future_earnings_report_date_is_rejected(self) -> None:
        payload = cloned_minimal_analysis_input_payload()
        payload["candidates"][0]["fundamental"]["expectation"]["earnings_report_date"] = "20260523"

        with self.assertRaisesRegex(AnalysisInputContractError, "earnings_report_date"):
            validate_analysis_input_contract(payload)

    def test_official_candidate_quote_date_must_equal_the_price_clock(self) -> None:
        payload = cloned_minimal_analysis_input_payload()
        payload["price_data_through"] = "20260522"
        payload["candidates"][0]["quote"]["source_trade_date"] = "20260521"
        payload["candidates"][0]["quote"]["price_time"] = "2026-05-21T15:00:00+08:00"

        validate_analysis_input_contract(payload)
        with self.assertRaisesRegex(AnalysisInputContractError, "official input requires.*=="):
            validate_analysis_input_contract(payload, official_input=True)

    def test_official_candidate_quote_date_cannot_be_missing(self) -> None:
        payload = cloned_minimal_analysis_input_payload()
        payload["price_data_through"] = payload["trade_date"]
        payload["candidates"][0]["quote"].pop("source_trade_date", None)

        with self.assertRaisesRegex(AnalysisInputContractError, "official input requires.*source_trade_date"):
            validate_analysis_input_contract(payload, official_input=True)

    def test_official_input_must_declare_its_price_clock(self) -> None:
        payload = cloned_minimal_analysis_input_payload()
        payload.pop("price_data_through", None)
        payload["source"].get("clocks", {}).pop("price_data_through", None)

        with self.assertRaisesRegex(AnalysisInputContractError, "official input must declare price_data_through"):
            validate_analysis_input_contract(payload, official_input=True)

    def test_official_path_auto_enables_the_candidate_price_clock_gate(self) -> None:
        payload = cloned_minimal_analysis_input_payload()
        payload["price_data_through"] = "20260522"
        payload["candidates"][0]["quote"]["source_trade_date"] = "20260521"
        payload["candidates"][0]["quote"]["price_time"] = "2026-05-21T15:00:00+08:00"

        with tempfile.TemporaryDirectory() as tmp:
            fake_root = Path(tmp)
            official_path = fake_root / "result" / "a_short" / "20260522" / "analysis_input.json"
            official_path.parent.mkdir(parents=True)
            official_path.write_text(json.dumps(payload), encoding="utf-8")
            with patch.object(analysis_input_contract, "ROOT", fake_root):
                self.assertTrue(is_official_a_short_analysis_input_path(official_path))
                with self.assertRaisesRegex(AnalysisInputContractError, "official input requires.*=="):
                    validate_analysis_input_file(official_path)

    def test_official_path_auto_rejects_an_implicit_price_clock(self) -> None:
        payload = cloned_minimal_analysis_input_payload()
        payload.pop("price_data_through", None)
        payload["source"].get("clocks", {}).pop("price_data_through", None)

        with tempfile.TemporaryDirectory() as tmp:
            fake_root = Path(tmp)
            official_path = fake_root / "result" / "a_short" / "20260522" / "analysis_input.json"
            official_path.parent.mkdir(parents=True)
            official_path.write_text(json.dumps(payload), encoding="utf-8")
            with patch.object(analysis_input_contract, "ROOT", fake_root):
                with self.assertRaisesRegex(AnalysisInputContractError, "official input must declare price_data_through"):
                    validate_analysis_input_file(official_path)

    def test_only_the_one_click_publish_path_is_official(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fake_root = Path(tmp)
            with patch.object(analysis_input_contract, "ROOT", fake_root):
                self.assertTrue(is_official_a_short_analysis_input_path(
                    fake_root / "result" / "a_short" / "20260522" / "analysis_input.json"
                ))
                self.assertFalse(is_official_a_short_analysis_input_path(
                    fake_root / "result" / "a_short" / "backtest" / "generated" / "analysis_input.json"
                ))

    def test_illegal_calendar_trade_date_is_rejected(self) -> None:
        # 8 位数字但非法历法日(六月0日 / 二月31日 / 六月31日)须拒,不得通过 schema 正则 + PIT 字典序比较。
        # 与 engine/weekly 已严格的 _is_valid_date 同口径(shared contract 是跨消费者防线)。
        for bad in ("20260600", "20260231", "20260631"):
            payload = cloned_minimal_analysis_input_payload()
            payload["trade_date"] = bad
            with self.assertRaisesRegex(AnalysisInputContractError, "calendar date"):
                validate_analysis_input_contract(payload)

    def test_illegal_calendar_earnings_report_date_is_rejected(self) -> None:
        # 非法历法日的 earnings_report_date(20260231)曾因字典序 < trade_date 被当合法过去日静默放行 → 须拒。
        payload = cloned_minimal_analysis_input_payload()
        payload["candidates"][0]["fundamental"]["expectation"]["earnings_report_date"] = "20260231"
        with self.assertRaisesRegex(AnalysisInputContractError, "calendar date"):
            validate_analysis_input_contract(payload)

    def test_valid_industry_signal_must_match_its_governed_score_classification(self) -> None:
        for score, forged_label in ((50.0, "headwind"), (10.0, "tailwind")):
            with self.subTest(score=score, forged_label=forged_label):
                payload = cloned_minimal_analysis_input_payload()
                signal = classify_industry_trend(
                    score=score,
                    sw_l2_code="801080",
                    sw_l2_name="industry",
                    source_as_of=payload["trade_date"],
                    expected_as_of=payload["trade_date"],
                    governance=load_governance(),
                )
                signal["classification"] = forged_label
                signal["industry_trend"] = forged_label
                payload["candidates"][0]["industry"].update({
                    "industry_trend": forged_label,
                    "industry_trend_signal": signal,
                })
                payload["candidates"][0]["scores"]["industry_heat_score"] = score
                with self.assertRaisesRegex(AnalysisInputContractError, "score/classification"):
                    validate_analysis_input_contract(payload)

    def test_valid_industry_signal_must_match_its_egs_source_score(self) -> None:
        payload = cloned_minimal_analysis_input_payload()
        signal = classify_industry_trend(
            score=20.0,
            sw_l2_code="801080",
            sw_l2_name="industry",
            source_as_of=payload["trade_date"],
            expected_as_of=payload["trade_date"],
            governance=load_governance(),
        )
        payload["candidates"][0]["industry"].update({
            "industry_trend": "headwind",
            "industry_trend_signal": signal,
        })
        payload["candidates"][0]["scores"]["industry_heat_score"] = 50.0
        with self.assertRaisesRegex(AnalysisInputContractError, "source score mismatch"):
            validate_analysis_input_contract(payload)


class RetiredMarketLevelLiquidityTest(unittest.TestCase):
    """Market-level `liquidity` is retired, not hidden behind a placeholder.

    Both of its fields were permanently null with no consumer anywhere. v14.2's
    regime triggers do not include turnover, so wiring one would have invented a
    rule outside the frozen spec -- and a permanently-null public field is a
    false contract that invites exactly that. Per-name `candidates[].liquidity`
    is a different thing and stays.
    """

    RETIRED = ("market_turnover_amount", "median_amount_20d")

    def _schema(self):
        return json.loads((ROOT / "schemas" / "analysis_input.schema.json")
                          .read_text(encoding="utf-8"))

    def test_the_current_schema_no_longer_exposes_market_level_liquidity(self):
        market_context = self._schema()["properties"]["market_context"]
        self.assertNotIn("liquidity", market_context["properties"])
        self.assertNotIn("liquidity", market_context["required"])

    def test_a_payload_that_still_carries_it_is_refused(self):
        payload = cloned_minimal_analysis_input_payload()
        validate_analysis_input_contract(payload)          # the honest one passes
        payload["market_context"]["liquidity"] = {
            field: None for field in self.RETIRED}
        with self.assertRaises(Exception) as caught:
            validate_analysis_input_contract(payload)
        self.assertIn("liquidity", str(caught.exception))

    def test_the_producer_no_longer_writes_it(self):
        source = (ROOT / "A-EGS" / "egs_main.py").read_text(encoding="utf-8")
        for field in self.RETIRED:
            self.assertNotIn(f'"{field}"', source, f"{field} is still produced")

    def test_no_consumer_reads_the_retired_market_level_path(self):
        """Residue sweep over the surfaces that could resurrect it."""
        offenders = []
        for relative in ("A-EGS/egs_main.py", "runners/a_short_phase5_engine.py",
                         "runners/a_short_weekly_pipeline.py",
                         "runners/a_short_m67_render.py",
                         "schemas/analysis_input.schema.json",
                         "schemas/examples/analysis_input.example.json"):
            text = (ROOT / relative).read_text(encoding="utf-8")
            for field in self.RETIRED:
                if field in text:
                    offenders.append(f"{relative}:{field}")
        self.assertEqual(offenders, [],
                         "the retired market-level path may only survive in legacy "
                         "migration records and the coverage note")

    def test_per_name_liquidity_is_untouched(self):
        candidate = (self._schema()["$defs"]["candidate"]["properties"]["liquidity"]
                     ["properties"])
        for field in ("avg_amount_5d", "avg_amount_20d", "turnover_rate"):
            self.assertIn(field, candidate)


if __name__ == "__main__":
    unittest.main()

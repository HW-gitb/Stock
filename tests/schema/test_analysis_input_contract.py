from __future__ import annotations

import unittest
from pathlib import Path

import pandas as pd

from engine.data.analysis_input_contract import (
    AnalysisInputContractError,
    validate_analysis_input_contract,
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
        payload["schema_version"] = "1.3.0"

        with self.assertRaisesRegex(ValueError, "schema validation failed"):
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
        payload["candidates"][0]["quote"].pop("source_trade_date", None)

        with self.assertRaisesRegex(AnalysisInputContractError, "official input requires.*source_trade_date"):
            validate_analysis_input_contract(payload, official_input=True)

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


if __name__ == "__main__":
    unittest.main()

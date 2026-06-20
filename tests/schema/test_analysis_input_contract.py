from __future__ import annotations

import unittest
from pathlib import Path

from engine.data.analysis_input_contract import (
    AnalysisInputContractError,
    validate_analysis_input_contract,
)
from tests.support.analysis_input_payload import cloned_minimal_analysis_input_payload


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

    def test_future_earnings_report_date_is_rejected(self) -> None:
        payload = cloned_minimal_analysis_input_payload()
        payload["candidates"][0]["fundamental"]["expectation"]["earnings_report_date"] = "20260523"

        with self.assertRaisesRegex(AnalysisInputContractError, "earnings_report_date"):
            validate_analysis_input_contract(payload)

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


if __name__ == "__main__":
    unittest.main()

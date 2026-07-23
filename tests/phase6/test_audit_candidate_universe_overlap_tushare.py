from __future__ import annotations

import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest import mock

import pandas as pd

try:
    from jsonschema import Draft7Validator
except ImportError:  # pragma: no cover - environment guard
    Draft7Validator = None  # type: ignore[assignment]

import runners.audit_candidate_universe_overlap_tushare as audit_runner
from runners.audit_candidate_universe_overlap_tushare import (
    API_FAMILIES,
    DEFAULT_LOOKBACK_DAYS,
    DEFAULT_OUT_DIR,
    BENCHMARKS,
    build_audit_payload,
    latest_membership_from_rows,
    main,
    membership_start_date,
    output_path,
)
from runners.backtest_execution import ROOT
from tests.support.analysis_input_payload import cloned_minimal_analysis_input_payload


class FakeIndexWeightPro:
    def __init__(self) -> None:
        self.calls: list[dict[str, str]] = []
        self.frames = {
            "000852.SH": pd.DataFrame(
                [
                    {"index_code": "000852.SH", "con_code": "600000.SH", "trade_date": "20250331", "weight": 0.1},
                    {"index_code": "000852.SH", "con_code": "600003.SH", "trade_date": "20250331", "weight": 0.1},
                    {"index_code": "000852.SH", "con_code": "600000.SH", "trade_date": "20250620", "weight": 0.1},
                    {"index_code": "000852.SH", "con_code": "600002.SH", "trade_date": "20250620", "weight": 0.1},
                    {"index_code": "000852.SH", "con_code": "600099.SH", "trade_date": "20250620", "weight": 0.1},
                ]
            ),
            "000300.SH": pd.DataFrame(
                [
                    {"index_code": "000300.SH", "con_code": "600001.SH", "trade_date": "20250619", "weight": 0.2},
                    {"index_code": "000300.SH", "con_code": "600088.SH", "trade_date": "20250619", "weight": 0.2},
                ]
            ),
        }

    def index_weight(self, **kwargs):
        self.calls.append(kwargs)
        return self.frames[str(kwargs["index_code"])]


@unittest.skipIf(Draft7Validator is None, "jsonschema not installed")
class CandidateUniverseOverlapAuditTest(unittest.TestCase):
    def write_analysis_input(
        self,
        path: Path,
        trade_date: str = "20260621",
        symbols: list[str] | None = None,
    ) -> None:
        payload = cloned_minimal_analysis_input_payload()
        payload["generated_at"] = "2026-06-21T15:30:00+08:00"
        payload["trade_date"] = trade_date
        requested_symbols = (
            ["600000.SH", "600001.SH", "600002.SH", "600000.SH"]
            if symbols is None
            else symbols
        )
        template = payload["candidates"][0]
        payload["candidates"] = []
        for rank, symbol in enumerate(requested_symbols, start=1):
            candidate = deepcopy(template)
            candidate["ts_code"] = symbol
            candidate["name"] = symbol
            candidate["selection"]["rank"] = rank
            payload["candidates"].append(candidate)

        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2)
            + "\n",
            encoding="utf-8",
        )

    def test_build_audit_payload_is_schema_valid_and_counts_overlap(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = Path(tmpdir) / "analysis_input.json"
            self.write_analysis_input(input_path)

            payload = build_audit_payload(
                FakeIndexWeightPro(),
                analysis_input_path=input_path,
                as_of="20260621",
                lookback_days=DEFAULT_LOOKBACK_DAYS,
                generated_at="2026-05-27T00:00:00+00:00",
            )
            schema = json.loads(
                (ROOT / "schemas" / "candidate_universe_overlap_audit.schema.json").read_text(
                    encoding="utf-8"
                )
            )
            errors = sorted(
                Draft7Validator(schema).iter_errors(payload),
                key=lambda item: list(item.path),
            )

        self.assertEqual(errors, [])
        self.assertEqual(payload["schema_name"], "candidate_universe_overlap_audit")
        self.assertEqual(payload["generated_at"], "2026-05-27T00:00:00+00:00")
        self.assertEqual(payload["scope"]["primary_switch_allowed"], False)
        self.assertEqual(payload["settings"]["provider"], "tushare")
        self.assertEqual(payload["settings"]["api_families"], API_FAMILIES)
        self.assertEqual(payload["settings"]["membership_source"], "tushare:index_weight")
        self.assertEqual(payload["candidate_universe"]["candidate_count_raw"], 4)
        self.assertEqual(payload["candidate_universe"]["candidate_count_unique"], 3)
        self.assertEqual(payload["candidate_universe"]["duplicate_candidate_count"], 1)

        csi1000 = payload["benchmarks"]["csi1000"]
        csi300 = payload["benchmarks"]["csi300"]
        self.assertEqual(csi1000["role"], "primary")
        self.assertEqual(csi1000["membership_trade_date"], "20250620")
        self.assertEqual(csi1000["overlap_symbols"], ["600000.SH", "600002.SH"])
        self.assertEqual(csi1000["overlap_count"], 2)
        self.assertEqual(csi1000["overlap_ratio"], 0.6666666667)
        self.assertEqual(csi300["overlap_symbols"], ["600001.SH"])
        self.assertEqual(csi300["overlap_count"], 1)
        self.assertEqual(
            payload["conclusion"]["nearest_benchmark_by_overlap_count"],
            "csi1000",
        )
        self.assertEqual(
            payload["conclusion"]["benchmark_policy_action"],
            "no_primary_switch_from_single_audit",
        )
        self.assertEqual(BENCHMARKS["csi1000"]["index_code"], "000852.SH")

    def test_cli_writes_default_audit_artifact(self) -> None:
        fake = FakeIndexWeightPro()
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = Path(tmpdir) / "analysis_input.json"
            out_path = Path(tmpdir) / "audit.json"
            self.write_analysis_input(input_path)

            with mock.patch.object(audit_runner, "tushare_pro", return_value=fake):
                rc = main(
                    [
                        "--as-of",
                        "20260621",
                        "--analysis-input",
                        str(input_path),
                        "--lookback-days",
                        str(DEFAULT_LOOKBACK_DAYS),
                        "--out-path",
                        str(out_path),
                        "--generated-at",
                        "2026-05-27T00:00:00+00:00",
                    ]
                )
            payload = json.loads(out_path.read_text(encoding="utf-8"))

        self.assertEqual(rc, 0)
        self.assertEqual(payload["as_of"], "20260621")
        self.assertEqual([call["fields"] for call in fake.calls], ["index_code,con_code,trade_date,weight"] * 2)
        self.assertEqual(
            {call["index_code"] for call in fake.calls},
            {"000852.SH", "000300.SH"},
        )

    def test_default_output_path_is_under_ignored_forward_aggregate_dir(self) -> None:
        self.assertEqual(
            output_path("20260621", None),
            DEFAULT_OUT_DIR / "candidate_universe_overlap_audit_20260621.json",
        )

    def test_membership_start_date_defaults_and_validates(self) -> None:
        self.assertEqual(membership_start_date("20260621", DEFAULT_LOOKBACK_DAYS), "20250328")
        with self.assertRaisesRegex(ValueError, "--as-of must be YYYYMMDD"):
            membership_start_date("2026-06-21", 10)
        with self.assertRaisesRegex(ValueError, "--lookback-days must be non-negative"):
            membership_start_date("20260621", -1)

    def test_analysis_input_trade_date_must_match_as_of(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = Path(tmpdir) / "analysis_input.json"
            self.write_analysis_input(input_path, trade_date="20260620")

            with self.assertRaisesRegex(ValueError, "must match analysis_input.trade_date"):
                build_audit_payload(
                    FakeIndexWeightPro(),
                    analysis_input_path=input_path,
                    as_of="20260621",
                    generated_at="2026-05-27T00:00:00+00:00",
                )

    def test_empty_candidate_universe_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = Path(tmpdir) / "analysis_input.json"
            self.write_analysis_input(input_path, symbols=[])

            with self.assertRaisesRegex(ValueError, "no candidate symbols"):
                build_audit_payload(
                    FakeIndexWeightPro(),
                    analysis_input_path=input_path,
                    as_of="20260621",
                    generated_at="2026-05-27T00:00:00+00:00",
                )

    def test_missing_index_weight_columns_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "index_weight missing required columns"):
            latest_membership_from_rows(
                pd.DataFrame([{"trade_date": "20250620"}]),
                "000852.SH",
                "20250101",
                "20260621",
            )

    def test_empty_index_weight_frame_reports_no_rows(self) -> None:
        with self.assertRaisesRegex(ValueError, "index_weight returned no rows"):
            latest_membership_from_rows(
                pd.DataFrame(),
                "000852.SH",
                "20250101",
                "20260621",
            )

    def test_index_weight_without_usable_rows_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "no usable rows"):
            latest_membership_from_rows(
                pd.DataFrame([{"con_code": "600000.SH", "trade_date": "20240101"}]),
                "000852.SH",
                "20250101",
                "20260621",
            )


if __name__ == "__main__":
    unittest.main()

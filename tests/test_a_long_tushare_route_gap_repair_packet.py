from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd

from runners import a_long_tushare_route_gap_repair_packet as runner


class FakeTusharePro:
    def index_classify(self, **kwargs):
        return pd.DataFrame(
            [{"index_code": "801010.SI", "industry_name": "fixture L2", "level": "L2", "parent_code": "801000.SI"}]
        )

    def index_member_all(self, **kwargs):
        return pd.DataFrame(
            [
                {
                    "ts_code": "000001.SZ",
                    "name": "active fixture",
                    "l1_code": "801000.SI",
                    "l1_name": "fixture L1",
                    "l2_code": "801010.SI",
                    "l2_name": "fixture L2",
                    "in_date": "20200101",
                    "out_date": "",
                    "is_new": "Y",
                }
            ]
        )

    def stock_basic(self, **kwargs):
        return pd.DataFrame(
            [
                {
                    "ts_code": "000003.SZ",
                    "symbol": "000003",
                    "name": "old delisted fixture",
                    "exchange": "SZSE",
                    "market": "main",
                    "list_status": "D",
                    "list_date": "19910403",
                    "delist_date": "20221230",
                }
            ]
        )

    def daily(self, **kwargs):
        return pd.DataFrame(
            [
                {
                    "ts_code": kwargs["ts_code"],
                    "trade_date": kwargs["end_date"],
                    "open": 10.0,
                    "close": 9.5,
                }
            ]
        )

    def adj_factor(self, **kwargs):
        return pd.DataFrame(
            [
                {
                    "ts_code": kwargs["ts_code"],
                    "trade_date": kwargs["end_date"],
                    "adj_factor": 1.0,
                }
            ]
        )


class ALongTushareRouteGapRepairPacketTest(unittest.TestCase):
    def setUp(self) -> None:
        self.raw_root = runner.RAW_ROOT / "unit_test"
        shutil.rmtree(self.raw_root, ignore_errors=True)

    def tearDown(self) -> None:
        shutil.rmtree(self.raw_root, ignore_errors=True)

    def test_fake_client_writes_pass_summary_and_raw_payloads(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            summary_path = Path(tmp) / "summary.json"

            summary = runner.execute_route_gap_repair(
                pro_factory=lambda: FakeTusharePro(),
                raw_root=self.raw_root,
                summary_path=summary_path,
                generated_at="2026-06-04T00:00:00+00:00",
            )

            persisted = json.loads(summary_path.read_text(encoding="utf-8"))
            self.assertEqual(summary, persisted)
            self.assertEqual(summary["decision"]["gap_repair_status"], "passed_route_gap_field_presence_only")
            self.assertTrue(summary["scope"]["provider_call_executed"])
            self.assertFalse(summary["decision"]["data_can_be_used_now"])
            self.assertFalse(summary["decision"]["materialization_allowed_by_this_summary"])
            self.assertEqual(summary["execution"]["actual_call_count"], 5)
            self.assertLessEqual(summary["execution"]["actual_call_count"], runner.MAX_TOTAL_CALLS)
            self.assertFalse(self._contains_key(summary, "records"))

            by_call = {item["call_id"]: item for item in summary["endpoint_results"]}
            member = by_call["index_member_all_current_field_mapping"]
            self.assertEqual(member["mapped_field_roles"]["member_symbol"], "ts_code")
            self.assertEqual(member["mapped_field_roles"]["industry_code"], "l2_code")

            daily = by_call["daily_older_delisted_terminal_window"]
            self.assertEqual(daily["request_shape_without_token"]["ts_code"], "000003.SZ")
            self.assertEqual(daily["request_shape_without_token"]["end_date"], "20221230")

            raw_refs = [Path(item["raw_payload_ref"]) for item in summary["endpoint_results"]]
            self.assertTrue(raw_refs)
            self.assertTrue(
                all(ref.as_posix().startswith("data/a_long/raw/tushare/route_gap_repair_20260604/") for ref in raw_refs)
            )
            self.assertTrue(all((runner.ROOT / ref).exists() for ref in raw_refs))

    def test_missing_token_records_no_execution_without_network(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            summary_path = Path(tmp) / "summary.json"
            with mock.patch.dict(os.environ, {}, clear=True):
                summary = runner.execute_route_gap_repair(
                    raw_root=self.raw_root,
                    summary_path=summary_path,
                    generated_at="2026-06-04T00:00:00+00:00",
                )

            self.assertEqual(summary["decision"]["gap_repair_status"], "not_executed_environment_missing")
            self.assertFalse(summary["scope"]["provider_call_executed"])
            self.assertFalse(summary["execution"]["network_call_attempted"])
            self.assertEqual(summary["execution"]["actual_call_count"], 0)
            self.assertEqual(summary["endpoint_results"], [])
            self.assertTrue(summary_path.exists())

    def test_raw_root_must_stay_under_gitignored_route_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                runner.execute_route_gap_repair(
                    pro_factory=lambda: FakeTusharePro(),
                    raw_root=Path(tmp) / "raw",
                    summary_path=Path(tmp) / "summary.json",
                    generated_at="2026-06-04T00:00:00+00:00",
                )

    def test_select_older_delisted_sample_avoids_latest_unsettled_sample(self) -> None:
        sample = runner.select_older_delisted_sample(
            [
                {"ts_code": "000638.SZ", "delist_date": "20260603"},
                {"ts_code": "000003.SZ", "delist_date": "20221230"},
            ]
        )

        self.assertEqual(sample, {"ts_code": "000003.SZ", "delist_date": "20221230"})

    def _contains_key(self, payload, needle: str) -> bool:
        if isinstance(payload, dict):
            return any(key == needle or self._contains_key(value, needle) for key, value in payload.items())
        if isinstance(payload, list):
            return any(self._contains_key(item, needle) for item in payload)
        return False


if __name__ == "__main__":
    unittest.main()

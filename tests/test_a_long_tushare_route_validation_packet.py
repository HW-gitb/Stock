from __future__ import annotations

import argparse
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd

from runners import a_long_tushare_route_validation_packet as runner


class FakeTusharePro:
    def trade_cal(self, **kwargs):
        return pd.DataFrame([{"cal_date": "20180131", "is_open": "1", "exchange": "SSE"}])

    def stock_basic(self, **kwargs):
        status = kwargs.get("list_status")
        if status == "D":
            return pd.DataFrame(
                [
                    {
                        "ts_code": "000003.SZ",
                        "symbol": "000003",
                        "name": "delisted fixture",
                        "exchange": "SZSE",
                        "market": "main",
                        "list_status": "D",
                        "list_date": "19910403",
                        "delist_date": "20240110",
                    }
                ]
            )
        return pd.DataFrame(
            [
                {
                    "ts_code": "000001.SZ",
                    "symbol": "000001",
                    "name": "active fixture",
                    "exchange": "SZSE",
                    "market": "main",
                    "list_status": "L",
                    "list_date": "19910403",
                    "delist_date": None,
                }
            ]
        )

    def index_classify(self, **kwargs):
        level = kwargs.get("level")
        if level == "L2":
            return pd.DataFrame(
                [{"index_code": "801010.SI", "industry_name": "fixture L2", "level": "L2", "parent_code": "801000.SI"}]
            )
        return pd.DataFrame(
            [{"index_code": "801000.SI", "industry_name": "fixture L1", "level": "L1", "parent_code": ""}]
        )

    def index_member(self, **kwargs):
        return pd.DataFrame(
            [
                {
                    "index_code": kwargs["index_code"],
                    "con_code": "000001.SZ",
                    "in_date": "20200101",
                    "out_date": "",
                }
            ]
        )

    def index_member_all(self, **kwargs):
        return pd.DataFrame(
            [
                {
                    "index_code": "801010.SI",
                    "con_code": "000001.SZ",
                    "in_date": "20200101",
                    "out_date": "",
                }
            ]
        )

    def income(self, **kwargs):
        return self._fundamental(kwargs, {"revenue": 100.0, "n_income_attr_p": 10.0})

    def balancesheet(self, **kwargs):
        return self._fundamental(
            kwargs,
            {"total_assets": 1000.0, "total_liab": 300.0, "total_hldr_eqy_exc_min_int": 700.0},
        )

    def cashflow(self, **kwargs):
        return self._fundamental(kwargs, {"n_cashflow_act": 20.0})

    def fina_indicator(self, **kwargs):
        return self._fundamental(kwargs, {"roe": 0.12, "profit_dedt": 9.0})

    def daily(self, **kwargs):
        return pd.DataFrame(
            [
                {
                    "ts_code": kwargs["ts_code"],
                    "trade_date": kwargs.get("end_date", "20240105"),
                    "open": 10.0,
                    "close": 10.5,
                }
            ]
        )

    def adj_factor(self, **kwargs):
        return pd.DataFrame(
            [
                {
                    "ts_code": kwargs["ts_code"],
                    "trade_date": kwargs.get("end_date", "20240105"),
                    "adj_factor": 1.0,
                }
            ]
        )

    def dividend(self, **kwargs):
        return pd.DataFrame(
            [
                {
                    "ts_code": kwargs["ts_code"],
                    "end_date": "20231231",
                    "ann_date": "20240401",
                    "record_date": "20240601",
                    "ex_date": "20240602",
                    "pay_date": "20240603",
                    "cash_div": 1.0,
                    "cash_div_tax": 1.0,
                }
            ]
        )

    def index_daily(self, **kwargs):
        return pd.DataFrame(
            [{"ts_code": kwargs["ts_code"], "trade_date": "20240105", "open": 100.0, "close": 101.0}]
        )

    def _fundamental(self, kwargs, extra):
        payload = {
            "ts_code": kwargs["ts_code"],
            "ann_date": "20240401",
            "f_ann_date": "20240401",
            "end_date": kwargs.get("period", "20231231"),
            "report_type": "1",
        }
        payload.update(extra)
        return pd.DataFrame([payload])


class ALongTushareRouteValidationPacketTest(unittest.TestCase):
    def setUp(self) -> None:
        self.raw_root = runner.RAW_ROOT / "unit_test"
        shutil.rmtree(self.raw_root, ignore_errors=True)

    def tearDown(self) -> None:
        shutil.rmtree(self.raw_root, ignore_errors=True)

    def test_fake_client_writes_no_secret_summary_and_raw_payloads(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            summary_path = Path(tmp) / "summary.json"

            summary = runner.execute_route_validation(
                pro_factory=lambda: FakeTusharePro(),
                raw_root=self.raw_root,
                summary_path=summary_path,
                generated_at="2026-06-04T00:00:00+00:00",
            )

            persisted = json.loads(summary_path.read_text(encoding="utf-8"))
            self.assertEqual(summary, persisted)
            self.assertEqual(summary["decision"]["route_validation_status"], "passed_field_presence_only")
            self.assertTrue(summary["scope"]["provider_call_executed"])
            self.assertFalse(summary["decision"]["data_can_be_used_now"])
            self.assertEqual(summary["execution"]["actual_call_count"], len(runner.call_plan()))
            self.assertLessEqual(summary["execution"]["actual_call_count"], runner.MAX_TOTAL_CALLS)
            self.assertFalse(summary["scope"]["tracked_summary_contains_raw_rows"])
            self.assertFalse(summary["scope"]["tracked_summary_contains_secret"])
            self.assertFalse(self._contains_key(summary, "records"))

            by_call = {item["call_id"]: item for item in summary["endpoint_results"]}
            terminal_daily = by_call["daily_first_delisted_terminal_window"]
            self.assertEqual(terminal_daily["request_shape_without_token"]["ts_code"], "000003.SZ")
            self.assertEqual(terminal_daily["request_shape_without_token"]["end_date"], "20240110")

            raw_refs = [Path(item["raw_payload_ref"]) for item in summary["endpoint_results"]]
            self.assertTrue(raw_refs)
            self.assertTrue(all(ref.as_posix().startswith("data/a_long/raw/tushare/route_validation_20260604/") for ref in raw_refs))
            self.assertTrue(all((runner.ROOT / ref).exists() for ref in raw_refs))

    def test_missing_token_records_no_execution_without_network(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            summary_path = Path(tmp) / "summary.json"
            with mock.patch.dict(os.environ, {}, clear=True):
                summary = runner.execute_route_validation(
                    raw_root=self.raw_root,
                    summary_path=summary_path,
                    generated_at="2026-06-04T00:00:00+00:00",
                )

            self.assertEqual(summary["decision"]["route_validation_status"], "not_executed_environment_missing")
            self.assertFalse(summary["scope"]["provider_call_executed"])
            self.assertFalse(summary["execution"]["network_call_attempted"])
            self.assertEqual(summary["execution"]["actual_call_count"], 0)
            self.assertEqual(summary["endpoint_results"], [])
            self.assertTrue(summary_path.exists())

    def test_raw_root_must_stay_under_gitignored_route_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                runner.execute_route_validation(
                    pro_factory=lambda: FakeTusharePro(),
                    raw_root=Path(tmp) / "raw",
                    summary_path=Path(tmp) / "summary.json",
                    generated_at="2026-06-04T00:00:00+00:00",
                )

    def test_call_plan_stays_small_and_fixed(self) -> None:
        calls = runner.call_plan()

        self.assertEqual(len(calls), 23)
        self.assertLessEqual(len(calls), runner.MAX_TOTAL_CALLS)
        self.assertIn("daily_first_delisted_terminal_window", {item["call_id"] for item in calls})
        self.assertIn("adj_factor_first_delisted_terminal_window", {item["call_id"] for item in calls})

    def _contains_key(self, payload, needle: str) -> bool:
        if isinstance(payload, dict):
            return any(key == needle or self._contains_key(value, needle) for key, value in payload.items())
        if isinstance(payload, list):
            return any(self._contains_key(item, needle) for item in payload)
        return False


if __name__ == "__main__":
    unittest.main()

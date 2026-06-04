from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd

from runners import a_long_tushare_broader_materialization_packet as runner


class FakeTusharePro:
    def trade_cal(self, **kwargs):
        return pd.DataFrame(
            [
                {"cal_date": "20180102", "is_open": "1", "exchange": "SSE"},
                {"cal_date": "20251231", "is_open": "1", "exchange": "SSE"},
            ]
        )

    def stock_basic(self, **kwargs):
        status = kwargs["list_status"]
        if status == "L":
            return pd.DataFrame(
                [
                    {
                        "ts_code": symbol,
                        "symbol": symbol.split(".")[0],
                        "name": f"active {idx}",
                        "exchange": "SSE" if symbol.endswith(".SH") else "SZSE",
                        "market": "main",
                        "list_status": "L",
                        "list_date": "20000101",
                        "delist_date": "",
                    }
                    for idx, symbol in enumerate(runner.ACTIVE_SYMBOLS, start=1)
                ]
            )
        return pd.DataFrame(
            [
                {
                    "ts_code": "000666.SZ",
                    "symbol": "000666",
                    "name": "delisted one",
                    "exchange": "SZSE",
                    "market": "main",
                    "list_status": "D",
                    "list_date": "19961218",
                    "delist_date": "20231026",
                }
            ]
        )

    def income(self, **kwargs):
        return pd.DataFrame(
            [
                {
                    "ts_code": kwargs["ts_code"],
                    "ann_date": "20240428",
                    "f_ann_date": "20240428",
                    "end_date": "20231231",
                    "report_type": "1",
                    "revenue": 100.0,
                    "n_income_attr_p": 10.0,
                }
            ]
        )

    def balancesheet(self, **kwargs):
        return pd.DataFrame(
            [
                {
                    "ts_code": kwargs["ts_code"],
                    "ann_date": "20240428",
                    "f_ann_date": "20240428",
                    "end_date": "20231231",
                    "report_type": "1",
                    "total_assets": 1000.0,
                    "total_liab": 500.0,
                    "total_hldr_eqy_exc_min_int": 500.0,
                }
            ]
        )

    def cashflow(self, **kwargs):
        return pd.DataFrame(
            [
                {
                    "ts_code": kwargs["ts_code"],
                    "ann_date": "20240428",
                    "f_ann_date": "20240428",
                    "end_date": "20231231",
                    "report_type": "1",
                    "n_cashflow_act": 8.0,
                }
            ]
        )

    def fina_indicator(self, **kwargs):
        return pd.DataFrame(
            [
                {
                    "ts_code": kwargs["ts_code"],
                    "ann_date": "20240428",
                    "end_date": "20231231",
                    "roe": 12.0,
                    "profit_dedt": 9.0,
                }
            ]
        )

    def index_classify(self, **kwargs):
        return pd.DataFrame(
            [
                {
                    "index_code": "801010.SI",
                    "industry_name": f"fixture {kwargs['level']}",
                    "level": kwargs["level"],
                    "parent_code": "801000.SI",
                }
            ]
        )

    def index_member_all(self, **kwargs):
        return pd.DataFrame(
            [
                {
                    "ts_code": symbol,
                    "name": f"member {idx}",
                    "l1_code": "801000.SI",
                    "l1_name": "fixture L1",
                    "l2_code": "801010.SI",
                    "l2_name": "fixture L2",
                    "in_date": "20180101",
                    "out_date": "",
                    "is_new": "Y",
                }
                for idx, symbol in enumerate(runner.SYMBOLS, start=1)
            ]
        )

    def daily(self, **kwargs):
        return pd.DataFrame(
            [
                {
                    "ts_code": kwargs["ts_code"],
                    "trade_date": "20231229",
                    "open": 10.0,
                    "close": 11.0,
                    "vol": 100.0,
                    "amount": 1000.0,
                }
            ]
        )

    def adj_factor(self, **kwargs):
        return pd.DataFrame(
            [
                {
                    "ts_code": kwargs["ts_code"],
                    "trade_date": "20231229",
                    "adj_factor": 1.0,
                }
            ]
        )

    def dividend(self, **kwargs):
        return pd.DataFrame(
            [
                {
                    "ts_code": kwargs["ts_code"],
                    "ann_date": "20230601",
                    "record_date": "20230610",
                    "ex_date": "20230613",
                    "pay_date": "20230620",
                    "stk_div": 0.0,
                    "cash_div_tax": 1.0,
                }
            ]
        )

    def index_daily(self, **kwargs):
        return pd.DataFrame(
            [
                {
                    "ts_code": kwargs["ts_code"],
                    "trade_date": "20231229",
                    "open": 4000.0,
                    "close": 4100.0,
                }
            ]
        )


class FailingTusharePro:
    def __getattr__(self, name):
        raise AssertionError(f"unexpected network call during checkpoint reuse: {name}")


class EmptyDailyTusharePro(FakeTusharePro):
    def daily(self, **kwargs):
        return pd.DataFrame(columns=["ts_code", "trade_date", "open", "close", "vol", "amount"])


class ALongTushareBroaderMaterializationPacketTest(unittest.TestCase):
    def setUp(self) -> None:
        self.raw_root = runner.RAW_ROOT / "unit_test"
        shutil.rmtree(self.raw_root, ignore_errors=True)

    def tearDown(self) -> None:
        shutil.rmtree(self.raw_root, ignore_errors=True)

    def test_fake_client_writes_pass_summary_and_raw_payloads(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            summary_path = Path(tmp) / "summary.json"

            summary = runner.execute_broader_materialization(
                pro_factory=lambda: FakeTusharePro(),
                raw_root=self.raw_root,
                summary_path=summary_path,
                generated_at="2026-06-04T00:00:00+00:00",
                confirm_independent_review_pass=True,
                confirm_post_review_execute=True,
            )

            persisted = json.loads(summary_path.read_text(encoding="utf-8"))
            self.assertEqual(summary, persisted)
            self.assertEqual(summary["decision"]["materialization_status"], "passed_full_period_panel_materialization_shape")
            self.assertFalse(summary["decision"]["data_can_be_used_for_alpha_now"])
            self.assertFalse(summary["decision"]["audit_rerun_authorized_by_this_summary"])
            self.assertEqual(summary["execution"]["new_network_call_count"], runner.PLANNED_TOTAL_ENDPOINT_CALLS)
            self.assertEqual(summary["execution"]["reused_raw_payload_count"], 0)
            self.assertEqual(summary["execution"]["daily_empty_raw_refetch_count"], 0)
            self.assertEqual(summary["execution"]["min_seconds_between_network_calls"], 0.0)
            self.assertFalse(self._contains_key(summary, "records"))

            raw_refs = [Path(item["raw_payload_ref"]) for item in summary["endpoint_results"]]
            self.assertEqual(len(raw_refs), runner.PLANNED_TOTAL_ENDPOINT_CALLS)
            self.assertTrue(
                all(
                    ref.as_posix().startswith("data/a_long/raw/tushare/materialization_full_period_panel_20260604/")
                    for ref in raw_refs
                )
            )
            self.assertTrue(all((runner.ROOT / ref).exists() for ref in raw_refs))

    def test_fake_summary_validates_against_schema_when_jsonschema_available(self) -> None:
        try:
            from jsonschema import Draft7Validator
        except ModuleNotFoundError as exc:
            raise unittest.SkipTest("jsonschema is not installed in this interpreter") from exc

        with tempfile.TemporaryDirectory() as tmp:
            summary = runner.execute_broader_materialization(
                pro_factory=lambda: FakeTusharePro(),
                raw_root=self.raw_root,
                summary_path=Path(tmp) / "summary.json",
                generated_at="2026-06-04T00:00:00+00:00",
                confirm_independent_review_pass=True,
                confirm_post_review_execute=True,
            )

        schema = json.loads(
            Path("schemas/a_long_tushare_broader_materialization_execution_summary.schema.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(list(Draft7Validator(schema).iter_errors(summary)), [])

    def test_second_run_reuses_existing_raw_without_network(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            first_summary_path = Path(tmp) / "first.json"
            second_summary_path = Path(tmp) / "second.json"
            runner.execute_broader_materialization(
                pro_factory=lambda: FakeTusharePro(),
                raw_root=self.raw_root,
                summary_path=first_summary_path,
                generated_at="2026-06-04T00:00:00+00:00",
                confirm_independent_review_pass=True,
                confirm_post_review_execute=True,
            )

            summary = runner.execute_broader_materialization(
                pro_factory=lambda: FailingTusharePro(),
                raw_root=self.raw_root,
                summary_path=second_summary_path,
                generated_at="2026-06-04T00:00:01+00:00",
                confirm_independent_review_pass=True,
                confirm_post_review_execute=True,
            )

            self.assertEqual(summary["decision"]["materialization_status"], "passed_full_period_panel_materialization_shape")
            self.assertEqual(summary["execution"]["new_network_call_count"], 0)
            self.assertEqual(summary["execution"]["reused_raw_payload_count"], runner.PLANNED_TOTAL_ENDPOINT_CALLS)
            self.assertEqual(summary["execution"]["daily_empty_raw_refetch_count"], 0)
            self.assertFalse(summary["execution"]["network_call_attempted"])
            self.assertTrue(all(item["checkpoint_status"] == "reused_existing_raw" for item in summary["endpoint_results"]))

    def test_empty_daily_raw_is_refetched_with_versioned_paced_raw_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            first_summary_path = Path(tmp) / "first.json"
            second_summary_path = Path(tmp) / "second.json"
            first = runner.execute_broader_materialization(
                pro_factory=lambda: EmptyDailyTusharePro(),
                raw_root=self.raw_root,
                summary_path=first_summary_path,
                generated_at="2026-06-04T00:00:00+00:00",
                confirm_independent_review_pass=True,
                confirm_post_review_execute=True,
            )
            self.assertEqual(
                first["decision"]["materialization_status"],
                "partial_or_failed_full_period_panel_materialization",
            )

            summary = runner.execute_broader_materialization(
                pro_factory=lambda: FakeTusharePro(),
                raw_root=self.raw_root,
                summary_path=second_summary_path,
                generated_at="2026-06-04T00:00:01+00:00",
                confirm_independent_review_pass=True,
                confirm_post_review_execute=True,
            )

            self.assertEqual(summary["decision"]["materialization_status"], "passed_full_period_panel_materialization_shape")
            self.assertEqual(summary["execution"]["new_network_call_count"], len(runner.SYMBOLS))
            self.assertEqual(summary["execution"]["reused_raw_payload_count"], runner.PLANNED_TOTAL_ENDPOINT_CALLS - len(runner.SYMBOLS))
            self.assertEqual(summary["execution"]["daily_empty_raw_refetch_count"], len(runner.SYMBOLS))
            daily_results = [item for item in summary["endpoint_results"] if item["api_family"] == "daily"]
            self.assertEqual({item["checkpoint_status"] for item in daily_results}, {"written_paced_refetch_raw"})
            self.assertTrue(all(item["raw_payload_ref"].endswith("_paced_refetch.json") for item in daily_results))
            self.assertTrue(all(item["call_status"] == "success" for item in daily_results))

    def test_missing_token_records_no_execution_without_network(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            summary_path = Path(tmp) / "summary.json"
            with mock.patch.dict(os.environ, {}, clear=True):
                summary = runner.execute_broader_materialization(
                    raw_root=self.raw_root,
                    summary_path=summary_path,
                    generated_at="2026-06-04T00:00:00+00:00",
                    confirm_independent_review_pass=True,
                    confirm_post_review_execute=True,
                )

            self.assertEqual(summary["decision"]["materialization_status"], "not_executed_environment_missing")
            self.assertFalse(summary["scope"]["provider_call_executed"])
            self.assertFalse(summary["execution"]["network_call_attempted"])
            self.assertEqual(summary["execution"]["new_network_call_count"], 0)
            self.assertEqual(summary["endpoint_results"], [])
            self.assertTrue(summary_path.exists())

    def test_live_execution_requires_review_and_execute_confirmations(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(RuntimeError):
                runner.execute_broader_materialization(
                    pro_factory=lambda: FakeTusharePro(),
                    raw_root=self.raw_root,
                    summary_path=Path(tmp) / "summary.json",
                    generated_at="2026-06-04T00:00:00+00:00",
                )

    def test_raw_root_must_stay_under_gitignored_materialization_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                runner.execute_broader_materialization(
                    pro_factory=lambda: FakeTusharePro(),
                    raw_root=Path(tmp) / "raw",
                    summary_path=Path(tmp) / "summary.json",
                    generated_at="2026-06-04T00:00:00+00:00",
                    confirm_independent_review_pass=True,
                    confirm_post_review_execute=True,
                )

    def test_packet_loader_rejects_scope_creep(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            packet = runner.read_json(runner.PACKET_PATH)
            packet["scope"]["signal_search_allowed"] = True
            packet["broader_materialization_boundary"]["active_symbols"].append("000002.SZ")
            packet_path = Path(tmp) / "packet.json"
            packet_path.write_text(json.dumps(packet), encoding="utf-8")

            with self.assertRaises(ValueError):
                runner.load_and_validate_packet(packet_path)

    def test_packet_loader_rejects_non_main_board_symbol(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            packet = runner.read_json(runner.PACKET_PATH)
            packet["broader_materialization_boundary"]["active_symbols"] = [
                "000001.SZ",
                "600519.SH",
                "300750.SZ",
                "601318.SH",
                "600036.SH",
                "000651.SZ",
                "002415.SZ",
                "600276.SH",
            ]
            packet_path = Path(tmp) / "packet.json"
            packet_path.write_text(json.dumps(packet), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "main-board only"):
                runner.load_and_validate_packet(packet_path)

    def test_call_plan_matches_packet_budget(self) -> None:
        calls = runner.materialization_call_plan()

        self.assertEqual(len(calls), runner.PLANNED_TOTAL_ENDPOINT_CALLS)
        self.assertEqual(len(calls), 71)
        self.assertEqual(sum(1 for call in calls if call["table_id"] == "income"), 9)
        self.assertEqual(sum(1 for call in calls if call["api_family"] == "daily"), 9)
        self.assertEqual(sum(1 for call in calls if call["api_family"] == "index_daily"), 2)

    def _contains_key(self, payload, needle: str) -> bool:
        if isinstance(payload, dict):
            return any(key == needle or self._contains_key(value, needle) for key, value in payload.items())
        if isinstance(payload, list):
            return any(self._contains_key(item, needle) for item in payload)
        return False


if __name__ == "__main__":
    unittest.main()

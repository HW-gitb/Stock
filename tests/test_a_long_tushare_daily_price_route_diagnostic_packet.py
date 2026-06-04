from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd

from runners import a_long_tushare_daily_price_route_diagnostic_packet as runner


class FakeDailyRowsPro:
    def daily(self, **kwargs):
        return pd.DataFrame(
            [
                {
                    "ts_code": kwargs["ts_code"],
                    "trade_date": "20221230",
                    "open": 10.0,
                    "close": 11.0,
                    "vol": 100.0,
                    "amount": 1000.0,
                }
            ]
        )


class FakeWindowLimitPro:
    def daily(self, **kwargs):
        if kwargs["start_date"] == "20180101" and kwargs["end_date"] == "20251231":
            return pd.DataFrame(columns=["ts_code", "trade_date", "open", "close", "vol", "amount"])
        return pd.DataFrame(
            [
                {
                    "ts_code": kwargs["ts_code"],
                    "trade_date": "20221230",
                    "open": 10.0,
                    "close": 11.0,
                    "vol": 100.0,
                    "amount": 1000.0,
                }
            ]
        )


class FakeEmptyDailyPro:
    def daily(self, **kwargs):
        return pd.DataFrame(columns=["ts_code", "trade_date", "open", "close", "vol", "amount"])


class FakeErrorDailyPro:
    def daily(self, **kwargs):
        raise RuntimeError("fixture daily endpoint error with token=TOKEN_FIXTURE_VALUE")


class FailingTusharePro:
    def __getattr__(self, name):
        raise AssertionError(f"unexpected network call during checkpoint reuse: {name}")


class ALongTushareDailyPriceRouteDiagnosticPacketTest(unittest.TestCase):
    def setUp(self) -> None:
        self.raw_root = runner.RAW_ROOT / "unit_test"
        shutil.rmtree(self.raw_root, ignore_errors=True)

    def tearDown(self) -> None:
        shutil.rmtree(self.raw_root, ignore_errors=True)

    def _partial_prior_summary_patch(self, tmp: str):
        prior = runner.read_json(runner.PRIOR_BROADER_SUMMARY_PATH)
        prior["decision"]["materialization_status"] = "partial_or_failed_full_period_panel_materialization"
        for item in prior["endpoint_results"]:
            if item.get("api_family") == "daily" and item.get("table_id") == "daily_price_adj_factor_dividend":
                item["call_status"] = "empty"
                item["row_count"] = 0
        prior_path = Path(tmp) / "partial_prior.json"
        prior_path.write_text(json.dumps(prior), encoding="utf-8")
        original_validate = runner.validate_prior_broader_summary
        return mock.patch.object(
            runner,
            "validate_prior_broader_summary",
            side_effect=lambda path=prior_path: original_validate(prior_path),
        )

    def test_fake_client_writes_burst_rate_classification_and_raw_payloads(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            summary_path = Path(tmp) / "summary.json"

            with self._partial_prior_summary_patch(tmp):
                summary = runner.execute_daily_price_route_diagnostic(
                    pro_factory=lambda: FakeDailyRowsPro(),
                    raw_root=self.raw_root,
                    summary_path=summary_path,
                    generated_at="2026-06-04T00:00:00+00:00",
                    confirm_independent_review_pass=True,
                    confirm_post_review_execute=True,
                )

            persisted = json.loads(summary_path.read_text(encoding="utf-8"))
            self.assertEqual(summary, persisted)
            self.assertEqual(summary["decision"]["price_route_diagnostic_status"], "eight_year_isolated_returned_rows")
            self.assertIn("pacing", summary["decision"]["next_action"])
            self.assertFalse(summary["decision"]["data_can_be_used_for_alpha_now"])
            self.assertFalse(summary["decision"]["price_route_repair_authorized_by_this_summary"])
            self.assertFalse(summary["decision"]["broader_materialization_rerun_authorized_by_this_summary"])
            self.assertEqual(summary["execution"]["new_network_call_count"], 2)
            self.assertEqual(summary["execution"]["reused_raw_payload_count"], 0)
            self.assertEqual(summary["execution"]["endpoint_results_count"], 2)
            self.assertFalse(self._contains_key(summary, "records"))

            eight_year, control = summary["endpoint_results"]
            self.assertEqual(eight_year["call_id"], runner.EIGHT_YEAR_CALL_ID)
            self.assertEqual(eight_year["request_shape_without_token"]["start_date"], "20180101")
            self.assertEqual(eight_year["request_shape_without_token"]["end_date"], "20251231")
            self.assertEqual(control["call_id"], runner.CONTROL_CALL_ID)
            self.assertEqual(control["request_shape_without_token"]["start_date"], "20220101")
            self.assertEqual(control["request_shape_without_token"]["end_date"], "20221231")
            for result in summary["endpoint_results"]:
                self.assertEqual(result["request_shape_without_token"]["ts_code"], "000001.SZ")
                self.assertEqual(result["minimum_fields_missing"], [])
                raw_ref = Path(result["raw_payload_ref"])
                self.assertTrue(raw_ref.as_posix().startswith("data/a_long/raw/tushare/daily_price_route_diagnostic_20260604/"))
                self.assertTrue((runner.ROOT / raw_ref).exists())

    def test_fake_summary_validates_against_schema_when_jsonschema_available(self) -> None:
        try:
            from jsonschema import Draft7Validator
        except ModuleNotFoundError as exc:
            raise unittest.SkipTest("jsonschema is not installed in this interpreter") from exc

        with tempfile.TemporaryDirectory() as tmp:
            with self._partial_prior_summary_patch(tmp):
                summary = runner.execute_daily_price_route_diagnostic(
                    pro_factory=lambda: FakeDailyRowsPro(),
                    raw_root=self.raw_root,
                    summary_path=Path(tmp) / "summary.json",
                    generated_at="2026-06-04T00:00:00+00:00",
                    confirm_independent_review_pass=True,
                    confirm_post_review_execute=True,
                )

        schema = json.loads(
            Path("schemas/a_long_tushare_daily_price_route_diagnostic_execution_summary.schema.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(list(Draft7Validator(schema).iter_errors(summary)), [])

    def test_window_limit_classification_keeps_alpha_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self._partial_prior_summary_patch(tmp):
                summary = runner.execute_daily_price_route_diagnostic(
                    pro_factory=lambda: FakeWindowLimitPro(),
                    raw_root=self.raw_root,
                    summary_path=Path(tmp) / "summary.json",
                    generated_at="2026-06-04T00:00:00+00:00",
                    confirm_independent_review_pass=True,
                    confirm_post_review_execute=True,
                )

            self.assertEqual(summary["decision"]["price_route_diagnostic_status"], "eight_year_empty_control_returned_rows")
            self.assertIn("chunked-daily", summary["decision"]["next_action"])
            self.assertFalse(summary["decision"]["data_can_be_used_for_alpha_now"])
            self.assertEqual(summary["endpoint_results"][0]["call_status"], "empty")
            self.assertEqual(summary["endpoint_results"][1]["call_status"], "success")

    def test_both_empty_keeps_endpoint_or_account_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self._partial_prior_summary_patch(tmp):
                summary = runner.execute_daily_price_route_diagnostic(
                    pro_factory=lambda: FakeEmptyDailyPro(),
                    raw_root=self.raw_root,
                    summary_path=Path(tmp) / "summary.json",
                    generated_at="2026-06-04T00:00:00+00:00",
                    confirm_independent_review_pass=True,
                    confirm_post_review_execute=True,
                )

            self.assertEqual(summary["decision"]["price_route_diagnostic_status"], "both_windows_empty")
            self.assertFalse(summary["decision"]["data_can_be_used_for_alpha_now"])
            self.assertTrue(all(result["call_status"] == "empty" for result in summary["endpoint_results"]))

    def test_error_daily_result_is_redacted_and_keeps_alpha_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, {"TUSHARE_TOKEN": "TOKEN_FIXTURE_VALUE"}):
                with self._partial_prior_summary_patch(tmp):
                    summary = runner.execute_daily_price_route_diagnostic(
                        pro_factory=lambda: FakeErrorDailyPro(),
                        raw_root=self.raw_root,
                        summary_path=Path(tmp) / "summary.json",
                        generated_at="2026-06-04T00:00:00+00:00",
                        confirm_independent_review_pass=True,
                        confirm_post_review_execute=True,
                    )

            result = summary["endpoint_results"][0]
            self.assertEqual(summary["decision"]["price_route_diagnostic_status"], "daily_probe_error")
            self.assertEqual(result["call_status"], "error")
            self.assertNotIn("TOKEN_FIXTURE_VALUE", result["error_message_redacted"])
            self.assertFalse(summary["decision"]["signal_search_authorized_by_this_summary"])

    def test_second_run_reuses_existing_raw_without_network(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            first_summary_path = Path(tmp) / "first.json"
            second_summary_path = Path(tmp) / "second.json"
            with self._partial_prior_summary_patch(tmp):
                runner.execute_daily_price_route_diagnostic(
                    pro_factory=lambda: FakeDailyRowsPro(),
                    raw_root=self.raw_root,
                    summary_path=first_summary_path,
                    generated_at="2026-06-04T00:00:00+00:00",
                    confirm_independent_review_pass=True,
                    confirm_post_review_execute=True,
                )

                summary = runner.execute_daily_price_route_diagnostic(
                    pro_factory=lambda: FailingTusharePro(),
                    raw_root=self.raw_root,
                    summary_path=second_summary_path,
                    generated_at="2026-06-04T00:00:01+00:00",
                    confirm_independent_review_pass=True,
                    confirm_post_review_execute=True,
                )

            self.assertEqual(summary["decision"]["price_route_diagnostic_status"], "eight_year_isolated_returned_rows")
            self.assertEqual(summary["execution"]["new_network_call_count"], 0)
            self.assertEqual(summary["execution"]["reused_raw_payload_count"], 2)
            self.assertFalse(summary["execution"]["network_call_attempted"])
            self.assertTrue(all(result["checkpoint_status"] == "reused_existing_raw" for result in summary["endpoint_results"]))

    def test_live_execution_requires_review_and_execute_confirmations(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(RuntimeError):
                with self._partial_prior_summary_patch(tmp):
                    runner.execute_daily_price_route_diagnostic(
                        pro_factory=lambda: FakeDailyRowsPro(),
                        raw_root=self.raw_root,
                        summary_path=Path(tmp) / "summary.json",
                        generated_at="2026-06-04T00:00:00+00:00",
                    )

    def test_missing_token_records_no_execution_without_network(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            summary_path = Path(tmp) / "summary.json"
            with mock.patch.dict(os.environ, {}, clear=True):
                with self._partial_prior_summary_patch(tmp):
                    summary = runner.execute_daily_price_route_diagnostic(
                        raw_root=self.raw_root,
                        summary_path=summary_path,
                        generated_at="2026-06-04T00:00:00+00:00",
                        confirm_independent_review_pass=True,
                        confirm_post_review_execute=True,
                    )

            self.assertEqual(summary["decision"]["price_route_diagnostic_status"], "not_executed_environment_missing")
            self.assertFalse(summary["scope"]["provider_call_executed"])
            self.assertFalse(summary["execution"]["network_call_attempted"])
            self.assertEqual(summary["execution"]["new_network_call_count"], 0)
            self.assertEqual(summary["endpoint_results"], [])
            self.assertTrue(summary_path.exists())

    def test_raw_root_must_stay_under_gitignored_diagnostic_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                with self._partial_prior_summary_patch(tmp):
                    runner.execute_daily_price_route_diagnostic(
                        pro_factory=lambda: FakeDailyRowsPro(),
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
            packet["diagnostic_boundary"]["fixed_symbol"] = "600519.SH"
            packet["diagnostic_calls"][0]["kwargs"]["end_date"] = "20241231"
            packet["call_budget"]["planned_total_endpoint_calls"] = 3
            packet["storage_and_checkpoint_boundary"]["overwrite_existing_raw_without_resume_allowed"] = True
            packet["prohibited_claims"]["a_long_data_ready"] = True
            packet_path = Path(tmp) / "packet.json"
            packet_path.write_text(json.dumps(packet), encoding="utf-8")

            with self.assertRaises(ValueError):
                runner.load_and_validate_packet(packet_path)

    def test_partial_prior_summary_must_have_nine_empty_daily_calls(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            prior = runner.read_json(runner.PRIOR_BROADER_SUMMARY_PATH)
            prior["decision"]["materialization_status"] = "partial_or_failed_full_period_panel_materialization"
            for item in prior["endpoint_results"]:
                if item.get("api_family") == "daily":
                    item["call_status"] = "success"
                    item["row_count"] = 1
                    break
            prior_path = Path(tmp) / "prior.json"
            prior_path.write_text(json.dumps(prior), encoding="utf-8")

            with self.assertRaises(ValueError):
                runner.validate_prior_broader_summary(prior_path)

    def test_repaired_prior_summary_requires_paced_daily_success(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            prior = runner.read_json(runner.PRIOR_BROADER_SUMMARY_PATH)
            prior["decision"]["materialization_status"] = "passed_full_period_panel_materialization_shape"
            for item in prior["endpoint_results"]:
                if item.get("api_family") == "daily":
                    item["checkpoint_status"] = "reused_existing_raw"
                    break
            prior_path = Path(tmp) / "prior.json"
            prior_path.write_text(json.dumps(prior), encoding="utf-8")

            with self.assertRaises(ValueError):
                runner.validate_prior_broader_summary(prior_path)

    def test_call_plan_is_fixed_to_two_daily_probes(self) -> None:
        calls = runner.diagnostic_call_plan()

        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0]["call_id"], runner.EIGHT_YEAR_CALL_ID)
        self.assertEqual(calls[0]["kwargs"]["ts_code"], "000001.SZ")
        self.assertEqual(calls[0]["kwargs"]["start_date"], "20180101")
        self.assertEqual(calls[0]["kwargs"]["end_date"], "20251231")
        self.assertEqual(calls[1]["call_id"], runner.CONTROL_CALL_ID)
        self.assertEqual(calls[1]["kwargs"]["ts_code"], "000001.SZ")
        self.assertEqual(calls[1]["kwargs"]["start_date"], "20220101")
        self.assertEqual(calls[1]["kwargs"]["end_date"], "20221231")
        self.assertTrue(all(call["minimum_fields"] == ["ts_code", "trade_date", "open", "close"] for call in calls))

    def _contains_key(self, payload, needle: str) -> bool:
        if isinstance(payload, dict):
            return any(key == needle or self._contains_key(value, needle) for key, value in payload.items())
        if isinstance(payload, list):
            return any(self._contains_key(item, needle) for item in payload)
        return False


if __name__ == "__main__":
    unittest.main()

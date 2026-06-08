from __future__ import annotations

import copy
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from jsonschema import Draft7Validator

from runners import a_long_large_cap_market_cap_materialization as runner


def _rows(
    trade_date: str,
    *,
    main_count: int = runner.UNIVERSE_SIZE_N,
    non_main_count: int = runner.MIN_DAILY_BASIC_ROW_COUNT - runner.UNIVERSE_SIZE_N,
    circ: float | None = 1000.0,
) -> list[dict]:
    rows: list[dict] = []
    for idx in range(main_count):
        rows.append(
            {
                "ts_code": f"{600000 + idx:06d}.SH",
                "trade_date": trade_date,
                "circ_mv": None if circ is None else circ + idx,
            }
        )
    for idx in range(non_main_count):
        rows.append(
            {
                "ts_code": f"{300000 + idx:06d}.SZ",
                "trade_date": trade_date,
                "circ_mv": None if circ is None else circ / 2,
            }
        )
    return rows


class FakeGoodClient:
    def daily_basic(self, *, trade_date: str, fields: str) -> list[dict]:
        if fields != runner.DAILY_BASIC_FIELDS:
            raise AssertionError(f"unexpected fields: {fields}")
        return _rows(trade_date)


class FakeSparseMainBoardClient:
    def daily_basic(self, *, trade_date: str, fields: str) -> list[dict]:
        return _rows(trade_date, main_count=499, non_main_count=501)


class FakeErrorClient:
    def daily_basic(self, *, trade_date: str, fields: str) -> list[dict]:
        raise RuntimeError("fixture daily_basic materialization error token=TOKEN_FIXTURE_VALUE")


class FailingTushareClient:
    def __getattr__(self, name):
        raise AssertionError(f"unexpected network call during checkpoint reuse: {name}")


class ALongLargeCapMarketCapMaterializationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.raw_root = runner.RAW_ROOT / "unit_test"
        shutil.rmtree(self.raw_root, ignore_errors=True)
        # The shared large-cap pure-quality singleton ledger has since been spent; the materialization
        # pre-execution gate requires it unspent (materialization legitimately ran before that spend).
        # Inject a synthetic unspent ledger ONLY for the gate's ledger read so these fake-client tests
        # still exercise the materialization logic; every other read passes through unchanged and the
        # production gate is left intact.
        real_read_json = runner.read_json

        def _read_json_unspent_ledger(path, *args, **kwargs):
            data = real_read_json(path, *args, **kwargs)
            if Path(path) == runner.LEDGER_PATH:
                data = copy.deepcopy(data)
                data.setdefault("budget_policy", {})["tests_spent_count"] = 0
                data["budget_policy"]["tests_available_without_new_review"] = 0
                data["test_spend_log"] = []
            return data

        ledger_patch = mock.patch.object(runner, "read_json", side_effect=_read_json_unspent_ledger)
        ledger_patch.start()
        self.addCleanup(ledger_patch.stop)

    def tearDown(self) -> None:
        shutil.rmtree(self.raw_root, ignore_errors=True)

    def test_call_plan_is_fixed_to_96_monthly_daily_basic_calls(self) -> None:
        calls = runner.materialization_call_plan()

        self.assertEqual(len(calls), 96)
        self.assertEqual(calls[0]["kwargs"]["trade_date"], "20180131")
        self.assertEqual(calls[-1]["kwargs"]["trade_date"], "20251231")
        self.assertEqual({call["kwargs"]["fields"] for call in calls}, {runner.DAILY_BASIC_FIELDS})
        self.assertEqual({call["method"] for call in calls}, {"daily_basic"})
        self.assertTrue(all(call["authorizes_signal_search"] is False for call in calls))

    def test_fake_client_materializes_circ_mv_shape_without_raw_rows_or_top500_symbols_in_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            summary_path = Path(tmp) / "summary.json"
            summary = runner.execute_market_cap_materialization(
                pro_factory=lambda: FakeGoodClient(),
                raw_root=self.raw_root,
                summary_path=summary_path,
                generated_at="2026-06-07T00:00:00+00:00",
                confirm_independent_review_pass=True,
                confirm_post_review_execute=True,
                min_seconds_between_network_calls=0,
            )

            persisted = json.loads(summary_path.read_text(encoding="utf-8"))

        self.assertEqual(summary, persisted)
        self.assertEqual(summary["decision"]["market_cap_materialization_status"], "passed_market_cap_materialization_shape")
        self.assertTrue(summary["decision"]["raw_market_cap_materialization_shape_available"])
        self.assertEqual(summary["decision"]["selected_market_cap_field"], "circ_mv")
        self.assertFalse(summary["decision"]["audit_rerun_authorized_by_this_summary"])
        self.assertFalse(summary["decision"]["signal_search_authorized_by_this_summary"])
        self.assertEqual(summary["execution"]["new_network_call_count"], 96)
        self.assertEqual(summary["execution"]["reused_raw_payload_count"], 0)
        self.assertEqual(summary["coverage_rollup"]["months_with_complete_top500"], 96)
        self.assertFalse(self._contains_key(summary, "records"))
        self.assertFalse(self._contains_key(summary, "top500_symbols"))
        self.assertFalse(self._contains_key(summary, "selected_symbols"))
        self.assertEqual(len(summary["endpoint_results"]), 96)
        for result in summary["endpoint_results"]:
            raw_ref = Path(result["raw_payload_ref"])
            self.assertTrue(raw_ref.as_posix().startswith("data/a_long/raw/tushare/large_cap_market_cap_materialization_20260607/"))
            self.assertTrue((runner.ROOT / raw_ref).exists())
            self.assertEqual(result["top500_main_board_stats"]["selected_top500_count"], 500)
            self.assertTrue(result["top500_main_board_stats"]["selected_top500_complete"])
            self.assertFalse(result["top500_main_board_stats"]["top500_symbols_written_to_tracked_summary"])

    def test_fake_summary_validates_against_schema(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            summary = runner.execute_market_cap_materialization(
                pro_factory=lambda: FakeGoodClient(),
                raw_root=self.raw_root,
                summary_path=Path(tmp) / "summary.json",
                generated_at="2026-06-07T00:00:00+00:00",
                confirm_independent_review_pass=True,
                confirm_post_review_execute=True,
                min_seconds_between_network_calls=0,
            )

        schema = json.loads(Path("schemas/a_long_large_cap_market_cap_materialization_execution_summary.schema.json").read_text(encoding="utf-8"))
        self.assertEqual(list(Draft7Validator(schema).iter_errors(summary)), [])

    def test_sparse_main_board_coverage_blocks_materialization_pass(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            summary = runner.execute_market_cap_materialization(
                pro_factory=lambda: FakeSparseMainBoardClient(),
                raw_root=self.raw_root,
                summary_path=Path(tmp) / "summary.json",
                generated_at="2026-06-07T00:00:00+00:00",
                confirm_independent_review_pass=True,
                confirm_post_review_execute=True,
                min_seconds_between_network_calls=0,
            )

        self.assertEqual(summary["decision"]["market_cap_materialization_status"], "partial_or_failed_market_cap_materialization")
        self.assertFalse(summary["decision"]["raw_market_cap_materialization_shape_available"])
        self.assertLess(summary["coverage_rollup"]["min_selected_top500_count"], 500)
        self.assertFalse(summary["decision"]["signal_search_authorized_by_this_summary"])

    def test_error_is_redacted_and_keeps_signal_search_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, {"TUSHARE_TOKEN": "TOKEN_FIXTURE_VALUE"}):
                summary = runner.execute_market_cap_materialization(
                    pro_factory=lambda: FakeErrorClient(),
                    raw_root=self.raw_root,
                    summary_path=Path(tmp) / "summary.json",
                    generated_at="2026-06-07T00:00:00+00:00",
                    confirm_independent_review_pass=True,
                    confirm_post_review_execute=True,
                    min_seconds_between_network_calls=0,
                )

        result = summary["endpoint_results"][0]
        self.assertEqual(summary["decision"]["market_cap_materialization_status"], "partial_or_failed_market_cap_materialization")
        self.assertEqual(result["call_status"], "error")
        self.assertNotIn("TOKEN_FIXTURE_VALUE", result["error_message_redacted"])
        self.assertFalse(summary["decision"]["signal_search_authorized_by_this_summary"])

    def test_second_run_reuses_existing_raw_without_network(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            first_summary_path = Path(tmp) / "first.json"
            second_summary_path = Path(tmp) / "second.json"
            runner.execute_market_cap_materialization(
                pro_factory=lambda: FakeGoodClient(),
                raw_root=self.raw_root,
                summary_path=first_summary_path,
                generated_at="2026-06-07T00:00:00+00:00",
                confirm_independent_review_pass=True,
                confirm_post_review_execute=True,
                min_seconds_between_network_calls=0,
            )

            summary = runner.execute_market_cap_materialization(
                pro_factory=lambda: FailingTushareClient(),
                raw_root=self.raw_root,
                summary_path=second_summary_path,
                generated_at="2026-06-07T00:00:01+00:00",
                confirm_independent_review_pass=True,
                confirm_post_review_execute=True,
                min_seconds_between_network_calls=0,
            )

        self.assertEqual(summary["decision"]["market_cap_materialization_status"], "passed_market_cap_materialization_shape")
        self.assertEqual(summary["execution"]["new_network_call_count"], 0)
        self.assertEqual(summary["execution"]["reused_raw_payload_count"], 96)
        self.assertFalse(summary["execution"]["network_call_attempted"])
        self.assertTrue(all(result["checkpoint_status"] == "reused_existing_raw" for result in summary["endpoint_results"]))

    def test_live_execution_requires_review_and_execute_confirmations(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(RuntimeError):
                runner.execute_market_cap_materialization(
                    pro_factory=lambda: FakeGoodClient(),
                    raw_root=self.raw_root,
                    summary_path=Path(tmp) / "summary.json",
                    generated_at="2026-06-07T00:00:00+00:00",
                    min_seconds_between_network_calls=0,
                )

    def test_missing_token_records_no_execution_without_network_for_real_client_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, {}, clear=True):
                summary = runner.execute_market_cap_materialization(
                    raw_root=self.raw_root,
                    summary_path=Path(tmp) / "summary.json",
                    generated_at="2026-06-07T00:00:00+00:00",
                    confirm_independent_review_pass=True,
                    confirm_post_review_execute=True,
                    min_seconds_between_network_calls=0,
                )

        self.assertEqual(summary["decision"]["market_cap_materialization_status"], "not_executed_environment_missing")
        self.assertFalse(summary["scope"]["provider_call_executed"])
        self.assertEqual(summary["execution"]["new_network_call_count"], 0)

    def _contains_key(self, value, key: str) -> bool:
        if isinstance(value, dict):
            return key in value or any(self._contains_key(item, key) for item in value.values())
        if isinstance(value, list):
            return any(self._contains_key(item, key) for item in value)
        return False


if __name__ == "__main__":
    unittest.main()

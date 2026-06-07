from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from jsonschema import Draft7Validator

from runners import a_long_large_cap_market_cap_field_probe as runner


def _rows(trade_date: str, *, circ: float | None = 100.0, total: float | None = 200.0, count: int | None = None) -> list[dict]:
    row_count = count or runner.MINIMUM_ROW_COUNT_PER_PROBE
    return [
        {
            "ts_code": f"{idx:06d}.SZ",
            "trade_date": trade_date,
            "circ_mv": circ,
            "total_mv": total,
        }
        for idx in range(row_count)
    ]


class FakeCircMvGoodClient:
    def daily_basic(self, *, trade_date: str, fields: str) -> list[dict]:
        return _rows(trade_date, circ=100.0, total=200.0)


class FakeTotalMvFallbackClient:
    def daily_basic(self, *, trade_date: str, fields: str) -> list[dict]:
        return _rows(trade_date, circ=None, total=200.0)


class FakeSparseClient:
    def daily_basic(self, *, trade_date: str, fields: str) -> list[dict]:
        return _rows(trade_date, circ=100.0, total=200.0, count=10)


class FakeErrorClient:
    def daily_basic(self, *, trade_date: str, fields: str) -> list[dict]:
        raise RuntimeError("fixture daily_basic endpoint error with token=TOKEN_FIXTURE_VALUE")


class FailingTushareClient:
    def __getattr__(self, name):
        raise AssertionError(f"unexpected network call during checkpoint reuse: {name}")


class ALongLargeCapMarketCapFieldProbeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.raw_root = runner.RAW_ROOT / "unit_test"
        shutil.rmtree(self.raw_root, ignore_errors=True)

    def tearDown(self) -> None:
        shutil.rmtree(self.raw_root, ignore_errors=True)

    def test_fake_client_recommends_circ_mv_and_writes_no_raw_rows_to_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            summary_path = Path(tmp) / "summary.json"
            summary = runner.execute_market_cap_field_probe(
                pro_factory=lambda: FakeCircMvGoodClient(),
                raw_root=self.raw_root,
                summary_path=summary_path,
                generated_at="2026-06-07T00:00:00+00:00",
                confirm_independent_review_pass=True,
                confirm_post_review_execute=True,
            )

            persisted = json.loads(summary_path.read_text(encoding="utf-8"))
            self.assertEqual(summary, persisted)
            self.assertEqual(summary["decision"]["market_cap_field_probe_status"], "circ_mv_ready_for_reviewed_freeze")
            self.assertEqual(summary["decision"]["recommended_market_cap_field"], "circ_mv")
            self.assertTrue(summary["decision"]["field_freeze_ready_for_review"])
            self.assertFalse(summary["decision"]["market_cap_field_frozen_by_this_summary"])
            self.assertFalse(summary["decision"]["signal_search_authorized_by_this_summary"])
            self.assertEqual(summary["execution"]["new_network_call_count"], 3)
            self.assertEqual(summary["execution"]["reused_raw_payload_count"], 0)
            self.assertFalse(self._contains_key(summary, "records"))
            self.assertEqual(len(summary["endpoint_results"]), 3)
            for result in summary["endpoint_results"]:
                raw_ref = Path(result["raw_payload_ref"])
                self.assertTrue(raw_ref.as_posix().startswith("data/a_long/raw/tushare/large_cap_market_cap_field_probe_20260607/"))
                self.assertTrue((runner.ROOT / raw_ref).exists())
                self.assertTrue(result["market_cap_field_stats"]["circ_mv"]["passes_selection_rule"])

    def test_fake_summary_validates_against_schema(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            summary = runner.execute_market_cap_field_probe(
                pro_factory=lambda: FakeCircMvGoodClient(),
                raw_root=self.raw_root,
                summary_path=Path(tmp) / "summary.json",
                generated_at="2026-06-07T00:00:00+00:00",
                confirm_independent_review_pass=True,
                confirm_post_review_execute=True,
            )

        schema = json.loads(Path("schemas/a_long_large_cap_market_cap_field_probe_execution_summary.schema.json").read_text(encoding="utf-8"))
        self.assertEqual(list(Draft7Validator(schema).iter_errors(summary)), [])

    def test_total_mv_fallback_only_when_circ_mv_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            summary = runner.execute_market_cap_field_probe(
                pro_factory=lambda: FakeTotalMvFallbackClient(),
                raw_root=self.raw_root,
                summary_path=Path(tmp) / "summary.json",
                generated_at="2026-06-07T00:00:00+00:00",
                confirm_independent_review_pass=True,
                confirm_post_review_execute=True,
            )

        self.assertEqual(summary["decision"]["market_cap_field_probe_status"], "total_mv_ready_for_reviewed_freeze")
        self.assertEqual(summary["decision"]["recommended_market_cap_field"], "total_mv")
        self.assertTrue(summary["decision"]["fallback_used"])
        self.assertFalse(summary["endpoint_results"][0]["market_cap_field_stats"]["circ_mv"]["passes_selection_rule"])
        self.assertTrue(summary["endpoint_results"][0]["market_cap_field_stats"]["total_mv"]["passes_selection_rule"])

    def test_sparse_probe_blocks_field_recommendation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            summary = runner.execute_market_cap_field_probe(
                pro_factory=lambda: FakeSparseClient(),
                raw_root=self.raw_root,
                summary_path=Path(tmp) / "summary.json",
                generated_at="2026-06-07T00:00:00+00:00",
                confirm_independent_review_pass=True,
                confirm_post_review_execute=True,
            )

        self.assertEqual(summary["decision"]["market_cap_field_probe_status"], "daily_basic_probe_empty_or_too_sparse")
        self.assertIsNone(summary["decision"]["recommended_market_cap_field"])
        self.assertFalse(summary["decision"]["field_freeze_ready_for_review"])
        self.assertFalse(summary["decision"]["market_cap_materialization_authorized_by_this_summary"])

    def test_error_is_redacted_and_keeps_signal_search_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, {"TUSHARE_TOKEN": "TOKEN_FIXTURE_VALUE"}):
                summary = runner.execute_market_cap_field_probe(
                    pro_factory=lambda: FakeErrorClient(),
                    raw_root=self.raw_root,
                    summary_path=Path(tmp) / "summary.json",
                    generated_at="2026-06-07T00:00:00+00:00",
                    confirm_independent_review_pass=True,
                    confirm_post_review_execute=True,
                )

        result = summary["endpoint_results"][0]
        self.assertEqual(summary["decision"]["market_cap_field_probe_status"], "daily_basic_probe_error")
        self.assertEqual(result["call_status"], "error")
        self.assertNotIn("TOKEN_FIXTURE_VALUE", result["error_message_redacted"])
        self.assertFalse(summary["decision"]["signal_search_authorized_by_this_summary"])

    def test_second_run_reuses_existing_raw_without_network(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            first_summary_path = Path(tmp) / "first.json"
            second_summary_path = Path(tmp) / "second.json"
            runner.execute_market_cap_field_probe(
                pro_factory=lambda: FakeCircMvGoodClient(),
                raw_root=self.raw_root,
                summary_path=first_summary_path,
                generated_at="2026-06-07T00:00:00+00:00",
                confirm_independent_review_pass=True,
                confirm_post_review_execute=True,
            )

            summary = runner.execute_market_cap_field_probe(
                pro_factory=lambda: FailingTushareClient(),
                raw_root=self.raw_root,
                summary_path=second_summary_path,
                generated_at="2026-06-07T00:00:01+00:00",
                confirm_independent_review_pass=True,
                confirm_post_review_execute=True,
            )

        self.assertEqual(summary["decision"]["market_cap_field_probe_status"], "circ_mv_ready_for_reviewed_freeze")
        self.assertEqual(summary["execution"]["new_network_call_count"], 0)
        self.assertEqual(summary["execution"]["reused_raw_payload_count"], 3)
        self.assertFalse(summary["execution"]["network_call_attempted"])
        self.assertTrue(all(result["checkpoint_status"] == "reused_existing_raw" for result in summary["endpoint_results"]))

    def test_live_execution_requires_review_and_execute_confirmations(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(RuntimeError):
                runner.execute_market_cap_field_probe(
                    pro_factory=lambda: FakeCircMvGoodClient(),
                    raw_root=self.raw_root,
                    summary_path=Path(tmp) / "summary.json",
                    generated_at="2026-06-07T00:00:00+00:00",
                )

    def test_missing_token_records_no_execution_without_network_for_real_client_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, {}, clear=True):
                summary = runner.execute_market_cap_field_probe(
                    raw_root=self.raw_root,
                    summary_path=Path(tmp) / "summary.json",
                    generated_at="2026-06-07T00:00:00+00:00",
                    confirm_independent_review_pass=True,
                    confirm_post_review_execute=True,
                )

        self.assertEqual(summary["decision"]["market_cap_field_probe_status"], "not_executed_environment_missing")
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

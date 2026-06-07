from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from runners import a_long_large_cap_market_cap_audit as runner


def _payload(path: Path, trade_date: str, rows: list[dict]) -> None:
    path.write_text(
        json.dumps(
            {
                "call_id": f"daily_basic_market_cap_{trade_date}",
                "table_id": "daily_basic_market_cap_monthly",
                "api_family": "daily_basic",
                "request_shape_without_token": {
                    "trade_date": trade_date,
                    "fields": "ts_code,trade_date,circ_mv",
                },
                "call_status": "success",
                "row_count": len(rows),
                "columns": ["ts_code", "trade_date", "circ_mv"],
                "records": rows,
            }
        ),
        encoding="utf-8",
    )


def _rows(trade_date: str, count: int = 5) -> list[dict]:
    rows = [
        {"ts_code": "300001.SZ", "trade_date": trade_date, "circ_mv": 999999999.0},
    ]
    rows.extend(
        {"ts_code": f"{600000 + idx:06d}.SH", "trade_date": trade_date, "circ_mv": float(1000 + idx)}
        for idx in range(count)
    )
    return rows


def _summary(raw_ref: str, trade_date: str = "20180131", selected_count: int = 5) -> dict:
    values = [float(1000 + idx) for idx in range(selected_count)]
    return {
        "endpoint_results": [
            {
                "call_id": f"daily_basic_market_cap_{trade_date}",
                "trade_date": trade_date,
                "row_count": selected_count + 1,
                "raw_payload_ref": raw_ref,
                "top500_main_board_stats": {
                    "main_board_row_count": selected_count,
                    "main_board_positive_selected_field_count": selected_count,
                    "selected_top500_count": selected_count,
                    "selected_top500_complete": selected_count == 5,
                    "selected_market_cap_field": "circ_mv",
                    "top500_min_market_cap": min(values),
                    "top500_max_market_cap": max(values),
                    "top500_symbols_written_to_tracked_summary": False,
                },
            }
        ]
    }


class ALongLargeCapMarketCapAuditTest(unittest.TestCase):
    def test_runner_self_tests_detect_expected_violations(self) -> None:
        results = runner.run_runner_self_tests()

        self.assertEqual([item["fixture_id"] for item in results], runner.SELF_TEST_IDS)
        self.assertTrue(all(item["status"] == "pass" for item in results))
        self.assertTrue(all(item["detected_expected_violation"] for item in results))

    def test_audit_monthly_payload_rederives_top500_without_non_main_or_symbol_lists(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            raw_root = Path(temp_dir).resolve()
            raw_path = raw_root / "daily_basic_market_cap_20180131.json"
            _payload(raw_path, "20180131", _rows("20180131", count=5))
            prior_universe = {f"{600000 + idx:06d}.SH" for idx in range(5)}

            with patch.object(runner, "MONTHLY_AS_OF_DATES", ["20180131"]), patch.object(runner, "UNIVERSE_SIZE_N", 5):
                monthly = runner.audit_monthly_payloads(_summary(str(raw_path)), raw_root, prior_universe, {})

        self.assertEqual(len(monthly), 1)
        row = monthly[0]
        self.assertEqual(row["selected_top500_count"], 5)
        self.assertTrue(row["selected_top500_complete"])
        self.assertEqual(row["outside_prior_audited_universe_count"], 0)
        self.assertFalse(row["top500_symbols_written_to_tracked_report"])
        self.assertNotIn("300001.SZ", json.dumps(monthly, ensure_ascii=False))
        self.assertFalse(runner._contains_key(monthly, "top500_symbols"))

    def test_documented_exclusion_is_dropped_and_backfilled_for_signal_universe(self) -> None:
        trade_date = "20180131"
        rows = [
            {"ts_code": "600000.SH", "trade_date": trade_date, "circ_mv": 600.0},
            {"ts_code": "000043.SZ", "trade_date": trade_date, "circ_mv": 500.0},
            {"ts_code": "600001.SH", "trade_date": trade_date, "circ_mv": 400.0},
            {"ts_code": "600002.SH", "trade_date": trade_date, "circ_mv": 300.0},
            {"ts_code": "600003.SH", "trade_date": trade_date, "circ_mv": 200.0},
            {"ts_code": "600004.SH", "trade_date": trade_date, "circ_mv": 100.0},
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            raw_root = Path(temp_dir).resolve()
            raw_path = raw_root / "daily_basic_market_cap_20180131.json"
            _payload(raw_path, trade_date, rows)
            prior_universe = {f"60000{idx}.SH" for idx in range(5)}

            with patch.object(runner, "MONTHLY_AS_OF_DATES", [trade_date]), patch.object(runner, "UNIVERSE_SIZE_N", 5):
                monthly = runner.audit_monthly_payloads(
                    _summary(str(raw_path), trade_date=trade_date, selected_count=5),
                    raw_root,
                    prior_universe,
                    {trade_date: {"000043.SZ"}},
                )

        row = monthly[0]
        self.assertEqual(row["raw_top500_outside_prior_audited_universe_count"], 1)
        self.assertEqual(row["documented_data_quality_exclusion_count"], 1)
        self.assertEqual(row["outside_prior_audited_universe_count"], 0)
        self.assertEqual(row["signal_universe_count_after_exclusion_backfill"], 5)
        self.assertTrue(row["signal_universe_complete_after_exclusion_backfill"])
        self.assertEqual(row["signal_universe_backfill_count"], 1)
        self.assertEqual(row["signal_universe_outside_prior_audited_universe_count"], 0)

    def test_prior_universe_gap_blocks_decision(self) -> None:
        monthly_rows = []
        for trade_date in runner.MONTHLY_AS_OF_DATES:
            monthly_rows.append(
                {
                    "as_of": trade_date,
                    "raw_row_count": 501,
                    "summary_row_count": 501,
                    "date_mismatch_count": 0,
                    "main_board_row_count": 500,
                    "positive_main_board_circ_mv_count": 500,
                    "selected_top500_count": 500,
                    "selected_top500_complete": True,
                    "selected_top500_min_circ_mv": 1.0,
                    "selected_top500_max_circ_mv": 500.0,
                    "summary_rederivation_mismatch": False,
                    "raw_top500_outside_prior_audited_universe_count": 1 if trade_date == runner.MONTHLY_AS_OF_DATES[0] else 0,
                    "documented_data_quality_exclusion_count": 0,
                    "documented_data_quality_exclusion_sample": [],
                    "outside_prior_audited_universe_count": 1 if trade_date == runner.MONTHLY_AS_OF_DATES[0] else 0,
                    "outside_prior_audited_universe_sample": ["600001.SH"] if trade_date == runner.MONTHLY_AS_OF_DATES[0] else [],
                    "signal_universe_count_after_exclusion_backfill": 500,
                    "signal_universe_complete_after_exclusion_backfill": True,
                    "signal_universe_backfill_count": 0,
                    "signal_universe_outside_prior_audited_universe_count": 1 if trade_date == runner.MONTHLY_AS_OF_DATES[0] else 0,
                    "signal_universe_outside_prior_audited_universe_sample": ["600001.SH"] if trade_date == runner.MONTHLY_AS_OF_DATES[0] else [],
                    "size_q1_count": 100,
                    "size_q2_count": 100,
                    "size_q3_count": 100,
                    "size_q4_count": 100,
                    "size_q5_count": 100,
                    "minimum_size_quintile_count": 100,
                    "top500_symbols_written_to_tracked_report": False,
                }
            )
        summary = {
            "decision": {
                "market_cap_materialization_status": "passed_market_cap_materialization_shape",
                "selected_market_cap_field": "circ_mv",
            },
            "execution": {"endpoint_results_count": 96},
        }

        checks = runner.checks_from_monthly_rows(summary, monthly_rows, {f"{idx:06d}.SH" for idx in range(3387)})
        decision = runner.decision_from_checks(checks)

        bridge = next(check for check in checks if check["check_id"] == "prior_full_main_board_universe_bridge")
        self.assertEqual(bridge["status"], "fail_data_not_ready")
        self.assertFalse(decision["hard_checks_pass"])
        self.assertFalse(decision["signal_search_authorized_by_this_report"])

    def test_documented_single_gap_can_pass_bridge_check_after_backfill(self) -> None:
        monthly_rows = []
        for trade_date in runner.MONTHLY_AS_OF_DATES:
            is_gap_month = trade_date == "20191129"
            monthly_rows.append(
                {
                    "as_of": trade_date,
                    "raw_row_count": 501,
                    "summary_row_count": 501,
                    "date_mismatch_count": 0,
                    "main_board_row_count": 501,
                    "positive_main_board_circ_mv_count": 501,
                    "selected_top500_count": 500,
                    "selected_top500_complete": True,
                    "selected_top500_min_circ_mv": 1.0,
                    "selected_top500_max_circ_mv": 500.0,
                    "summary_rederivation_mismatch": False,
                    "raw_top500_outside_prior_audited_universe_count": 1 if is_gap_month else 0,
                    "documented_data_quality_exclusion_count": 1 if is_gap_month else 0,
                    "documented_data_quality_exclusion_sample": ["000043.SZ"] if is_gap_month else [],
                    "outside_prior_audited_universe_count": 0,
                    "outside_prior_audited_universe_sample": [],
                    "signal_universe_count_after_exclusion_backfill": 500,
                    "signal_universe_complete_after_exclusion_backfill": True,
                    "signal_universe_backfill_count": 1 if is_gap_month else 0,
                    "signal_universe_outside_prior_audited_universe_count": 0,
                    "signal_universe_outside_prior_audited_universe_sample": [],
                    "size_q1_count": 100,
                    "size_q2_count": 100,
                    "size_q3_count": 100,
                    "size_q4_count": 100,
                    "size_q5_count": 100,
                    "minimum_size_quintile_count": 100,
                    "top500_symbols_written_to_tracked_report": False,
                }
            )
        summary = {
            "decision": {
                "market_cap_materialization_status": "passed_market_cap_materialization_shape",
                "selected_market_cap_field": "circ_mv",
            },
            "execution": {"endpoint_results_count": 96},
        }

        checks = runner.checks_from_monthly_rows(summary, monthly_rows, {f"{idx:06d}.SH" for idx in range(3387)})
        bridge = next(check for check in checks if check["check_id"] == "prior_full_main_board_universe_bridge")

        self.assertEqual(bridge["status"], "pass_large_cap_market_cap_audit")
        self.assertEqual(bridge["metrics"]["documented_data_quality_exclusion_observations"], 1)
        self.assertEqual(bridge["metrics"]["total_unresolved_outside_prior_audited_universe_observations"], 0)
        self.assertEqual(bridge["metrics"]["signal_universe_backfill_observations"], 1)

    def test_execute_requires_review_and_execute_confirmations(self) -> None:
        with self.assertRaises(RuntimeError):
            runner.execute_audit()


if __name__ == "__main__":
    unittest.main()

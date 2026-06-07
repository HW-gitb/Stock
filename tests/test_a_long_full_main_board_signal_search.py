from __future__ import annotations

import csv
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from runners import a_long_full_main_board_signal_search as runner
from runners import a_long_full_main_board_data_integrity_audit as audit_runner


class ALongFullMainBoardSignalSearchTest(unittest.TestCase):
    def test_live_signal_search_requires_both_confirmations(self) -> None:
        with self.assertRaises(RuntimeError):
            runner.require_execution_confirmations(
                confirm_independent_review_pass=False,
                confirm_post_review_execute=True,
            )
        with self.assertRaises(RuntimeError):
            runner.require_execution_confirmations(
                confirm_independent_review_pass=True,
                confirm_post_review_execute=False,
            )

    def test_current_gate_artifacts_validate(self) -> None:
        prereg = runner.load_and_validate_preregistration()
        ledger_payload = runner.read_json(runner.LEDGER_PATH)
        if ledger_payload["budget_policy"]["tests_spent_count"] == 0:
            ledger = runner.load_and_validate_ledger()
        else:
            ledger = ledger_payload
            self.assertEqual(ledger["ledger_status"], "active_no_new_test_authorized")
            self.assertEqual(ledger["budget_policy"]["tests_spent_count"], 1)
        exclusions = runner.load_restatement_exclusions()

        self.assertEqual(prereg["artifact_id"], "a_long_signal_search_preregistration_20260604")
        self.assertIn(ledger["budget_policy"]["tests_spent_count"], {0, 1})
        self.assertEqual(len(exclusions), runner.EXPECTED_RESTATEMENT_EXCLUSION_GROUP_COUNT)
        audit_report = runner.load_and_validate_audit_report()
        self.assertEqual(
            audit_report["decision"]["audit_status"],
            "passed_full_main_board_data_integrity_for_signal_search",
        )
        checks = {item["check_id"]: item for item in audit_report["check_results"]}
        self.assertEqual(
            checks["selection_time_status_source"]["status"],
            "pass_full_main_board",
        )
        self.assertEqual(
            checks["return_benchmark_measurement_basis"]["metrics"]["benchmark_return_basis"],
            runner.BENCHMARK_RETURN_BASIS,
        )

    def test_audit_report_rejects_legacy_checks_field_shape(self) -> None:
        payload = copy.deepcopy(runner.read_json(runner.AUDIT_REPORT_PATH))
        payload["checks"] = payload.pop("check_results")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "legacy_audit_report.json"
            path.write_text(json.dumps(payload), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "lacks check_results"):
                runner.load_and_validate_audit_report(path)

    def test_restatement_exclusion_csv_count_is_enforced(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad_exclusions.csv"
            with path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=["table_id", "symbol", "end_date", "ann_date", "required_signal_treatment"],
                )
                writer.writeheader()
                writer.writerow(
                    {
                        "table_id": "income",
                        "symbol": "000001.SZ",
                        "end_date": "20211231",
                        "ann_date": "20220430",
                        "required_signal_treatment": "exclude_this_table_symbol_period_ann_date_group",
                    }
                )

            with self.assertRaises(ValueError):
                runner.load_restatement_exclusions(path)

    def test_select_latest_pit_row_applies_restatement_exclusion(self) -> None:
        rows = [
            {
                "ts_code": "000001.SZ",
                "end_date": "20211231",
                "ann_date": "20220430",
                "f_ann_date": "20220430",
                "revenue": 999.0,
            },
            {
                "ts_code": "000001.SZ",
                "end_date": "20210930",
                "ann_date": "20211030",
                "f_ann_date": "20211030",
                "revenue": 100.0,
            },
        ]
        exclusions = {("income", "000001.SZ", "20211231", "20220430")}

        selected = runner.select_latest_pit_row(
            rows,
            table_id="income",
            as_of="20220531",
            restatement_exclusions=exclusions,
        )

        self.assertIsNotNone(selected)
        self.assertEqual(selected["end_date"], "20210930")

    def test_compute_signal_values_uses_only_allowed_families(self) -> None:
        payloads = {
            runner.call_id_for("income", "000001.SZ"): self._payload(
                [
                    {
                        "ts_code": "000001.SZ",
                        "ann_date": "20220430",
                        "f_ann_date": "20220430",
                        "end_date": "20211231",
                        "n_income_attr_p": 100000000.0,
                        "revenue": 1000.0,
                    }
                ]
            ),
            runner.call_id_for("balancesheet", "000001.SZ"): self._payload(
                [
                    {
                        "ts_code": "000001.SZ",
                        "ann_date": "20220430",
                        "f_ann_date": "20220430",
                        "end_date": "20211231",
                        "total_assets": 1000.0,
                        "total_liab": 400.0,
                        "total_hldr_eqy_exc_min_int": 600.0,
                    }
                ]
            ),
            runner.call_id_for("cashflow", "000001.SZ"): self._payload(
                [
                    {
                        "ts_code": "000001.SZ",
                        "ann_date": "20220430",
                        "f_ann_date": "20220430",
                        "end_date": "20211231",
                        "n_cashflow_act": 120000000.0,
                    }
                ]
            ),
            runner.call_id_for("fina_indicator", "000001.SZ"): self._payload(
                [
                    {"ts_code": "000001.SZ", "ann_date": "20220430", "end_date": "20211231", "roe": 10.0, "profit_dedt": 100.0},
                    {"ts_code": "000001.SZ", "ann_date": "20210430", "end_date": "20201231", "roe": 9.0, "profit_dedt": 80.0},
                    {"ts_code": "000001.SZ", "ann_date": "20200430", "end_date": "20191231", "roe": 8.0, "profit_dedt": 70.0},
                    {"ts_code": "000001.SZ", "ann_date": "20190430", "end_date": "20181231", "roe": 7.0, "profit_dedt": 65.0},
                    {"ts_code": "000001.SZ", "ann_date": "20211030", "end_date": "20210930", "roe": 8.0, "profit_dedt": 95.0},
                    {"ts_code": "000001.SZ", "ann_date": "20210830", "end_date": "20210630", "roe": 6.0, "profit_dedt": 90.0},
                ]
            ),
        }
        store = audit_runner.PayloadStore(raw_root=Path("."), payloads=payloads)

        values = runner.compute_signal_values(store, "000001.SZ", "20220531", set())

        self.assertEqual(set(values), set(runner.ALLOWED_SIGNAL_FAMILIES))
        self.assertAlmostEqual(values["cash_conversion"], 1.2)
        self.assertAlmostEqual(values["balance_sheet_strength"], 0.2)
        expected_growths = [(100.0 - 80.0) / 80.0, (80.0 - 70.0) / 70.0, (70.0 - 65.0) / 65.0]
        self.assertAlmostEqual(values["earnings_stability"], -runner.pstdev(expected_growths))

    def test_cash_conversion_requires_same_period_income_and_cashflow_rows(self) -> None:
        symbol = "000001.SZ"
        payloads = {
            runner.call_id_for("income", symbol): self._payload(
                [
                    {
                        "ts_code": symbol,
                        "ann_date": "20220430",
                        "f_ann_date": "20220430",
                        "end_date": "20211231",
                        "n_income_attr_p": 100000000.0,
                    }
                ]
            ),
            runner.call_id_for("balancesheet", symbol): self._payload([]),
            runner.call_id_for("cashflow", symbol): self._payload(
                [
                    {
                        "ts_code": symbol,
                        "ann_date": "20220430",
                        "f_ann_date": "20220430",
                        "end_date": "20210930",
                        "n_cashflow_act": 120000000.0,
                    }
                ]
            ),
            runner.call_id_for("fina_indicator", symbol): self._payload([]),
        }
        store = audit_runner.PayloadStore(raw_root=Path("."), payloads=payloads)

        values = runner.compute_signal_values(store, symbol, "20220531", set())

        self.assertNotIn("cash_conversion", values)

    def test_profitability_quality_annualizes_ytd_roe_before_ranking(self) -> None:
        self.assertAlmostEqual(
            runner.annualized_ytd_roe({"end_date": "20220331", "roe": 2.5}),
            10.0,
        )
        self.assertAlmostEqual(
            runner.annualized_ytd_roe({"end_date": "20220630", "roe": 4.0}),
            8.0,
        )
        self.assertAlmostEqual(
            runner.annualized_ytd_roe({"end_date": "20220930", "roe": 6.0}),
            8.0,
        )
        self.assertAlmostEqual(
            runner.annualized_ytd_roe({"end_date": "20221231", "roe": 9.0}),
            9.0,
        )

    def test_cash_conversion_excludes_near_zero_net_income_denominator(self) -> None:
        symbol = "000001.SZ"
        payloads = {
            runner.call_id_for("income", symbol): self._payload(
                [
                    {
                        "ts_code": symbol,
                        "ann_date": "20220430",
                        "f_ann_date": "20220430",
                        "end_date": "20211231",
                        "n_income_attr_p": runner.CASH_CONVERSION_MIN_ABS_NET_INCOME - 1,
                    }
                ]
            ),
            runner.call_id_for("balancesheet", symbol): self._payload([]),
            runner.call_id_for("cashflow", symbol): self._payload(
                [
                    {
                        "ts_code": symbol,
                        "ann_date": "20220430",
                        "f_ann_date": "20220430",
                        "end_date": "20211231",
                        "n_cashflow_act": 50000000.0,
                    }
                ]
            ),
            runner.call_id_for("fina_indicator", symbol): self._payload([]),
        }
        store = audit_runner.PayloadStore(raw_root=Path("."), payloads=payloads)

        values = runner.compute_signal_values(store, symbol, "20220531", set())

        self.assertNotIn("cash_conversion", values)

    def test_earnings_stability_does_not_mix_ytd_quarter_sequence(self) -> None:
        symbol = "000001.SZ"
        payloads = {
            runner.call_id_for("income", symbol): self._payload([]),
            runner.call_id_for("balancesheet", symbol): self._payload([]),
            runner.call_id_for("cashflow", symbol): self._payload([]),
            runner.call_id_for("fina_indicator", symbol): self._payload(
                [
                    {"ts_code": symbol, "ann_date": "20220430", "f_ann_date": "20220430", "end_date": "20211231", "roe": 10.0, "profit_dedt": 100.0},
                    {"ts_code": symbol, "ann_date": "20211030", "f_ann_date": "20211030", "end_date": "20210930", "roe": 8.0, "profit_dedt": 95.0},
                    {"ts_code": symbol, "ann_date": "20210830", "f_ann_date": "20210830", "end_date": "20210630", "roe": 6.0, "profit_dedt": 90.0},
                    {"ts_code": symbol, "ann_date": "20210430", "f_ann_date": "20210430", "end_date": "20210331", "roe": 5.0, "profit_dedt": 40.0},
                ]
            ),
        }
        store = audit_runner.PayloadStore(raw_root=Path("."), payloads=payloads)

        values = runner.compute_signal_values(store, symbol, "20220531", set())

        self.assertNotIn("earnings_stability", values)

    def test_compute_return_uses_same_anchor_and_cost(self) -> None:
        stock = {
            "20200102": {"close": 101.0},
            "20200103": {"close": 110.0},
        }
        index = {
            "20200102": {"close": 1000.0},
            "20200103": {"close": 1050.0},
        }

        stock_return, benchmark_return, entry, exit_ = runner.compute_return(
            stock,
            index,
            ["20200101", "20200102", "20200103"],
            "20200101",
            1,
        )

        self.assertEqual((entry, exit_), ("20200102", "20200103"))
        self.assertAlmostEqual(stock_return, (110.0 / 101.0) - 1.0 - runner.ROUND_TRIP_COST)
        self.assertAlmostEqual(benchmark_return, 0.05)

    def test_compute_return_uses_actual_terminal_exit_anchor_for_benchmark(self) -> None:
        stock = {
            "20200102": {"close": 100.0},
            "20200103": {"close": 80.0},
        }
        index = {
            "20200102": {"close": 1000.0},
            "20200103": {"close": 900.0},
            "20200106": {"close": 1100.0},
        }

        stock_return, benchmark_return, entry, exit_ = runner.compute_return(
            stock,
            index,
            ["20200101", "20200102", "20200103", "20200106"],
            "20200101",
            2,
            delist_date="20200106",
        )

        self.assertEqual((entry, exit_), ("20200102", "20200103"))
        self.assertAlmostEqual(stock_return, -0.2 - runner.ROUND_TRIP_COST)
        self.assertAlmostEqual(benchmark_return, -0.1)

    def test_compute_return_uses_next_available_exit_for_non_terminal_missing_price(self) -> None:
        stock = {
            "20200102": {"close": 100.0},
            "20200107": {"close": 104.0},
        }
        index = {
            "20200102": {"close": 1000.0},
            "20200107": {"close": 1020.0},
        }

        stock_return, benchmark_return, entry, exit_ = runner.compute_return(
            stock,
            index,
            ["20200101", "20200102", "20200103", "20200106", "20200107"],
            "20200101",
            2,
        )

        self.assertEqual((entry, exit_), ("20200102", "20200107"))
        self.assertAlmostEqual(stock_return, 0.04 - runner.ROUND_TRIP_COST)
        self.assertAlmostEqual(benchmark_return, 0.02)

    def test_compute_return_does_not_backfill_non_terminal_missing_exit(self) -> None:
        stock = {
            "20200102": {"close": 100.0},
            "20200103": {"close": 99.0},
        }
        index = {
            "20200102": {"close": 1000.0},
            "20200103": {"close": 1010.0},
            "20200106": {"close": 1020.0},
        }

        stock_return, benchmark_return, entry, exit_ = runner.compute_return(
            stock,
            index,
            ["20200101", "20200102", "20200103", "20200106"],
            "20200101",
            2,
        )

        self.assertIsNone(stock_return)
        self.assertIsNone(benchmark_return)
        self.assertEqual((entry, exit_), ("20200102", "20200106"))

    def test_stock_total_return_rows_apply_adj_factor_for_split_safety(self) -> None:
        symbol = "000001.SZ"
        payloads = {
            runner.call_id_for("daily", symbol): self._payload(
                [
                    {"ts_code": symbol, "trade_date": "20200102", "open": 100.0, "close": 101.0},
                    {"ts_code": symbol, "trade_date": "20200103", "open": 51.0, "close": 50.5},
                ]
            ),
            runner.call_id_for("adj_factor", symbol): self._payload(
                [
                    {"ts_code": symbol, "trade_date": "20200102", "adj_factor": 1.0},
                    {"ts_code": symbol, "trade_date": "20200103", "adj_factor": 2.0},
                ]
            ),
        }
        store = audit_runner.PayloadStore(raw_root=Path("."), payloads=payloads)

        prices = runner.stock_total_return_close_rows(store, symbol)

        self.assertEqual(prices["20200102"], {"close": 101.0})
        self.assertEqual(prices["20200103"], {"close": 101.0})

    def test_newey_west_t_stat_is_more_conservative_for_overlap_like_series(self) -> None:
        values = [0.02 + (0.002 * (index // 6)) for index in range(48)]
        naive_t = runner.mean(values) / (runner.pstdev(values) / runner.math.sqrt(len(values)))

        hac_t, _se, lag = runner.newey_west_hac_t_stat(values, horizon=252)

        self.assertEqual(lag, 12)
        self.assertIsNotNone(hac_t)
        self.assertLess(abs(hac_t), abs(naive_t))

    def test_monthly_cohort_rows_attaches_all_benchmark_excess_fields(self) -> None:
        symbol = "000001.SZ"
        payloads = {
            runner.call_id_for("income", symbol): self._payload([]),
            runner.call_id_for("balancesheet", symbol): self._payload([]),
            runner.call_id_for("cashflow", symbol): self._payload([]),
            runner.call_id_for("fina_indicator", symbol): self._payload(
                [
                    {
                        "ts_code": symbol,
                        "ann_date": "20191231",
                        "f_ann_date": "20191231",
                        "end_date": "20190930",
                        "roe": 12.0,
                        "profit_dedt": 100.0,
                    }
                ]
            ),
            runner.call_id_for("daily", symbol): self._payload(
                [
                    {"ts_code": symbol, "trade_date": "20200102", "open": 100.0, "close": 101.0},
                    {"ts_code": symbol, "trade_date": "20200103", "open": 100.0, "close": 110.0},
                ]
            ),
            runner.call_id_for("adj_factor", symbol): self._payload(
                [
                    {"ts_code": symbol, "trade_date": "20200102", "adj_factor": 1.0},
                    {"ts_code": symbol, "trade_date": "20200103", "adj_factor": 1.0},
                ]
            ),
            runner.benchmark_call_id("H00300.CSI"): self._payload(
                [
                    {"trade_date": "20200102", "open": None, "close": 1000.0},
                    {"trade_date": "20200103", "open": None, "close": 1010.0},
                ]
            ),
            runner.benchmark_call_id("H00852.CSI"): self._payload(
                [
                    {"trade_date": "20200102", "open": None, "close": 1000.0},
                    {"trade_date": "20200103", "open": None, "close": 1020.0},
                ]
            ),
        }
        store = audit_runner.PayloadStore(raw_root=Path("."), payloads=payloads)
        context = runner.SignalContext(
            symbols=[symbol],
            active_symbols=[symbol],
            delisted_symbols=[],
            exception_symbols=set(),
            as_ofs=["20200101"],
            trade_dates=["20200101", "20200102", "20200103"],
            list_date_by_symbol={symbol: "19910101"},
            delist_date_by_symbol={symbol: None},
        )

        original_horizons = runner.HORIZONS
        original_load_industry_records = runner.load_industry_records
        try:
            runner.HORIZONS = [1]
            runner.load_industry_records = lambda _store: {
                symbol: [
                    {
                        "ts_code": symbol,
                        "l1_code": "801780.SI",
                        "l2_code": "801783.SI",
                        "in_date": "20100101",
                        "out_date": None,
                    }
                ]
            }
            rows, diagnostics = runner.monthly_cohort_rows(
                store=store,
                context=context,
                restatement_exclusions=set(),
            )
        finally:
            runner.HORIZONS = original_horizons
            runner.load_industry_records = original_load_industry_records

        self.assertEqual(diagnostics["missing_return_rows"], 0)
        self.assertEqual(len(rows), 1)
        self.assertIn("excess_CSI300", rows[0])
        self.assertIn("excess_CSI1000", rows[0])
        self.assertIsNotNone(rows[0]["excess_CSI300"])
        self.assertIsNotNone(rows[0]["excess_CSI1000"])
        original_horizons = runner.HORIZONS
        try:
            runner.HORIZONS = [1]
            results = runner.summarize_results(rows)
            self.assertGreater(sum(item["monthly_cohort_count"] for item in results), 0)
            runner.validate_pipeline_result_sanity(rows, results)
        finally:
            runner.HORIZONS = original_horizons

    def test_current_stock_basic_name_is_not_selection_time_veto_source(self) -> None:
        context = runner.SignalContext(
            symbols=["600421.SH"],
            active_symbols=["600421.SH"],
            delisted_symbols=[],
            exception_symbols=set(),
            as_ofs=["20200131"],
            trade_dates=["20200131", "20200203"],
            list_date_by_symbol={"600421.SH": "19960101"},
            delist_date_by_symbol={"600421.SH": None},
            name_by_symbol={"600421.SH": "\u9000\u5e02\u672a\u6765"},
        )

        self.assertFalse(runner.symbol_vetoed_at_selection_time(context, "600421.SH", "20200131"))

    def test_pit_selection_status_veto_blocks_only_after_observed_start(self) -> None:
        context = runner.SignalContext(
            symbols=["600421.SH"],
            active_symbols=["600421.SH"],
            delisted_symbols=[],
            exception_symbols=set(),
            as_ofs=["20200131"],
            trade_dates=["20200131", "20200203"],
            list_date_by_symbol={"600421.SH": "19960101"},
            delist_date_by_symbol={"600421.SH": None},
            selection_status_by_symbol={
                "600421.SH": [
                    {"name": "\u9000\u5e02\u672a\u6765", "start_date": "20210101", "end_date": None}
                ]
            },
        )

        self.assertFalse(runner.symbol_vetoed_at_selection_time(context, "600421.SH", "20200131"))
        self.assertTrue(runner.symbol_vetoed_at_selection_time(context, "600421.SH", "20210131"))

    def test_pit_selection_status_veto_catches_delisting_suffix_names(self) -> None:
        context = runner.SignalContext(
            symbols=["000511.SZ"],
            active_symbols=[],
            delisted_symbols=["000511.SZ"],
            exception_symbols=set(),
            as_ofs=["20180629"],
            trade_dates=["20180629", "20180702"],
            list_date_by_symbol={"000511.SZ": "19930101"},
            delist_date_by_symbol={"000511.SZ": "20180718"},
            selection_status_by_symbol={
                "000511.SZ": [
                    {"name": "\u70ef\u78b3\u9000", "start_date": "20180601", "end_date": None}
                ]
            },
        )

        self.assertTrue(runner.symbol_vetoed_at_selection_time(context, "000511.SZ", "20180629"))

    def test_select_latest_pit_row_requires_f_ann_date_for_statement_tables_only(self) -> None:
        selected = runner.select_latest_pit_row(
            [
                {
                    "ts_code": "000001.SZ",
                    "end_date": "20211231",
                    "ann_date": "20220430",
                    "revenue": 100.0,
                }
            ],
            table_id="income",
            as_of="20220531",
            restatement_exclusions=set(),
        )

        self.assertIsNone(selected)

        indicator_selected = runner.select_latest_pit_row(
            [
                {
                    "ts_code": "000001.SZ",
                    "end_date": "20211231",
                    "ann_date": "20220430",
                    "roe": 10.0,
                    "profit_dedt": 100.0,
                }
            ],
            table_id="fina_indicator",
            as_of="20220531",
            restatement_exclusions=set(),
        )

        self.assertIsNotNone(indicator_selected)
        self.assertEqual(indicator_selected["roe"], 10.0)

    def test_materialization_manifest_must_include_total_return_benchmark_payloads(self) -> None:
        fake_summary = {
            "execution": {
                "endpoint_results_count": 23718,
                "token_logged": False,
                "request_url_logged": False,
            }
        }
        price_only_manifest = {
            "index_daily_000300_SH_2018_2025": {"call_status": "success"},
            "index_daily_000852_SH_2018_2025": {"call_status": "success"},
        }

        with (
            mock.patch.object(runner, "read_json", return_value=fake_summary),
            mock.patch.object(runner.audit, "validate_materialization_summary", return_value=None),
            mock.patch.object(runner.audit, "load_endpoint_manifest", return_value=price_only_manifest),
        ):
            with self.assertRaisesRegex(ValueError, "total-return benchmark"):
                runner.validate_materialization_summary_and_manifest(Path("."))

    def test_pipeline_sanity_rejects_return_rows_with_zero_cohorts(self) -> None:
        rows = [
            {
                "as_of": "20200131",
                "symbol": "000001.SZ",
                "horizon": 252,
                "profitability_quality__non_neutral": 0.9,
                "excess_CSI1000": 0.01,
            }
        ]
        results = runner.summarize_results(rows)

        with self.assertRaisesRegex(ValueError, "pipeline failure"):
            runner.validate_pipeline_result_sanity(rows, results)

    def test_pipeline_sanity_rejects_no_evaluated_return_rows(self) -> None:
        with self.assertRaisesRegex(ValueError, "no evaluated return rows"):
            runner.validate_pipeline_result_sanity([], [])

    def _year_concentration_fixture(self, returns_by_year: dict[int, float]) -> list[dict]:
        rows = []
        for month in range(1, 51):
            year = 2018 + ((month - 1) // 10)
            month_in_year = ((month - 1) % 10) + 1
            as_of = f"{year}{month_in_year:02d}28"
            cohort_return = returns_by_year[year]
            for idx in range(15):
                rows.append(
                    {
                        "as_of": as_of,
                        "symbol": f"{idx:06d}.SZ",
                        "horizon": 252,
                        "profitability_quality__non_neutral": idx / 14,
                        "profitability_quality__industry_neutral": idx / 14,
                        "cash_conversion__non_neutral": idx / 14,
                        "cash_conversion__industry_neutral": idx / 14,
                        "balance_sheet_strength__non_neutral": idx / 14,
                        "balance_sheet_strength__industry_neutral": idx / 14,
                        "earnings_stability__non_neutral": idx / 14,
                        "earnings_stability__industry_neutral": idx / 14,
                        "excess_CSI300": cohort_return,
                        "excess_CSI1000": cohort_return,
                    }
                )
        return rows

    def _profitability_non_neutral_one_year_cell(self, rows: list[dict]) -> dict:
        results = runner.summarize_results(rows)
        return next(
            item for item in results
            if item["signal_family"] == "profitability_quality"
            and item["view"] == "non_neutral"
            and item["horizon_trading_days"] == 252
        )

    def test_summarize_results_produces_frozen_result_grid(self) -> None:
        rows = []
        for month in range(1, 51):
            year = 2018 + ((month - 1) // 10)
            month_in_year = ((month - 1) % 10) + 1
            as_of = f"{year}{month_in_year:02d}28"
            for idx in range(15):
                rows.append(
                    {
                        "as_of": as_of,
                        "symbol": f"{idx:06d}.SZ",
                        "horizon": 252,
                        "profitability_quality__non_neutral": idx / 14,
                        "profitability_quality__industry_neutral": idx / 14,
                        "cash_conversion__non_neutral": idx / 14,
                        "cash_conversion__industry_neutral": idx / 14,
                        "balance_sheet_strength__non_neutral": idx / 14,
                        "balance_sheet_strength__industry_neutral": idx / 14,
                        "earnings_stability__non_neutral": idx / 14,
                        "earnings_stability__industry_neutral": idx / 14,
                        "excess_CSI300": 0.02 if idx >= 5 else -0.01,
                        "excess_CSI1000": 0.01 if idx >= 5 else -0.02,
                    }
                )
                rows.append({**rows[-1], "horizon": 504})

        results = runner.summarize_results(rows)

        self.assertEqual(len(results), 32)
        self.assertTrue(all("bh_adjusted_p_value" in item for item in results))
        self.assertEqual({item["benchmark"] for item in results}, {"CSI300", "CSI1000"})
        self.assertTrue(all("max_single_year_positive_return_share" in item for item in results))
        self.assertTrue(all("passes_single_year_concentration_guard" in item for item in results))
        self.assertTrue(all("passes_drawdown_guard" in item for item in results))
        self.assertTrue(all("worst_monthly_cohort_excess" in item for item in results))
        self.assertTrue(all("best_monthly_cohort_excess" in item for item in results))
        self.assertTrue(all(item["monthly_t_stat_method"] == runner.MONTHLY_T_STAT_METHOD for item in results))
        self.assertEqual({item["hac_lag_months"] for item in results}, {12, 24})
        self.assertTrue(all(item["passes_minimum_monthly_cohorts"] for item in results))

    def test_summarize_results_rejects_single_year_positive_return_dominance(self) -> None:
        rows = self._year_concentration_fixture(
            {
                2018: 0.10,
                2019: 0.001,
                2020: 0.001,
                2021: 0.001,
                2022: 0.001,
            }
        )

        cell = self._profitability_non_neutral_one_year_cell(rows)

        self.assertGreater(
            cell["max_single_year_positive_return_share"],
            runner.MAX_SINGLE_YEAR_POSITIVE_RETURN_SHARE,
        )
        self.assertFalse(cell["passes_single_year_concentration_guard"])

    def test_summarize_results_accepts_year_spread_positive_return(self) -> None:
        rows = self._year_concentration_fixture(
            {
                2018: 0.02,
                2019: 0.02,
                2020: 0.02,
                2021: 0.02,
                2022: 0.02,
            }
        )

        cell = self._profitability_non_neutral_one_year_cell(rows)

        self.assertLessEqual(
            cell["max_single_year_positive_return_share"],
            runner.MAX_SINGLE_YEAR_POSITIVE_RETURN_SHARE,
        )
        self.assertTrue(cell["passes_single_year_concentration_guard"])

    def test_pre_membership_symbol_is_excluded_from_neutral_not_backcast(self) -> None:
        records = {
            "002189.SZ": [
                {
                    "ts_code": "002189.SZ",
                    "l1_code": "801740.SI",
                    "l2_code": "801745.SI",
                    "in_date": "20210730",
                    "out_date": None,
                }
            ]
        }
        context = runner.SignalContext(
            symbols=["002189.SZ"],
            active_symbols=["002189.SZ"],
            delisted_symbols=[],
            exception_symbols=set(),
            as_ofs=["20180131"],
            trade_dates=["20180131"],
            list_date_by_symbol={"002189.SZ": "20000101"},
            delist_date_by_symbol={"002189.SZ": None},
        )

        l2, l1, source, industry_excluded = runner.industry_context_for_symbol(records, context, "002189.SZ", "20180131")

        self.assertIsNone(l2)
        self.assertIsNone(l1)
        self.assertEqual(source, "no_interval_membership")
        self.assertTrue(industry_excluded)

        items = [
            {"symbol": "002189.SZ", "profitability_quality": 3.0, "industry_excluded": True},
            {"symbol": "000001.SZ", "profitability_quality": 1.0, "industry_l2": "801780.SI", "industry_l1": "801780.SI", "industry_excluded": False},
            {"symbol": "000002.SZ", "profitability_quality": 2.0, "industry_l2": "801780.SI", "industry_l1": "801780.SI", "industry_excluded": False},
        ]
        runner.percentile_scores(items, "profitability_quality", "profitability_quality__non_neutral")
        runner.add_industry_neutral_scores(items, "profitability_quality")

        excluded = next(item for item in items if item["symbol"] == "002189.SZ")
        included = next(item for item in items if item["symbol"] == "000002.SZ")
        self.assertIn("profitability_quality__non_neutral", excluded)
        self.assertNotIn("profitability_quality__industry_neutral", excluded)
        self.assertIn("profitability_quality__industry_neutral", included)

    def test_active_symbol_with_no_membership_source_still_hard_fails(self) -> None:
        context = runner.SignalContext(
            symbols=["000001.SZ"],
            active_symbols=["000001.SZ"],
            delisted_symbols=[],
            exception_symbols=set(),
            as_ofs=["20180131"],
            trade_dates=["20180131"],
            list_date_by_symbol={"000001.SZ": "19910403"},
            delist_date_by_symbol={"000001.SZ": None},
        )

        with self.assertRaisesRegex(ValueError, "no industry membership source"):
            runner.industry_context_for_symbol({}, context, "000001.SZ", "20180131")

    def test_decision_never_authorizes_production(self) -> None:
        results = [
            {
                "benchmark": "CSI300",
                "signal_family": "profitability_quality",
                "view": "non_neutral",
                "horizon_trading_days": 252,
                "passes_minimum_monthly_cohorts": True,
                "mean_monthly_cohort_net_excess": 0.02,
                "monthly_clustered_t_stat": 3.0,
                "bh_adjusted_p_value": 0.01,
                "top_symbol_selection_share": 0.1,
                "passes_name_concentration_guard": True,
                "passes_single_year_concentration_guard": True,
                "passes_drawdown_guard": True,
            },
            {
                "benchmark": "CSI1000",
                "signal_family": "profitability_quality",
                "view": "non_neutral",
                "horizon_trading_days": 252,
                "passes_minimum_monthly_cohorts": True,
                "mean_monthly_cohort_net_excess": 0.015,
                "monthly_clustered_t_stat": 2.5,
                "bh_adjusted_p_value": 0.02,
                "top_symbol_selection_share": 0.1,
                "passes_name_concentration_guard": True,
                "passes_single_year_concentration_guard": True,
                "passes_drawdown_guard": True,
            }
        ]

        decision = runner.decision_from_results(results)

        self.assertEqual(decision["research_verdict"], "candidate_alpha_clue_research_only")
        self.assertTrue(decision["secondary_benchmark_required_for_candidate_alpha"])
        self.assertFalse(decision["alpha_found_for_production"])
        self.assertFalse(decision["ship_gate_evidence"])
        self.assertFalse(decision["full_size_allowed"])
        self.assertIn("CSI1000", decision["size_exposure_caveat"])

    def test_decision_rejects_single_year_dominated_candidate(self) -> None:
        results = [
            {
                "benchmark": "CSI300",
                "signal_family": "profitability_quality",
                "view": "non_neutral",
                "horizon_trading_days": 252,
                "passes_minimum_monthly_cohorts": True,
                "mean_monthly_cohort_net_excess": 0.02,
                "monthly_clustered_t_stat": 3.0,
                "bh_adjusted_p_value": 0.01,
                "top_symbol_selection_share": 0.1,
                "passes_name_concentration_guard": True,
                "passes_single_year_concentration_guard": False,
                "passes_drawdown_guard": True,
            }
        ]

        decision = runner.decision_from_results(results)

        self.assertEqual(decision["research_verdict"], "no_alpha_found_under_frozen_rules")
        self.assertEqual(decision["candidate_alpha_clue_count"], 0)

    def test_decision_rejects_candidate_that_fails_drawdown_guard(self) -> None:
        results = [
            {
                "benchmark": "CSI300",
                "signal_family": "profitability_quality",
                "view": "non_neutral",
                "horizon_trading_days": 252,
                "passes_minimum_monthly_cohorts": True,
                "mean_monthly_cohort_net_excess": 0.02,
                "monthly_clustered_t_stat": 3.0,
                "bh_adjusted_p_value": 0.01,
                "top_symbol_selection_share": 0.1,
                "passes_name_concentration_guard": True,
                "passes_single_year_concentration_guard": True,
                "passes_drawdown_guard": False,
            },
            {
                "benchmark": "CSI1000",
                "signal_family": "profitability_quality",
                "view": "non_neutral",
                "horizon_trading_days": 252,
                "passes_minimum_monthly_cohorts": True,
                "mean_monthly_cohort_net_excess": 0.02,
                "monthly_clustered_t_stat": 3.0,
                "bh_adjusted_p_value": 0.01,
                "top_symbol_selection_share": 0.1,
                "passes_name_concentration_guard": True,
                "passes_single_year_concentration_guard": True,
                "passes_drawdown_guard": True,
            },
        ]

        decision = runner.decision_from_results(results)

        self.assertEqual(decision["research_verdict"], "no_alpha_found_under_frozen_rules")
        self.assertEqual(decision["candidate_alpha_clue_count"], 0)

    def test_decision_rejects_csi1000_only_candidate_alpha(self) -> None:
        results = [
            {
                "benchmark": "CSI1000",
                "signal_family": "profitability_quality",
                "view": "non_neutral",
                "horizon_trading_days": 252,
                "passes_minimum_monthly_cohorts": True,
                "mean_monthly_cohort_net_excess": 0.03,
                "monthly_clustered_t_stat": 3.0,
                "bh_adjusted_p_value": 0.01,
                "top_symbol_selection_share": 0.1,
                "passes_name_concentration_guard": True,
                "passes_single_year_concentration_guard": True,
                "passes_drawdown_guard": True,
            }
        ]

        decision = runner.decision_from_results(results)

        self.assertEqual(decision["research_verdict"], "no_alpha_found_under_frozen_rules")
        self.assertEqual(decision["candidate_alpha_clue_count"], 0)

    def test_decision_rejects_csi300_only_candidate_without_csi1000_robustness(self) -> None:
        results = [
            {
                "benchmark": "CSI300",
                "signal_family": "profitability_quality",
                "view": "non_neutral",
                "horizon_trading_days": 252,
                "passes_minimum_monthly_cohorts": True,
                "mean_monthly_cohort_net_excess": 0.03,
                "monthly_clustered_t_stat": 3.0,
                "bh_adjusted_p_value": 0.01,
                "top_symbol_selection_share": 0.1,
                "passes_name_concentration_guard": True,
                "passes_single_year_concentration_guard": True,
                "passes_drawdown_guard": True,
            }
        ]

        decision = runner.decision_from_results(results)

        self.assertEqual(decision["research_verdict"], "no_alpha_found_under_frozen_rules")
        self.assertEqual(decision["candidate_alpha_clue_count"], 0)

    def test_benchmark_route_amendment_accepts_blocked_tr_open_probe(self) -> None:
        summary = runner.load_and_validate_benchmark_route_amendment()

        self.assertEqual(summary["decision"]["benchmark_access_status"], "blocked_total_return_same_anchor_open_unavailable")

    def test_benchmark_route_amendment_rejects_probe_status_drift(self) -> None:
        summary = runner.read_json(runner.BENCHMARK_ACCESS_PROBE_SUMMARY_PATH)
        summary["decision"]["benchmark_access_status"] = "passed_total_return_same_anchor_open_available"
        summary["decision"]["selected_total_return_codes"] = {
            "CSI300": "H00300.CSI",
            "CSI1000": "H00852.CSI",
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "probe_summary.json"
            path.write_text(json.dumps(summary, ensure_ascii=False), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "blocked total-return-open probe"):
                runner.load_and_validate_benchmark_route_amendment(path)

    def test_delisted_symbol_leaves_scored_universe_after_delist_date(self) -> None:
        context = runner.SignalContext(
            symbols=["000666.SZ"],
            active_symbols=[],
            delisted_symbols=["000666.SZ"],
            exception_symbols=set(),
            as_ofs=["20230929", "20231026", "20231130"],
            trade_dates=["20230929", "20231026", "20231130"],
            list_date_by_symbol={"000666.SZ": "19961231"},
            delist_date_by_symbol={"000666.SZ": "20231026"},
        )

        self.assertTrue(runner.symbol_in_pit_scored_universe(context, "000666.SZ", "20230929"))
        self.assertFalse(runner.symbol_in_pit_scored_universe(context, "000666.SZ", "20231026"))
        self.assertFalse(runner.symbol_in_pit_scored_universe(context, "000666.SZ", "20231130"))

    def test_restatement_exclusion_keys_present_count_is_computed(self) -> None:
        payloads = {
            runner.call_id_for("income", "000001.SZ"): self._payload(
                [
                    {
                        "ts_code": "000001.SZ",
                        "ann_date": "20220430",
                        "f_ann_date": "20220430",
                        "end_date": "20211231",
                        "revenue": 100.0,
                    }
                ]
            ),
            runner.call_id_for("balancesheet", "000001.SZ"): self._payload([]),
            runner.call_id_for("cashflow", "000001.SZ"): self._payload([]),
            runner.call_id_for("fina_indicator", "000001.SZ"): self._payload([]),
        }
        store = audit_runner.PayloadStore(raw_root=Path("."), payloads=payloads)
        context = runner.SignalContext(
            symbols=["000001.SZ"],
            active_symbols=["000001.SZ"],
            delisted_symbols=[],
            exception_symbols=set(),
            as_ofs=[],
            trade_dates=[],
            list_date_by_symbol={"000001.SZ": "19910101"},
            delist_date_by_symbol={"000001.SZ": None},
        )

        count = runner.count_restatement_exclusion_keys_present(
            store,
            context,
            {("income", "000001.SZ", "20211231", "20220430")},
        )

        self.assertEqual(count, 1)

    def test_spend_ledger_after_success_updates_singleton_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ledger_path = Path(tmp) / "ledger.json"
            ledger = self._unspent_ledger_fixture()
            ledger_path.write_text(json.dumps(ledger, ensure_ascii=False), encoding="utf-8")
            summary = {
                "decision": {
                    "research_verdict": "no_alpha_found_under_frozen_rules",
                    "candidate_alpha_clue_count": 0,
                }
            }

            spent = runner.spend_ledger_after_success(
                ledger_path=ledger_path,
                summary=summary,
                result_ref="research/results/a_long_signal_search_20260604/execution_summary.json",
                generated_at="2026-06-06T00:00:00+00:00",
            )

        self.assertEqual(spent["ledger_status"], "active_no_new_test_authorized")
        self.assertEqual(spent["budget_policy"]["tests_spent_count"], 1)
        self.assertEqual(spent["planned_tests"], [])
        self.assertEqual(spent["test_spend_log"][0]["status"], "spent_failed_outcome_threshold")

    def _unspent_ledger_fixture(self) -> dict:
        ledger = copy.deepcopy(runner.read_json(runner.LEDGER_PATH))
        ledger["generated_at"] = "2026-06-04T00:00:00Z"
        ledger["ledger_status"] = "active_planned_test_pending_review"
        ledger["budget_policy"]["tests_spent_count"] = 0
        ledger["budget_policy"]["tests_available_without_new_review"] = 0
        ledger["test_spend_log"] = []
        if not ledger.get("planned_tests"):
            ledger["planned_tests"] = [
                {
                    "test_id": "a_long_signal_search_preregistration_20260604",
                    "planned_status": "planned_not_reviewed",
                    "created_at": "2026-06-04T00:00:00Z",
                    "planned_preregistration_ref": "research/preregistrations/a_long_signal_search_preregistration_20260604.json",
                    "planned_result_ref": "research/results/a_long_signal_search_20260604/evidence_report.json",
                    "promotion_relevant": True,
                    "expected_tests_spent": 1,
                    "approval_status": "pending_user_approval",
                    "design_summary": (
                        "Research-only A-long main-board quality / cashflow / balance-sheet / "
                        "earnings-stability signal search."
                    ),
                    "review_boundary": [
                        "No alpha, production, ship-gate, full-size, or broker / order automation authorization."
                    ],
                }
            ]
        return ledger

    def _payload(self, records: list[dict]) -> dict:
        columns = sorted({key for row in records for key in row})
        return {"records": records, "columns": columns}


if __name__ == "__main__":
    unittest.main()

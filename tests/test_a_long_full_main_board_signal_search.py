from __future__ import annotations

import csv
import copy
import json
import tempfile
import unittest
from pathlib import Path

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
        ledger = runner.load_and_validate_ledger()
        audit = runner.load_and_validate_audit_report()
        exclusions = runner.load_restatement_exclusions()

        self.assertEqual(prereg["artifact_id"], "a_long_signal_search_preregistration_20260604")
        self.assertEqual(ledger["budget_policy"]["tests_spent_count"], 0)
        self.assertEqual(audit["decision"]["audit_status"], "passed_full_main_board_data_integrity_for_signal_search")
        self.assertEqual(len(exclusions), runner.EXPECTED_RESTATEMENT_EXCLUSION_GROUP_COUNT)

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
                        "n_income_attr_p": 100.0,
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
                        "n_cashflow_act": 120.0,
                    }
                ]
            ),
            runner.call_id_for("fina_indicator", "000001.SZ"): self._payload(
                [
                    {"ts_code": "000001.SZ", "ann_date": "20220430", "end_date": "20211231", "roe": 10.0, "profit_dedt": 100.0},
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

    def test_compute_return_uses_same_anchor_and_cost(self) -> None:
        stock = {
            "20200102": {"open": 100.0, "close": 101.0},
            "20200103": {"open": 102.0, "close": 110.0},
        }
        index = {
            "20200102": {"open": 1000.0, "close": 1000.0},
            "20200103": {"open": 1000.0, "close": 1050.0},
        }

        stock_return, benchmark_return, entry, exit_ = runner.compute_return(
            stock,
            index,
            ["20200101", "20200102", "20200103"],
            "20200101",
            1,
        )

        self.assertEqual((entry, exit_), ("20200102", "20200103"))
        self.assertAlmostEqual(stock_return, 0.10 - runner.ROUND_TRIP_COST)
        self.assertAlmostEqual(benchmark_return, 0.05)

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
                    }
                )
                rows.append({**rows[-1], "horizon": 504})

        results = runner.summarize_results(rows)

        self.assertEqual(len(results), 16)
        self.assertTrue(all("bh_adjusted_p_value" in item for item in results))
        self.assertTrue(all("max_single_year_positive_return_share" in item for item in results))
        self.assertTrue(all("passes_single_year_concentration_guard" in item for item in results))
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

    def test_decision_never_authorizes_production(self) -> None:
        results = [
            {
                "passes_minimum_monthly_cohorts": True,
                "mean_monthly_cohort_net_excess": 0.02,
                "monthly_clustered_t_stat": 3.0,
                "bh_adjusted_p_value": 0.01,
                "top_symbol_selection_share": 0.1,
                "passes_name_concentration_guard": True,
                "passes_single_year_concentration_guard": True,
            }
        ]

        decision = runner.decision_from_results(results)

        self.assertEqual(decision["research_verdict"], "candidate_alpha_clue_research_only")
        self.assertFalse(decision["alpha_found_for_production"])
        self.assertFalse(decision["ship_gate_evidence"])
        self.assertFalse(decision["full_size_allowed"])

    def test_decision_rejects_single_year_dominated_candidate(self) -> None:
        results = [
            {
                "passes_minimum_monthly_cohorts": True,
                "mean_monthly_cohort_net_excess": 0.02,
                "monthly_clustered_t_stat": 3.0,
                "bh_adjusted_p_value": 0.01,
                "top_symbol_selection_share": 0.1,
                "passes_name_concentration_guard": True,
                "passes_single_year_concentration_guard": False,
            }
        ]

        decision = runner.decision_from_results(results)

        self.assertEqual(decision["research_verdict"], "no_alpha_found_under_frozen_rules")
        self.assertEqual(decision["candidate_alpha_clue_count"], 0)

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
            ledger = copy.deepcopy(runner.read_json(runner.LEDGER_PATH))
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

    def _payload(self, records: list[dict]) -> dict:
        columns = sorted({key for row in records for key in row})
        return {"records": records, "columns": columns}


if __name__ == "__main__":
    unittest.main()

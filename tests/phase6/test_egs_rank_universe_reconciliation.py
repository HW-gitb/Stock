import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from engine.a_short_loss_making_admission import (
    LOSS_MAKING_REASON,
    UNAVAILABLE_REASON,
    apply_loss_making_admission,
)
from runners.backtest_rank import load_eligible_universe

ROOT = Path(__file__).resolve().parents[2]
EGS_SCRIPT = ROOT / "A-EGS" / "egs_main.py"
DATA_HEALTH_SCHEMA = ROOT / "schemas" / "data_health.schema.json"


def _load_egs_module():
    old_argv = sys.argv[:]
    sys.argv = [str(EGS_SCRIPT), "--help"]
    try:
        spec = importlib.util.spec_from_file_location(
            "egs_main_rank_reconciliation_under_test",
            EGS_SCRIPT,
        )
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        return module
    finally:
        sys.argv = old_argv


def _frame(*codes):
    return pd.DataFrame({"ts_code": list(codes)})


def _feature_frame(*codes, total_mv=100.0, l1_name="行业A", l2_name="行业B"):
    return pd.DataFrame({
        "ts_code": list(codes),
        "name": [f"name-{code}" for code in codes],
        "l1_name": [l1_name] * len(codes),
        "l2_name": [l2_name] * len(codes),
        "total_mv": [total_mv] * len(codes),
        "pct_20d": [1.0] * len(codes),
        "avg_amount_20d": [1000.0] * len(codes),
    })


class RankUniverseReconciliationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.egs_main = _load_egs_module()

    def test_expected_l1_l2_exclusions_are_accounted_per_symbol(self) -> None:
        summary, detail = self.egs_main.build_rank_universe_reconciliation(
            df_l0=_frame("A", "B", "C", "D"),
            feature_source=_feature_frame("A", "B", "C", "D"),
            stages=[
                ("master_join", _frame("A", "B", "C", "D"), False, "master_join_loss"),
                ("l1_industry_leader", _frame("A", "C", "D"), True, "l1_industry_leader_elim"),
                ("l2_quality_risk", _frame("A", "D"), True, "l2_quality_or_risk_elim"),
                ("l5_rank", _frame("A", "D"), False, "l5_unexpected_row_loss"),
            ],
            sources={
                "financial_l0": (_frame("A", "B", "C", "D"), _frame("A", "B", "C", "D"), 1.0),
            },
        )

        self.assertEqual(summary["status"], "pass")
        self.assertEqual(summary["l0_count"], 4)
        self.assertEqual(summary["ranked_count"], 2)
        self.assertEqual(summary["expected_excluded_count"], 2)
        self.assertEqual(summary["unaccounted_count"], 0)
        self.assertEqual(len(detail), 4)
        by_code = detail.set_index("ts_code").to_dict("index")
        self.assertEqual(by_code["B"]["reason"], "l1_industry_leader_elim")
        self.assertEqual(by_code["C"]["reason"], "l2_quality_or_risk_elim")
        self.assertEqual(by_code["A"]["outcome"], "ranked")

    def test_loss_making_admission_partitions_pre_rank_without_rescoring(self) -> None:
        scored = pd.DataFrame([
            {"ts_code": "A", "ttm_profit_dedt": 10.0, "final_score": 100.0,
             "l4_score": 90.0, "pct_20d_n": 5.0, "tier": "Tier1",
             "l1_name": "L1-A", "l2_name": "L2-A", "pe_ttm": None, "q0_profit_dedt": -1.0},
            {"ts_code": "B", "ttm_profit_dedt": 0.0, "final_score": 99.0,
             "l4_score": 89.0, "pct_20d_n": 4.0, "tier": "Tier1",
             "l1_name": "L1-B", "l2_name": "L2-B", "pe_ttm": 20.0, "q0_profit_dedt": 2.0},
            {"ts_code": "C", "ttm_profit_dedt": 8.0, "final_score": 98.0,
             "l4_score": 88.0, "pct_20d_n": 3.0, "tier": "Tier1",
             "l1_name": "L1-C", "l2_name": "L2-C", "pe_ttm": None, "q0_profit_dedt": None},
            {"ts_code": "D", "ttm_profit_dedt": None, "final_score": 97.0,
             "l4_score": 87.0, "pct_20d_n": 2.0, "tier": "Tier1",
             "l1_name": "L1-D", "l2_name": "L2-D", "pe_ttm": 20.0, "q0_profit_dedt": 2.0},
        ])
        admitted, reasons, audit = apply_loss_making_admission(scored)

        pre = self.egs_main.select_profile_watch_pool(scored, top_n=15)
        post = pre[pre["ts_code"].isin(set(admitted["ts_code"]))]
        self.assertEqual(pre["ts_code"].tolist(), ["A", "B", "C", "D"])
        self.assertEqual(post["ts_code"].tolist(), ["A", "C"])
        self.assertEqual(reasons["B"], LOSS_MAKING_REASON)
        self.assertEqual(reasons["D"], UNAVAILABLE_REASON)
        self.assertEqual(audit.set_index("ts_code").loc["B", "pre_admission_rank"], 2)
        pd.testing.assert_frame_equal(
            admitted[["ts_code", "final_score", "tier"]].reset_index(drop=True),
            scored.loc[[0, 2], ["ts_code", "final_score", "tier"]].reset_index(drop=True),
        )

    def test_data_health_accepts_full_l5_artifact_when_admission_excludes_rows(self) -> None:
        scored = pd.DataFrame([
            {"ts_code": "A", "ttm_profit_dedt": 10.0, "final_score": 100.0,
             "l4_score": 90.0, "pct_20d_n": 5.0, "tier": "Tier1",
             "l1_name": "行业A", "l2_name": "行业B", "close": 10.0,
             "pe": 20.0, "pb": 2.0},
            {"ts_code": "B", "ttm_profit_dedt": 8.0, "final_score": 99.0,
             "l4_score": 89.0, "pct_20d_n": 4.0, "tier": "Tier1",
             "l1_name": "行业A", "l2_name": "行业B", "close": 11.0,
             "pe": 21.0, "pb": 2.1},
            {"ts_code": "C", "ttm_profit_dedt": 0.0, "final_score": 98.0,
             "l4_score": 88.0, "pct_20d_n": 3.0, "tier": "Tier1",
             "l1_name": "行业A", "l2_name": "行业B", "close": 12.0,
             "pe": 22.0, "pb": 2.2},
        ])
        admitted, reasons, _audit = apply_loss_making_admission(scored)
        summary, _detail = self.egs_main.build_rank_universe_reconciliation(
            df_l0=_frame("A", "B", "C"),
            feature_source=_feature_frame("A", "B", "C"),
            stages=[
                ("l5_rank", scored, False, "l5_unexpected_row_loss"),
                ("loss_making_admission", admitted, True, reasons),
            ],
            sources={},
        )
        analysis_input = {
            "schema_name": "analysis_input",
            "schema_version": self.egs_main.ANALYSIS_INPUT_SCHEMA_VERSION,
            "source": {
                "screening_engine_version": self.egs_main.EGS_VERSION,
                "data_provider": "tushare",
            },
            "candidates": [
                {"data_quality": {"completeness_score": 100}}
                for _ in range(len(admitted))
            ],
        }

        health = self.egs_main.build_data_health(
            df_full=scored,
            watch_df=admitted,
            tier1_final=admitted,
            analysis_input=analysis_input,
            latest_td="20260714",
            analysis_path=str(EGS_SCRIPT),
            snapshot_path=str(EGS_SCRIPT),
            candidates_path=str(EGS_SCRIPT),
            tier1_csv_path=str(EGS_SCRIPT),
            full_csv_path=str(EGS_SCRIPT),
            rank_reconciliation=summary,
        )

        self.assertEqual(summary["ranked_count"], 2)
        self.assertEqual(summary["expected_excluded_count"], 1)
        self.assertNotEqual(summary["ranked_count"], len(scored))
        self.assertEqual(health["metrics"]["full_count"], len(scored))
        self.assertNotIn(
            "rank_universe_reconciliation",
            {item["check"] for item in health["errors"]},
        )

    def test_admission_does_not_reselect_a_non_monotonic_pool(self) -> None:
        groups = [
            ("A", "A3"), ("A", "A2"), ("A", "A2"), ("B", "B2"), ("C", "C2"),
            ("A", "A1"), ("B", "B1"), ("B", "B2"), ("C", "C1"), ("C", "C2"),
            ("B", "B3"), ("A", "A3"), ("A", "A2"), ("A", "A1"), ("A", "A3"),
            ("C", "C1"), ("B", "B3"), ("A", "A2"), ("C", "C1"), ("C", "C1"),
            ("B", "B2"), ("C", "C1"), ("B", "B1"), ("C", "C1"), ("B", "B2"),
        ]
        scored = pd.DataFrame([
            {"ts_code": f"C{index:02d}", "ttm_profit_dedt": 0.0 if index == 3 else 1.0,
             "final_score": 100.0 - index, "l4_score": 90.0 - index,
             "pct_20d_n": 10.0 - index / 10.0, "tier": "Tier1",
             "l1_name": l1, "l2_name": l2}
            for index, (l1, l2) in enumerate(groups)
        ])
        admitted, _reasons, _audit = apply_loss_making_admission(scored)
        pre = self.egs_main.select_profile_watch_pool(scored, top_n=15)
        expected = pre[pre["ts_code"].isin(set(admitted["ts_code"]))]
        reselected = self.egs_main.select_profile_watch_pool(admitted, top_n=15)

        self.assertIn("C05", expected["ts_code"].tolist())
        self.assertNotIn("C05", reselected["ts_code"].tolist())
        self.assertEqual(expected["ts_code"].tolist(), [
            "C00", "C04", "C05", "C06", "C07", "C08", "C09", "C10",
            "C11", "C12", "C13", "C15", "C16", "C17",
        ])

    def test_production_gate_keeps_full_rank_artifact_and_filters_existing_pools(self) -> None:
        source = EGS_SCRIPT.read_text(encoding="utf-8")
        self.assertIn(
            "_pre_admission_top15 = select_profile_watch_pool(\n"
            "        watch_pool_eligible_frame(df_l5_scored), top_n=CONF[\"watch_n\"]\n"
            "    )",
            source,
        )
        self.assertIn(
            "top50 = _pre_selector_top[\n"
            "        _pre_selector_top[\"ts_code\"].astype(str).isin(_admitted_codes)\n"
            "    ].copy()",
            source,
        )
        self.assertIn("df_full = df_l5_scored", source)
        self.assertIn("watch_eligible_count = int(len(watch_df))", source)
        self.assertNotIn("watch_eligible_count = int(len(top50))", source)
        self.assertNotIn(
            "top50 = select_profile_watch_pool(\n"
            "        watch_pool_eligible_frame(df_full), top_n=CONF[\"top_n\"]\n"
            "    )",
            source,
        )

    def test_full_rank_writer_keeps_loss_row_for_backtest_eligible_consumer(self) -> None:
        with tempfile.TemporaryDirectory(dir=str(ROOT)) as tmp:
            source_root = Path(tmp)
            path = source_root / "_intermediate" / "egs_full_20260817.csv"
            full_rank = pd.DataFrame([
                {"ts_code": "LOSS.SZ", "tier": "Tier1", "final_score": 95.0,
                 "l4_score": 80.0, "pct_20d_n": 4.0},
                {"ts_code": "GOOD.SZ", "tier": "Tier1", "final_score": 90.0,
                 "l4_score": 79.0, "pct_20d_n": 3.0},
            ])
            self.egs_main.write_csv_atomic(full_rank, str(path), index=False)
            loaded = load_eligible_universe(source_root, ["20260817"])
            self.assertEqual(set(loaded["ts_code"]), {"LOSS.SZ", "GOOD.SZ"})

    def test_score_l1_records_the_exact_terminal_reason(self) -> None:
        frame = pd.DataFrame({
            "ts_code": ["A", "B"],
            "l2_name": ["行业A", "未知"],
            "pct_20d": [0.0, 0.0],
            "total_mv": [100.0, 100.0],
            "avg_amount_5d": [2e8, 2e8],
            "pe": [20.0, 20.0],
        })
        reasons = {}

        out = self.egs_main.score_l1(frame, csi300_ret=100.0, exclusion_reasons=reasons)

        self.assertTrue(out.empty)
        self.assertEqual(reasons["A"], "l1_industry_leader_elim")
        self.assertEqual(reasons["B"], "l1_unknown_industry_elim")

    def test_empty_frame_keeps_the_complete_l1_to_l5_contract(self) -> None:
        frame = pd.DataFrame(columns=[
            "ts_code", "name", "l1_name", "l2_name", "pct_20d",
            "total_mv", "avg_amount_5d", "has_crash_veto", "reduce_deduct",
        ])

        l1 = self.egs_main.score_l1(frame, csi300_ret=0.0)
        l2 = self.egs_main.score_l2(
            l1, pd.DataFrame(), [], {}, margin_observation=None
        )
        with patch.dict(self.egs_main.CONF, {"l3_mode": "neutralize"}):
            l3 = self.egs_main.score_l3(l2, [], pd.DataFrame())
        l4 = self.egs_main.score_l4(l3, pd.DataFrame())
        full, top = self.egs_main.score_l5(l4, {})

        self.assertTrue(full.empty)
        self.assertTrue(top.empty)
        self.assertTrue({
            "tier", "final_score", "l4_score", "pct_20d_n",
            "l1_name", "l2_name", "chasing_high", "overheat_flag",
            "downgrade_reasons",
        }.issubset(full.columns))
        self.assertEqual(str(full["chasing_high"].dtype), "boolean")
        self.assertEqual(str(full["overheat_flag"].dtype), "boolean")
        self.assertTrue({"close_n", "high_20d_n"}.issubset(l2.columns))
        self.assertEqual(str(l4["mom_rank"].dtype), "float64")
        self.assertEqual(str(l4["l4_mom_ok"].dtype), "Int64")
        self.assertEqual(str(l4["l4_rel_ok"].dtype), "Int64")
        self.assertEqual(str(l4["l4_score"].dtype), "Float64")
        self.assertEqual(str(l4["reduce_penalty"].dtype), "float64")

    def test_missing_momentum_stays_unknown_and_cannot_reach_tier1(self) -> None:
        frame = pd.DataFrame([{
            "ts_code": "600000.SH",
            "l1_name": "行业A",
            "l2_name": "行业B",
            "pct_20d_n": float("nan"),
            "pct_5d": float("nan"),
            "pct_60d": float("nan"),
            "drawdown_20d": float("nan"),
            "vol_confirm": True,
            "is_lock": False,
            "is_breakout": False,
            "esp_raw": 10.0,
            "l2_flags": "",
            "cat_score": 50.0,
            "cat_flag": "",
            "reduce_penalty": 0.0,
            "val_penalty": 0.0,
            "val_bonus": 0.0,
            "q0_dt_yoy": 10.0,
        }])

        l4 = self.egs_main.score_l4(frame, pd.DataFrame())

        self.assertTrue(pd.isna(l4.loc[0, "mom_rank"]))
        self.assertTrue(pd.isna(l4.loc[0, "l4_mom_ok"]))
        self.assertTrue(pd.isna(l4.loc[0, "chasing_high"]))
        self.assertTrue(pd.isna(l4.loc[0, "overheat_flag"]))

        full, _top = self.egs_main.score_l5(l4, {
            "600000.SH": {"l1_name": "行业A", "l2_name": "行业B"},
        })
        self.assertNotEqual(full.loc[0, "tier"], "Tier1")
        self.assertIn("momentum_history_unknown", full.loc[0, "downgrade_reasons"])

    def test_truncated_critical_source_fails_reconciliation(self) -> None:
        summary, _detail = self.egs_main.build_rank_universe_reconciliation(
            df_l0=_frame("A", "B", "C"),
            feature_source=_feature_frame("A", "B", "C"),
            stages=[
                ("master_join", _frame("A", "B", "C"), False, "master_join_loss"),
                ("l5_rank", _frame("A", "B", "C"), False, "l5_unexpected_row_loss"),
            ],
            sources={
                "financial_l0": (_frame("A", "B", "C"), _frame("A", "B"), 1.0),
            },
        )

        self.assertEqual(summary["status"], "fail")
        self.assertEqual(summary["source_coverage_failure_count"], 1)
        self.assertEqual(summary["source_coverage"]["financial_l0"]["missing_count"], 1)

    def test_unexpected_loss_in_scoring_only_stage_fails_reconciliation(self) -> None:
        summary, detail = self.egs_main.build_rank_universe_reconciliation(
            df_l0=_frame("A", "B"),
            feature_source=_feature_frame("A", "B"),
            stages=[
                ("master_join", _frame("A", "B"), False, "master_join_loss"),
                ("l3_scoring", _frame("A"), False, "l3_unexpected_row_loss"),
            ],
            sources={},
        )

        self.assertEqual(summary["status"], "fail")
        self.assertEqual(summary["unexpected_stage_change_count"], 1)
        by_code = detail.set_index("ts_code").to_dict("index")
        self.assertEqual(by_code["B"]["reason"], "l3_unexpected_row_loss")

    def _build_health(self, rank_reconciliation):
        ranked = pd.DataFrame({
            "ts_code": ["A", "B"],
            "tier": ["Tier1", "Tier1"],
            "close": [10.0, 11.0],
            "pe": [20.0, 21.0],
            "pb": [2.0, 2.1],
            "l1_name": ["行业A", "行业A"],
            "l2_name": ["行业B", "行业B"],
        })
        analysis_input = {
            "schema_name": "analysis_input",
            "schema_version": self.egs_main.ANALYSIS_INPUT_SCHEMA_VERSION,
            "source": {
                "screening_engine_version": self.egs_main.EGS_VERSION,
                "data_provider": "tushare",
            },
            "candidates": [
                {"data_quality": {"completeness_score": 100}},
                {"data_quality": {"completeness_score": 100}},
            ],
        }
        return self.egs_main.build_data_health(
            df_full=ranked,
            watch_df=ranked,
            tier1_final=ranked,
            analysis_input=analysis_input,
            latest_td="20260714",
            analysis_path=str(EGS_SCRIPT),
            snapshot_path=str(EGS_SCRIPT),
            candidates_path=str(EGS_SCRIPT),
            tier1_csv_path=str(EGS_SCRIPT),
            full_csv_path=str(EGS_SCRIPT),
            rank_reconciliation=rank_reconciliation,
        )

    def test_small_but_reconciled_rank_pool_does_not_trigger_legacy_1000_warning(self) -> None:
        summary, _detail = self.egs_main.build_rank_universe_reconciliation(
            df_l0=_frame("A", "B", "C"),
            feature_source=_feature_frame("A", "B", "C"),
            stages=[
                ("l1_industry_leader", _frame("A", "B"), True, "l1_industry_leader_elim"),
                ("l5_rank", _frame("A", "B"), False, "l5_unexpected_row_loss"),
            ],
            sources={"financial_l0": (_frame("A", "B", "C"), _frame("A", "B", "C"), 1.0)},
        )

        health = self._build_health(summary)

        self.egs_main.validate_json_schema(
            health,
            schema_path=str(DATA_HEALTH_SCHEMA),
            label="rank reconciliation health test",
        )
        self.assertNotIn("full_universe", {item["check"] for item in health["warnings"]})
        self.assertNotIn("rank_universe_reconciliation", {item["check"] for item in health["errors"]})

    def test_source_coverage_failure_is_a_data_health_error(self) -> None:
        summary, _detail = self.egs_main.build_rank_universe_reconciliation(
            df_l0=_frame("A", "B"),
            feature_source=_feature_frame("A", "B"),
            stages=[("l5_rank", _frame("A", "B"), False, "l5_unexpected_row_loss")],
            sources={"financial_l0": (_frame("A", "B"), _frame("A"), 1.0)},
        )

        health = self._build_health(summary)

        self.assertEqual(health["overall_status"], "error")
        self.assertIn("rank_source_coverage", {item["check"] for item in health["errors"]})

    def test_reconciled_empty_pool_is_a_warning_not_a_publish_error(self) -> None:
        empty = _frame()
        summary, _detail = self.egs_main.build_rank_universe_reconciliation(
            df_l0=_frame("A", "B"),
            feature_source=_feature_frame("A", "B"),
            stages=[
                ("master_join", _frame("A", "B"), False, "master_join_loss"),
                ("l1_industry_leader", empty, True, "l1_industry_leader_elim"),
                ("l5_rank", empty, False, "l5_unexpected_row_loss"),
            ],
            sources={"financial_l0": (_frame("A", "B"), _frame("A", "B"), 1.0)},
        )
        ranked = pd.DataFrame(columns=[
            "ts_code", "tier", "close", "pe", "pb", "l1_name", "l2_name",
        ])
        margin = {
            "reference_date": "20260714",
            "effective_ref_date": None,
            "row_count": 0,
            "universe_size": 0,
            "coverage_complete": False,
            "status": "unavailable",
        }
        analysis_input = {
            "schema_name": "analysis_input",
            "schema_version": self.egs_main.ANALYSIS_INPUT_SCHEMA_VERSION,
            "source": {
                "screening_engine_version": self.egs_main.EGS_VERSION,
                "data_provider": "tushare",
            },
            "market_context": {"margin_coverage": margin},
            "price_data_through": "20260714",
            "candidates": [],
        }

        health = self.egs_main.build_data_health(
            df_full=ranked,
            watch_df=ranked,
            tier1_final=ranked,
            analysis_input=analysis_input,
            latest_td="20260714",
            analysis_path=str(EGS_SCRIPT),
            snapshot_path=str(EGS_SCRIPT),
            candidates_path=str(EGS_SCRIPT),
            tier1_csv_path=str(EGS_SCRIPT),
            full_csv_path=str(EGS_SCRIPT),
            rank_reconciliation=summary,
            watch_eligible_count=0,
            short_history_candidate_count=2,
        )

        self.assertEqual(summary["status"], "pass")
        self.assertTrue(summary["accounting_balanced"])
        self.assertEqual(summary["l0_count"], 2)
        self.assertEqual(summary["expected_excluded_count"], 2)
        self.assertEqual(health["overall_status"], "warn")
        warning_checks = {item["check"] for item in health["warnings"]}
        error_checks = {item["check"] for item in health["errors"]}
        self.assertIn("empty_candidate_pool", warning_checks)
        self.assertIn("short_history_candidate_count", warning_checks)
        self.assertTrue({
            "full_universe", "watch_pool", "final_pool", "tier1_count",
        }.isdisjoint(error_checks))
        self.egs_main.validate_json_schema(
            health,
            schema_path=str(DATA_HEALTH_SCHEMA),
            label="reconciled empty pool health",
        )

        nonempty_full = pd.DataFrame({
            "ts_code": ["A"],
            "tier": ["Other"],
            "close": [10.0],
            "pe": [20.0],
            "pb": [2.0],
            "l1_name": ["行业A"],
            "l2_name": ["行业B"],
        })
        inconsistent_health = self.egs_main.build_data_health(
            df_full=nonempty_full,
            watch_df=ranked,
            tier1_final=ranked,
            analysis_input=analysis_input,
            latest_td="20260714",
            analysis_path=str(EGS_SCRIPT),
            snapshot_path=str(EGS_SCRIPT),
            candidates_path=str(EGS_SCRIPT),
            tier1_csv_path=str(EGS_SCRIPT),
            full_csv_path=str(EGS_SCRIPT),
            rank_reconciliation=summary,
            watch_eligible_count=0,
        )
        self.assertEqual(inconsistent_health["overall_status"], "error")
        self.assertNotIn(
            "empty_candidate_pool",
            {item["check"] for item in inconsistent_health["warnings"]},
        )

    def test_zero_l0_pool_is_an_error_and_never_an_empty_pool_warning(self) -> None:
        empty = _frame()
        summary, _detail = self.egs_main.build_rank_universe_reconciliation(
            df_l0=empty,
            feature_source=_feature_frame(),
            stages=[("l5_rank", empty, False, "l5_unexpected_row_loss")],
            sources={"financial_l0": (empty, empty, 1.0)},
        )
        ranked = pd.DataFrame(columns=[
            "ts_code", "tier", "close", "pe", "pb", "l1_name", "l2_name",
        ])
        analysis_input = {
            "schema_name": "analysis_input",
            "schema_version": self.egs_main.ANALYSIS_INPUT_SCHEMA_VERSION,
            "source": {
                "screening_engine_version": self.egs_main.EGS_VERSION,
                "data_provider": "tushare",
            },
            "candidates": [],
        }
        health = self.egs_main.build_data_health(
            df_full=ranked,
            watch_df=ranked,
            tier1_final=ranked,
            analysis_input=analysis_input,
            latest_td="20260714",
            analysis_path=str(EGS_SCRIPT),
            snapshot_path=str(EGS_SCRIPT),
            candidates_path=str(EGS_SCRIPT),
            tier1_csv_path=str(EGS_SCRIPT),
            full_csv_path=str(EGS_SCRIPT),
            rank_reconciliation=summary,
            watch_eligible_count=0,
        )

        self.assertEqual(health["overall_status"], "error")
        self.assertNotIn(
            "empty_candidate_pool",
            {item["check"] for item in health["warnings"]},
        )

    def test_feature_source_is_explicit_and_must_cover_post_l0_exactly(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "coverage mismatch"):
            self.egs_main.build_rank_universe_reconciliation(
                df_l0=_frame("A", "B"),
                feature_source=_feature_frame("A"),
                stages=[("l5_rank", _frame("A", "B"), False, "l5_unexpected_row_loss")],
                sources={},
            )

        duplicate_source = pd.concat([_feature_frame("A"), _feature_frame("A")], ignore_index=True)
        with self.assertRaisesRegex(RuntimeError, "duplicate ts_code"):
            self.egs_main.build_rank_universe_reconciliation(
                df_l0=_frame("A"),
                feature_source=duplicate_source,
                stages=[("l5_rank", _frame("A"), False, "l5_unexpected_row_loss")],
                sources={},
            )

    def test_production_call_binds_df_master_as_feature_source(self) -> None:
        source = EGS_SCRIPT.read_text(encoding="utf-8")
        call_start = source.index("rank_reconciliation, rank_reconciliation_detail = build_rank_universe_reconciliation(")
        call_end = source.index("    )", call_start)
        self.assertIn("feature_source=df_master", source[call_start:call_end])

    def test_feature_source_missing_required_column_fails_loudly(self) -> None:
        source = _feature_frame("A", "B").drop(columns=["l2_name"])
        with self.assertRaisesRegex(RuntimeError, "missing columns"):
            self.egs_main.build_rank_universe_reconciliation(
                df_l0=_frame("A", "B"),
                feature_source=source,
                stages=[("l5_rank", _frame("A", "B"), False, "l5_unexpected_row_loss")],
                sources={},
            )

    def test_crash_veto_member_quality_gaps_do_not_abort_publish(self) -> None:
        for source, label in (
            (_feature_frame("A", total_mv=None), "null total_mv"),
            (_feature_frame("A", l1_name="未知", l2_name="行业B"), "real L2 with unknown L1"),
        ):
            with self.subTest(label=label):
                summary, detail = self.egs_main.build_rank_universe_reconciliation(
                    df_l0=_frame("A"),
                    feature_source=source,
                    stages=[
                        ("master_join", _frame("A"), False, "master_join_loss"),
                        ("l2_quality_risk", _frame(), True, {"A": "l2_crash_veto"}),
                    ],
                    sources={},
                )
                self.assertEqual(summary["status"], "pass")
                row = detail.set_index("ts_code").loc["A"]
                self.assertEqual(row["reason"], "l2_crash_veto")
                self.assertIn("total_mv", detail.columns)
                self.assertIn("l1_name", detail.columns)
                self.assertIn("l2_name", detail.columns)


if __name__ == "__main__":
    unittest.main()

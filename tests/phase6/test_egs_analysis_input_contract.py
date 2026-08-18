import importlib.util
import inspect
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from engine.a_short_rule6_contract import RULE6_D_TIER_REASONS
from engine.data.analysis_input_contract import validate_analysis_input_contract
from runners.a_short_weekly_pipeline import _EXCL_REASON_META


ROOT = Path(__file__).resolve().parents[2]
EGS_SCRIPT = ROOT / "A-EGS" / "egs_main.py"


def _load_egs_module():
    old_argv = sys.argv[:]
    sys.argv = [str(EGS_SCRIPT), "--help"]
    try:
        spec = importlib.util.spec_from_file_location("egs_main_analysis_contract_under_test", EGS_SCRIPT)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        return module
    finally:
        sys.argv = old_argv


class EgsMainAnalysisInputContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.egs_main = _load_egs_module()

    def setUp(self) -> None:
        self._original_l3 = {
            "l3_mode": self.egs_main.CONF.get("l3_mode"),
            "l3_pit_strict": self.egs_main.CONF.get("l3_pit_strict"),
            "l3_snapshot_date": self.egs_main.CONF.get("l3_snapshot_date"),
            "l3_provider": self.egs_main.CONF.get("l3_provider"),
            "l3_coverage": self.egs_main.CONF.get("l3_coverage"),
        }
        self.egs_main.CONF["l3_provider"] = "legacy_tushare_snapshot"
        self.egs_main.CONF["l3_coverage"] = None
        self._original_health = dict(self.egs_main._LAST_HARD_VETO_SOURCE_HEALTH)
        self.egs_main._LAST_HARD_VETO_SOURCE_HEALTH = {
            name: {"status": "known_clear", "observed_at": "20260522"}
            for name in ("suspension", "unlock", "holder_reduction")
        }
        # This contract fixture must not inherit a prior module's in-memory
        # l3 reset; export schema validation requires a concrete mode.
        self.egs_main.CONF.update({
            "l3_mode": "pit",
            "l3_pit_strict": True,
            "l3_snapshot_date": "20260522",
        })

    def tearDown(self) -> None:
        self.egs_main.CONF.update(self._original_l3)
        self.egs_main._LAST_HARD_VETO_SOURCE_HEALTH = self._original_health

    def test_export_validates_analysis_input_before_write(self) -> None:
        self.egs_main.CONF["l3_mode"] = "pit"
        self.egs_main.CONF["l3_pit_strict"] = True
        self.egs_main.CONF["l3_snapshot_date"] = "20260523"

        with tempfile.TemporaryDirectory(dir=str(ROOT)) as tmp:
            with self.assertRaisesRegex(ValueError, "l3_snapshot_date"):
                self._export(tmp, latest_td="20260522")

    def test_exported_analysis_input_satisfies_contract(self) -> None:
        self.egs_main.CONF["l3_mode"] = "pit"
        self.egs_main.CONF["l3_pit_strict"] = True
        self.egs_main.CONF["l3_snapshot_date"] = "20260522"

        with tempfile.TemporaryDirectory(dir=str(ROOT)) as tmp:
            analysis_path, _snapshot_path, _candidates_path, payload = self._export(
                tmp,
                latest_td="20260522",
            )
            self.assertTrue(Path(analysis_path).exists())

        validate_analysis_input_contract(payload)

    def test_official_export_applies_the_same_strict_price_clock_contract(self) -> None:
        with tempfile.TemporaryDirectory(dir=str(ROOT)) as tmp:
            with patch.object(
                self.egs_main, "is_official_a_short_analysis_input_path", return_value=True
            ) as official_path:
                _analysis_path, _snapshot_path, _candidates_path, payload = self._export(
                    tmp,
                    latest_td="20260522",
                )

        official_path.assert_called_once()
        validate_analysis_input_contract(payload, official_input=True)

    def test_export_records_reconciled_l0_and_stage_exclusion_counts(self) -> None:
        self.egs_main.CONF["l3_mode"] = "pit"
        self.egs_main.CONF["l3_pit_strict"] = True
        self.egs_main.CONF["l3_snapshot_date"] = "20260522"
        reconciliation = {
            "l0_count": 3,
            "unexpected_stage_change_count": 0,
            "stage_counts": [
                {"stage": "l1_industry_leader", "excluded_count": 1},
                {"stage": "l2_quality_risk", "excluded_count": 1},
            ],
        }

        with tempfile.TemporaryDirectory(dir=str(ROOT)) as tmp:
            _analysis_path, _snapshot_path, _candidates_path, payload = self._export(
                tmp,
                latest_td="20260522",
                rank_reconciliation=reconciliation,
                l0_excluded_counts={"short_history_momentum": 2, "financial_data_unavailable": 1},
                unlock_set={"600001.SH"},
                red_dict={"unknown_codes": {"000002.SZ"}},
            )

        summary = payload["universe_summary"]
        self.assertEqual(summary["after_l0_count"], 3)
        self.assertNotIn("l1_industry_leader", summary["excluded_counts"])
        self.assertNotIn("l2_quality_risk", summary["excluded_counts"])
        self.assertNotIn("rank_unexpected", summary["excluded_counts"])
        self.assertEqual(summary["rank_exclusion_counts"]["l1_industry_leader"], 1)
        self.assertEqual(summary["rank_exclusion_counts"]["l2_quality_risk"], 1)
        self.assertEqual(summary["rank_exclusion_counts"]["rank_unexpected"], 0)
        self.assertEqual(summary["excluded_counts"]["short_history_momentum"], 2)
        self.assertEqual(summary["excluded_counts"]["financial_data_unavailable"], 1)
        self.assertEqual(summary["excluded_counts"]["unlock"], 0)
        self.assertEqual(summary["excluded_counts"]["unlock_uncomputable"], 1)
        self.assertEqual(summary["excluded_counts"]["holder_reduction_uncomputable"], 1)
        self.assertEqual(set(summary["excluded_counts"]), set(_EXCL_REASON_META))

    def test_current_schema_rejects_neutralized_l3_without_provider_binding(self) -> None:
        with tempfile.TemporaryDirectory(dir=str(ROOT)) as tmp:
            _analysis_path, _snapshot_path, _candidates_path, payload = self._export(
                tmp,
                latest_td="20260522",
            )
        payload["source"].update({
            "l3_mode": "neutralize",
            "l3_snapshot_date": None,
            "l3_provider": None,
            "l3_coverage": None,
            "data_provider": "tushare",
        })

        with self.assertRaisesRegex(Exception, "neutralized L3 requires provider"):
            validate_analysis_input_contract(payload)

    def test_export_marks_only_rule6_d_tier_as_manual_only(self) -> None:
        """The three unavailable checks are explicit human review, never silent passes."""
        with tempfile.TemporaryDirectory(dir=str(ROOT)) as tmp:
            _analysis_path, _snapshot_path, _candidates_path, payload = self._export(
                tmp, latest_td="20260522"
            )

        checks = {
            item["id"]: item
            for item in payload["candidates"][0]["event_risk"]["rule6_checks"]
        }
        self.assertEqual(set(RULE6_D_TIER_REASONS), {
            check_id for check_id, item in checks.items()
            if item["status"] == "not_applicable"
        })
        for check_id, reason in RULE6_D_TIER_REASONS.items():
            self.assertEqual(checks[check_id]["notes"], reason)
            self.assertEqual(checks[check_id]["severity"], "review")
        computed_without_this_export = {
            "rule6_holder_below_5pct", "rule6_50etf_iv", "rule6_cash_debt_double_high",
            "rule6_volume_stall", "rule6_margin_extreme_accumulation", "rule6_block_trade_discount",
            "rule6_short_selling_surge", "rule6_ar_growth_gt_revenue_growth",
        }
        for check_id in computed_without_this_export:
            self.assertEqual(checks[check_id]["status"], "unknown")
            self.assertEqual(checks[check_id]["severity"], "watch")

    def test_p4_stage3_snapshot_is_a_non_mutating_same_run_selection_receipt(self) -> None:
        rows = pd.DataFrame([{
            "ts_code": f"60000{i}.SH", "final_score": float(100 - i),
            "l1_name": f"L1-{i}", "l2_name": f"L2-{i}", "tier": "Tier1",
            "overheat_flag": False, "chasing_high": False,
        } for i in range(1, 7)])
        official = rows.iloc[:5].copy()
        with tempfile.TemporaryDirectory(dir=str(ROOT)) as tmp:
            path = self.egs_main.export_stage3_selection_snapshot(
                rows, official, "20260522", {"run_id": "a-short-20260522-probe", "candidate_digest": "a" * 64},
                {"veto_10d": {"600003.SH"}}, {"600004.SH"}, output_root=tmp)
            snapshot = json.loads(Path(path).read_text(encoding="utf-8"))
        self.assertEqual(snapshot["run_id"], "a-short-20260522-probe")
        self.assertEqual(snapshot["candidate_digest"], "a" * 64)
        self.assertIn("active_industry_weight_profile", snapshot)
        self.assertIn("screening_runtime_recipe", snapshot)
        self.assertEqual(set(snapshot["screening_runtime_recipe"]), {"policy_id", "schema_version", "path", "sha256"})
        self.assertEqual([row["ts_code"] for row in snapshot["top50"]], list(rows["ts_code"]))
        self.assertEqual([row["ts_code"] for row in snapshot["stage3_eligible_pool"]],
                         ["600001.SH", "600002.SH", "600005.SH", "600006.SH"])
        self.assertEqual([row["ts_code"] for row in snapshot["official_tier1_final"]], list(official["ts_code"]))
        self.assertTrue(snapshot["boundary"]["changes_official_top5"] is False)

    def test_p4_sidecar_failures_cannot_enter_formal_data_health(self) -> None:
        source = inspect.getsource(self.egs_main.run_egs)
        self.assertNotIn("comparison_sidecar_warnings.append(_p4_warning)", source)
        self.assertIn("P4a Stage3 overlay sidecar unavailable; formal EGS output unchanged", source)
        self.assertLess(source.index("with publish_context:"), source.index("with official_output_transaction([_p4_overlay_target]):"))

    def test_example_rule6_fixture_has_no_legacy_pending_status(self) -> None:
        fixture = json.loads((ROOT / "schemas" / "examples" / "analysis_input.example.json").read_text(encoding="utf-8"))
        checks = fixture["candidates"][0]["event_risk"]["rule6_checks"]
        statuses = {item["id"]: item["status"] for item in checks}
        self.assertNotIn("pending_data", statuses.values())
        self.assertNotIn("pending_llm", statuses.values())

    def test_real_egs_export_flows_through_weekly_main_without_rank_count_crash(self) -> None:
        """Run-1 #4 regression: actual EGS exporter contract -> weekly main, not two isolated unit fixtures."""
        from runners.a_short_weekly_pipeline import main as weekly_main

        as_of = "20260522"
        self.egs_main.CONF["l3_mode"] = "pit"
        self.egs_main.CONF["l3_pit_strict"] = True
        self.egs_main.CONF["l3_snapshot_date"] = as_of
        reconciliation = {
            "l0_count": 3,
            "unexpected_stage_change_count": 0,
            "stage_counts": [
                {"stage": "l1_industry_leader", "excluded_count": 601},
                {"stage": "l2_quality_risk", "excluded_count": 255},
            ],
        }
        feed = {
            "schema_name": "a_short_iv_feed", "schema_version": "1.1.0",
            "generated_at": "2026-05-22T15:30:00+08:00", "as_of": as_of,
            "underlying": "510050.SH",
            "params": {"risk_free": 0.02, "div_yield": 0.0,
                        "const_maturity_days": 30, "min_t_days": 5,
                        "roll_window": 252, "min_roll_obs": 60, "hv_window": 21},
            "n_days": 5,
            "series": [
                {"trade_date": day, "iv_value": 0.20 + i * 0.001,
                 "iv_percentile_252d": 50.0, "hv_value": 0.18 + i * 0.001}
                for i, day in enumerate(["20260518", "20260519", "20260520", "20260521", as_of])
            ],
            "boundary": {"production": False, "real_money": False,
                         "satisfies_ship_gate": False,
                         "iv_method": "bs_atm_constant_maturity_feasibility_grade"},
        }
        prices = [{"high": 10.2, "low": 9.8, "close": 10.0} for _ in range(30)]
        with tempfile.TemporaryDirectory(dir=str(ROOT)) as tmp:
            analysis_path, _snapshot_path, _candidates_path, payload = self._export(
                tmp, latest_td=as_of, rank_reconciliation=reconciliation)
            feed_path = Path(tmp) / "feed.json"
            out_path = Path(tmp) / "weekly.json"
            p4_root = Path(tmp) / "state" / "a_short" / "overlay_adjudication_private" / "v1"
            p4_summary = Path(tmp) / "p4-summary.json"
            p4_markdown = Path(tmp) / "p4-summary.md"
            feed_path.write_text(json.dumps(feed), encoding="utf-8")
            weekly_main(["--as-of", as_of, "--analysis-input", str(analysis_path),
                         "--iv-feed", str(feed_path), "--out", str(out_path), "--run-date", as_of,
                         "--overlay-adjudication-root", str(p4_root),
                         "--overlay-adjudication-public-json", str(p4_summary),
                         "--overlay-adjudication-public-markdown", str(p4_markdown)],
                        price_provider=lambda _code: prices)
            weekly = json.loads(out_path.read_text(encoding="utf-8"))
            self.assertTrue(out_path.exists())
        self.assertEqual(payload["universe_summary"]["rank_exclusion_counts"]["l1_industry_leader"], 601)
        self.assertNotIn("l1_industry_leader", payload["universe_summary"]["excluded_counts"])
        self.assertNotIn("exclusion_summary", weekly)  # no L0 count in this fixture; rank counts are not hard vetoes

    def test_p4_import_failure_cannot_fail_or_mutate_the_formal_weekly_output(self) -> None:
        """P4 is optional: even importing its sidecar must not change M6.7 publication."""
        from runners.a_short_weekly_pipeline import main as weekly_main

        as_of = "20260522"
        reconciliation = {"l0_count": 3, "unexpected_stage_change_count": 0, "stage_counts": []}
        feed = {
            "schema_name": "a_short_iv_feed", "schema_version": "1.1.0",
            "generated_at": "2026-05-22T15:30:00+08:00", "as_of": as_of,
            "underlying": "510050.SH",
            "params": {"risk_free": 0.02, "div_yield": 0.0,
                        "const_maturity_days": 30, "min_t_days": 5,
                        "roll_window": 252, "min_roll_obs": 60, "hv_window": 21},
            "n_days": 5, "series": [
            {"trade_date": day, "iv_value": 0.20, "iv_percentile_252d": 50.0, "hv_value": 0.18}
            for day in ["20260518", "20260519", "20260520", "20260521", as_of]
            ],
            "boundary": {"production": False, "real_money": False,
                         "satisfies_ship_gate": False,
                         "iv_method": "bs_atm_constant_maturity_feasibility_grade"},
        }
        prices = [{"high": 10.2, "low": 9.8, "close": 10.0} for _ in range(30)]
        with tempfile.TemporaryDirectory(dir=str(ROOT)) as tmp:
            analysis_path, _, _, _ = self._export(tmp, latest_td=as_of, rank_reconciliation=reconciliation)
            feed_path, out_path = Path(tmp) / "feed.json", Path(tmp) / "weekly.json"
            feed_path.write_text(json.dumps(feed), encoding="utf-8")
            p4_root = Path(tmp) / "state" / "a_short" / "overlay_adjudication_private" / "v1"
            with patch.dict(sys.modules, {"engine.a_short_overlay_adjudication": None}):
                weekly_main(["--as-of", as_of, "--analysis-input", str(analysis_path), "--iv-feed", str(feed_path),
                             "--out", str(out_path), "--run-date", as_of,
                             "--overlay-adjudication-root", str(p4_root)],
                            price_provider=lambda _code: prices)
            weekly = json.loads(out_path.read_text(encoding="utf-8"))
            self.assertTrue(out_path.exists())
            self.assertNotIn("overlay_adjudication", weekly)

    def test_ttm_profit_dedt_output_and_missing_path_preserve_contract(self) -> None:
        with tempfile.TemporaryDirectory(dir=str(ROOT)) as tmp:
            _analysis_path, _snapshot_path, _candidates_path, missing_payload = self._export(
                tmp,
                latest_td="20260522",
                row_overrides={"ttm_profit_dedt": None},
            )
        with tempfile.TemporaryDirectory(dir=str(ROOT)) as tmp:
            _analysis_path, _snapshot_path, _candidates_path, present_payload = self._export(
                tmp,
                latest_td="20260522",
                row_overrides={"ttm_profit_dedt": 130.0},
            )

        validate_analysis_input_contract(missing_payload)
        validate_analysis_input_contract(present_payload)
        missing_candidate = missing_payload["candidates"][0]
        present_candidate = present_payload["candidates"][0]
        self.assertIn(
            "fundamental.profitability.ttm_profit_dedt",
            missing_candidate["data_quality"]["missing_fields"],
        )
        self.assertNotIn(
            "fundamental.ttm_profit_dedt",
            missing_candidate["data_quality"]["missing_fields"],
        )
        self.assertNotIn(
            "fundamental.profitability.ttm_profit_dedt",
            present_candidate["data_quality"]["missing_fields"],
        )
        self.assertEqual(
            missing_candidate["data_quality"]["completeness_score"],
            present_candidate["data_quality"]["completeness_score"],
        )
        self.assertEqual(
            present_candidate["fundamental"]["profitability"]["ttm_profit_dedt"],
            130.0,
        )

    def _export(
        self,
        output_root: str,
        latest_td: str,
        rank_reconciliation=None,
        l0_excluded_counts=None,
        unlock_set=None,
        red_dict=None,
        row_overrides=None,
    ):
        row = {
            "ts_code": "600000.SH",
            "name": "Probe",
            "close": 10.0,
            "final_score": 80.0,
            "egs_base": 70.0,
            "esp_score": 50.0,
            "cat_score": 60.0,
            "l4_score": 100.0,
            "tier": "Tier1",
            "entry_flag": "可直接观察",
            "l2_name": "一般零售",
        }
        row.update(row_overrides or {})
        df = pd.DataFrame([row])
        with patch.object(
            self.egs_main,
            "_LAST_UNLOCK_DETAILS",
            {code: {"status": "unknown"} for code in (unlock_set or set())},
        ):
            return self.egs_main.export_analysis_input(
            df_full=df,
            watch_df=df,
            tier1_final=df,
            latest_td=latest_td,
            trade_dates=[latest_td],
            unlock_set=set(unlock_set or set()),
            suspended_set=set(),
            relisted_set=set(),
            red_dict=red_dict or {},
            tier1_csv_path=ROOT / "tier1.csv",
            full_csv_path=ROOT / "full.csv",
            output_root=output_root,
            rank_reconciliation=rank_reconciliation,
            l0_excluded_counts=l0_excluded_counts,
            trade_calendar_context={
                "decision_as_of": latest_td,
                "next_trade_date": None,
                "is_pre_holiday_window": False,
                "holiday_days_ahead": 0,
                "calendar_source": "tushare.trade_cal",
            },
            )


if __name__ == "__main__":
    unittest.main()

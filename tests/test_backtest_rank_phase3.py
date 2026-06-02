import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import unittest

import pandas as pd

from runners import backtest_rank
from runners.backtest_rank import _is_l2_unknown_value, attach_forward_returns, build_analyzer_ablation_variants


class BacktestRankPhase3Tests(unittest.TestCase):
    def test_l2_unknown_normalization_matches_analyzer(self):
        self.assertTrue(_is_l2_unknown_value("未知"))
        self.assertTrue(_is_l2_unknown_value(" unknown "))
        self.assertTrue(_is_l2_unknown_value("UNK"))
        self.assertFalse(_is_l2_unknown_value(""))
        self.assertFalse(_is_l2_unknown_value(None))
        self.assertFalse(_is_l2_unknown_value("专用设备"))

    def test_analyzer_ablation_variant_names_state_scope(self):
        samples = pd.DataFrame([
            {
                "tier": "Tier1",
                "entry_flag": "可直接观察",
                "l4_flag": "",
                "l2_name": "专用设备",
                "esp_raw": 10,
            },
            {
                "tier": "Tier1",
                "entry_flag": "可直接观察",
                "l4_flag": "",
                "l2_name": "专用设备",
                "esp_raw": -1,
            },
            {
                "tier": "Tier2",
                "entry_flag": "追高风险，周一确认",
                "l4_flag": "OVERHEAT",
                "l2_name": "专用设备",
                "esp_raw": 10,
            },
        ])

        variants = build_analyzer_ablation_variants(samples, analyzer_enabled=True)

        self.assertIn("all_analyzer_veto_all_rules", variants)
        self.assertIn("tier1_analyzer_veto_all_rules", variants)
        self.assertIn("all_analyzer_veto_chase_overheat", variants)
        self.assertIn("tier1_analyzer_veto_chase_overheat", variants)
        self.assertNotIn("analyzer_veto_all_rules", variants)
        self.assertEqual(len(variants["all_analyzer_veto_all_rules"]), 1)
        self.assertEqual(len(variants["tier1_analyzer_veto_all_rules"]), 1)
        self.assertEqual(len(variants["all_analyzer_veto_chase_overheat"]), 2)
        self.assertEqual(len(variants["tier1_analyzer_veto_chase_overheat"]), 2)

    def test_benchmark_excess_uses_benchmark_entry_open_to_exit_close(self):
        samples = pd.DataFrame([
            {
                "trade_date": "20260520",
                "ts_code": "000001.SZ",
                "close": 10.0,
                "name": "Ping An Bank",
                "board": "main",
            }
        ])
        stocks = pd.DataFrame([
            {"ts_code": "000001.SZ", "trade_date": "20260520", "open": 10.0, "close": 10.0, "adj_factor": 1.0},
            {"ts_code": "000001.SZ", "trade_date": "20260521", "open": 10.0, "close": 11.0, "adj_factor": 1.0},
            {"ts_code": "000001.SZ", "trade_date": "20260522", "open": 11.0, "close": 12.0, "adj_factor": 1.0},
            {"ts_code": "000001.SZ", "trade_date": "20260523", "open": 12.0, "close": 13.0, "adj_factor": 1.0},
            {"ts_code": "000001.SZ", "trade_date": "20260526", "open": 13.0, "close": 14.0, "adj_factor": 1.0},
            {"ts_code": "000001.SZ", "trade_date": "20260527", "open": 17.0, "close": 18.0, "adj_factor": 1.0},
        ])
        benchmarks = {
            "csi1000": pd.DataFrame([
                {"trade_date": "20260521", "open": 200.0, "close": 250.0},
                {"trade_date": "20260527", "open": 210.0, "close": 220.0},
            ]),
            "csi300": pd.DataFrame([
                {"trade_date": "20260521", "open": 4000.0, "close": 4100.0},
                {"trade_date": "20260527", "open": 4050.0, "close": 4200.0},
            ]),
        }

        out = attach_forward_returns(
            samples,
            [5],
            {"stocks": stocks, "limits": pd.DataFrame(), "benchmarks": benchmarks},
            cost_pct=0.16,
        )

        self.assertEqual(out.loc[0, "entry_date"], "20260521")
        self.assertEqual(out.loc[0, "ret_5d_exit_date"], "20260527")
        self.assertAlmostEqual(out.loc[0, "ret_5d_t1"], 80.0)
        self.assertAlmostEqual(out.loc[0, "ret_5d_csi1000"], 10.0)
        self.assertAlmostEqual(out.loc[0, "ret_5d_excess_csi1000"], 70.0)

    def test_benchmark_excess_does_not_fallback_to_close_only_benchmark(self):
        samples = pd.DataFrame([
            {
                "trade_date": "20260520",
                "ts_code": "000001.SZ",
                "close": 10.0,
                "name": "Ping An Bank",
                "board": "main",
            }
        ])
        stocks = pd.DataFrame([
            {"ts_code": "000001.SZ", "trade_date": "20260520", "open": 10.0, "close": 10.0, "adj_factor": 1.0},
            {"ts_code": "000001.SZ", "trade_date": "20260521", "open": 10.0, "close": 11.0, "adj_factor": 1.0},
            {"ts_code": "000001.SZ", "trade_date": "20260522", "open": 11.0, "close": 12.0, "adj_factor": 1.0},
            {"ts_code": "000001.SZ", "trade_date": "20260523", "open": 12.0, "close": 13.0, "adj_factor": 1.0},
            {"ts_code": "000001.SZ", "trade_date": "20260526", "open": 13.0, "close": 14.0, "adj_factor": 1.0},
            {"ts_code": "000001.SZ", "trade_date": "20260527", "open": 17.0, "close": 18.0, "adj_factor": 1.0},
        ])
        benchmarks = {
            "csi1000": pd.DataFrame([
                {"trade_date": "20260521", "close": 250.0},
                {"trade_date": "20260527", "close": 220.0},
            ]),
            "csi300": pd.DataFrame(columns=["trade_date", "open", "close"]),
        }

        out = attach_forward_returns(
            samples,
            [5],
            {"stocks": stocks, "limits": pd.DataFrame(), "benchmarks": benchmarks},
            cost_pct=0.16,
        )

        self.assertEqual(out.loc[0, "ret_5d_status"], "ok")
        self.assertAlmostEqual(out.loc[0, "ret_5d_t1"], 80.0)
        self.assertTrue(pd.isna(out.loc[0, "ret_5d_csi1000"]))
        self.assertTrue(pd.isna(out.loc[0, "ret_5d_excess_csi1000"]))

    def test_forward_return_conversion_failure_is_not_ok_status(self):
        samples = pd.DataFrame([
            {
                "trade_date": "20260520",
                "ts_code": "000001.SZ",
                "close": 10.0,
                "name": "Ping An Bank",
                "board": "main",
            }
        ])
        stocks = pd.DataFrame([
            {"ts_code": "000001.SZ", "trade_date": "20260520", "open": 10.0, "close": 10.0, "adj_factor": 1.0},
            {"ts_code": "000001.SZ", "trade_date": "20260521", "open": 10.0, "close": 11.0, "adj_factor": 1.0},
            {"ts_code": "000001.SZ", "trade_date": "20260522", "open": 11.0, "close": 12.0, "adj_factor": 1.0},
            {"ts_code": "000001.SZ", "trade_date": "20260523", "open": 12.0, "close": 13.0, "adj_factor": 1.0},
            {"ts_code": "000001.SZ", "trade_date": "20260526", "open": 13.0, "close": 14.0, "adj_factor": 1.0},
            {"ts_code": "000001.SZ", "trade_date": "20260527", "open": 17.0, "close": "bad-close", "adj_factor": 1.0},
        ])

        out = attach_forward_returns(
            samples,
            [5],
            {"stocks": stocks, "limits": pd.DataFrame(), "benchmarks": {}},
            cost_pct=0.16,
        )

        self.assertEqual(out.loc[0, "ret_5d_exit_date"], "20260527")
        self.assertEqual(out.loc[0, "ret_5d_status"], "pending_return_conversion_failed")
        self.assertTrue(pd.isna(out.loc[0, "ret_5d_close"]))
        self.assertTrue(pd.isna(out.loc[0, "ret_5d_t1_net"]))

    def test_missing_asof_bar_does_not_mix_close_to_close_adj_or_block_t1(self):
        samples = pd.DataFrame([
            {
                "trade_date": "20260520",
                "ts_code": "000001.SZ",
                "close": 10.0,
                "name": "Ping An Bank",
                "board": "main",
            }
        ])
        stocks = pd.DataFrame([
            {"ts_code": "999999.SZ", "trade_date": "20260520", "open": 1.0, "close": 1.0, "adj_factor": 1.0},
            {"ts_code": "000001.SZ", "trade_date": "20260521", "open": 10.0, "close": 11.0, "adj_factor": 2.0},
            {"ts_code": "000001.SZ", "trade_date": "20260522", "open": 11.0, "close": 12.0, "adj_factor": 2.0},
            {"ts_code": "000001.SZ", "trade_date": "20260523", "open": 12.0, "close": 13.0, "adj_factor": 2.0},
            {"ts_code": "000001.SZ", "trade_date": "20260526", "open": 13.0, "close": 14.0, "adj_factor": 2.0},
            {"ts_code": "000001.SZ", "trade_date": "20260527", "open": 17.0, "close": 18.0, "adj_factor": 2.0},
        ])

        out = attach_forward_returns(
            samples,
            [5],
            {"stocks": stocks, "limits": pd.DataFrame(), "benchmarks": {}},
            cost_pct=0.16,
        )

        self.assertEqual(out.loc[0, "ret_5d_status"], "ok")
        self.assertTrue(pd.isna(out.loc[0, "ret_5d_close"]))
        self.assertAlmostEqual(out.loc[0, "ret_5d_t1_net"], 79.84)

    def test_smoke_today_l3_generation_declares_live_l3_non_evidence_path(self):
        with TemporaryDirectory(dir=backtest_rank.ROOT) as tmp:
            with patch("runners.backtest_rank.subprocess.run") as run:
                backtest_rank.generate_candidates(
                    ["20260522"],
                    sys.executable,
                    output_root=Path(tmp),
                    skip_existing=False,
                    l3_mode="today",
                    allow_historical_live_l3=True,
                )

        cmd = run.call_args.args[0]
        self.assertIn("--l3-mode", cmd)
        self.assertIn("today", cmd)
        self.assertIn("--allow-historical-live-l3", cmd)

    def test_generation_does_not_declare_live_l3_when_not_requested(self):
        with TemporaryDirectory(dir=backtest_rank.ROOT) as tmp:
            with patch("runners.backtest_rank.subprocess.run") as run:
                backtest_rank.generate_candidates(
                    ["20260522"],
                    sys.executable,
                    output_root=Path(tmp),
                    skip_existing=False,
                    l3_mode="today",
                    allow_historical_live_l3=False,
                )

        cmd = run.call_args.args[0]
        self.assertNotIn("--allow-historical-live-l3", cmd)


if __name__ == "__main__":
    unittest.main()

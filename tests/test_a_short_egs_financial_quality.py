"""Focused 3.1 tests for the governed OCF quality gate."""
from __future__ import annotations

import importlib.util
import inspect
import sys
import unittest
from pathlib import Path

import pandas as pd

from engine.egs_industry_heat import final_score_and_tier


ROOT = Path(__file__).resolve().parents[1]
EGS_SCRIPT = ROOT / "A-EGS" / "egs_main.py"


def _load_egs_module():
    old_argv = sys.argv[:]
    sys.argv = [str(EGS_SCRIPT), "--help"]
    try:
        spec = importlib.util.spec_from_file_location(
            "egs_main_ocf_quality_gate_under_test", EGS_SCRIPT
        )
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        return module
    finally:
        sys.argv = old_argv


def _row(ts_code: str, *, ocf: float | None, ttm_profit: float | None = 1_000.0,
         pe: float = 10.0, q0_dt_yoy: float = 10.0) -> dict:
    return {
        "ts_code": ts_code,
        "l2_name": "test",
        "q0_dt_yoy": q0_dt_yoy,
        "q1_dt_yoy": 10.0,
        "pe": pe,
        "pb": 1.0,
        "roe": 10.0,
        "q0_dt_profit_ratio": 100.0,
        "ttm_profit_dedt": ttm_profit,
        "ttm_ocf_ratio": ocf,
        "pct_20d_n": 0.0,
        "reduce_deduct": 0.0,
        "avg_amount_5d": 1.0,
        "avg_amount_20d": 1.0,
    }


class OcfQualityGateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.egs = _load_egs_module()

    def _score(self, rows: list[dict], exclusion_reasons: dict | None = None):
        return self.egs.score_l2(
            pd.DataFrame(rows),
            pd.DataFrame(),
            [],
            {"test": 5.0},
            exclusion_reasons=exclusion_reasons,
            margin_observation=None,
        )

    def test_percentage_point_samples_use_the_unified_70_percent_gate(self):
        output = self._score([
            _row("LOW-43", ocf=43.8),
            _row("LOW-65", ocf=65.5),
            _row("PASS-90", ocf=90.0),
        ])
        flags = dict(zip(output["ts_code"], output["l2_flags"]))
        self.assertIn("ESP-Q", flags["LOW-43"])
        self.assertIn("ESP-Q", flags["LOW-65"])
        self.assertNotIn("ESP-Q", flags["PASS-90"])

    def test_ocf_gate_is_independent_of_ttm_profit_and_negative_ocf_still_hits(self):
        for ttm_profit in (-1.0, 0.0, 50.0, 1_000_000.0, None):
            with self.subTest(ttm_profit=ttm_profit):
                output = self._score([_row("LOW", ocf=50.0, ttm_profit=ttm_profit)])
                self.assertIn("ESP-Q", output.iloc[0]["l2_flags"])

        output = self._score([_row("NEGATIVE", ocf=-1.0, ttm_profit=None)])
        self.assertIn("ESP-Q", output.iloc[0]["l2_flags"])

    def test_espq_high_pe_and_peg_is_the_existing_hard_veto(self):
        reasons = {}
        rows = [_row("TARGET", ocf=50.0, pe=100.0)]
        rows.extend(_row(f"PEER-{index}", ocf=90.0, pe=1.0) for index in range(3))
        output = self._score(rows, exclusion_reasons=reasons)
        self.assertNotIn("TARGET", set(output["ts_code"]))
        self.assertEqual(reasons["TARGET"], "l2_espq_valuation_veto")

        no_high_pe = self._score([_row("TARGET", ocf=50.0, pe=10.0)] + [
            _row(f"PEER-{index}", ocf=90.0, pe=1.0) for index in range(3)
        ])
        self.assertIn("TARGET", set(no_high_pe["ts_code"]))

        no_peg = self._score([_row("TARGET", ocf=50.0, pe=100.0, q0_dt_yoy=60.0)] + [
            _row(f"PEER-{index}", ocf=90.0, pe=1.0) for index in range(3)
        ])
        self.assertIn("TARGET", set(no_peg["ts_code"]))

    def test_espq_has_one_existing_multiplier_without_duplicate_penalty(self):
        scored = self._score([_row("LOW", ocf=43.8)])
        scored["esp_score"] = 80.0
        scored["cat_score"] = 60.0
        scored["l4_score"] = 40.0
        scored["cat_flag"] = ""
        scored["val_bonus"] = 0.0
        scored["val_penalty"] = 0.0
        scored["reduce_penalty"] = 0.0
        output, _ = final_score_and_tier(
            scored, {"esp": 0.20, "cat": 0.30, "l4": 0.50, "industry_heat": 0.00}
        )
        self.assertEqual(output.iloc[0]["l2_flags"].count("ESP-Q"), 1)
        self.assertAlmostEqual(output.iloc[0]["egs_base"], 54.0)
        self.assertAlmostEqual(output.iloc[0]["mult"], 0.7)
        self.assertAlmostEqual(output.iloc[0]["final_score"], 37.8)
        self.assertAlmostEqual(output.iloc[0]["deduct"], 0.0)

    def test_ocf_gate_reads_policy_and_does_not_read_ttm_profit(self):
        source = inspect.getsource(self.egs.score_l2)
        self.assertIn('threshold_pct = CONF["ocf_quality_min_pct"]', source)
        self.assertIn("ttm_ocf_pct", source)
        self.assertNotIn("ttm_dt", source)
        self.assertNotIn("abs(ttm_dt)", source)


if __name__ == "__main__":
    unittest.main()

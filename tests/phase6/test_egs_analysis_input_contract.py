import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from engine.data.analysis_input_contract import validate_analysis_input_contract


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
        }
        self._original_health = dict(self.egs_main._LAST_HARD_VETO_SOURCE_HEALTH)
        self.egs_main._LAST_HARD_VETO_SOURCE_HEALTH = {
            name: {"status": "known_clear", "observed_at": "20260522"}
            for name in ("suspension", "unlock", "holder_reduction")
        }

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
            )

        summary = payload["universe_summary"]
        self.assertEqual(summary["after_l0_count"], 3)
        self.assertNotIn("l1_industry_leader", summary["excluded_counts"])
        self.assertNotIn("l2_quality_risk", summary["excluded_counts"])
        self.assertNotIn("rank_unexpected", summary["excluded_counts"])
        self.assertEqual(summary["rank_exclusion_counts"]["l1_industry_leader"], 1)
        self.assertEqual(summary["rank_exclusion_counts"]["l2_quality_risk"], 1)
        self.assertEqual(summary["rank_exclusion_counts"]["rank_unexpected"], 0)

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
            "as_of": as_of, "n_days": 5,
            "series": [
                {"trade_date": day, "iv_value": 0.20 + i * 0.001,
                 "iv_percentile_252d": 50.0, "hv_value": 0.18 + i * 0.001}
                for i, day in enumerate(["20260518", "20260519", "20260520", "20260521", as_of])
            ],
        }
        prices = [{"high": 10.2, "low": 9.8, "close": 10.0} for _ in range(30)]
        with tempfile.TemporaryDirectory(dir=str(ROOT)) as tmp:
            analysis_path, _snapshot_path, _candidates_path, payload = self._export(
                tmp, latest_td=as_of, rank_reconciliation=reconciliation)
            feed_path = Path(tmp) / "feed.json"
            out_path = Path(tmp) / "weekly.json"
            feed_path.write_text(json.dumps(feed), encoding="utf-8")
            weekly_main(["--as-of", as_of, "--analysis-input", str(analysis_path),
                         "--iv-feed", str(feed_path), "--out", str(out_path)],
                        price_provider=lambda _code: prices)
            weekly = json.loads(out_path.read_text(encoding="utf-8"))
            self.assertTrue(out_path.exists())
        self.assertEqual(payload["universe_summary"]["rank_exclusion_counts"]["l1_industry_leader"], 601)
        self.assertNotIn("l1_industry_leader", payload["universe_summary"]["excluded_counts"])
        self.assertNotIn("exclusion_summary", weekly)  # no L0 count in this fixture; rank counts are not hard vetoes

    def _export(self, output_root: str, latest_td: str, rank_reconciliation=None):
        df = pd.DataFrame([{
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
        }])
        return self.egs_main.export_analysis_input(
            df_full=df,
            watch_df=df,
            tier1_final=df,
            latest_td=latest_td,
            trade_dates=[latest_td],
            unlock_set=set(),
            suspended_set=set(),
            relisted_set=set(),
            red_dict={},
            tier1_csv_path=ROOT / "tier1.csv",
            full_csv_path=ROOT / "full.csv",
            output_root=output_root,
            rank_reconciliation=rank_reconciliation,
        )


if __name__ == "__main__":
    unittest.main()

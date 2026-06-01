import importlib.util
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

    def tearDown(self) -> None:
        self.egs_main.CONF.update(self._original_l3)

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

    def _export(self, output_root: str, latest_td: str):
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
        )


if __name__ == "__main__":
    unittest.main()

import importlib.util
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
EGS_SCRIPT = ROOT / "A-EGS" / "egs_main.py"


def _load_egs_module():
    old_argv = sys.argv[:]
    sys.argv = [str(EGS_SCRIPT), "--help"]
    try:
        spec = importlib.util.spec_from_file_location("egs_main_suspend_guard_under_test", EGS_SCRIPT)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        return module
    finally:
        sys.argv = old_argv


class EgsMainSuspendGuardTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.egs_main = _load_egs_module()

    def setUp(self) -> None:
        self.old_threshold = self.egs_main.CONF["suspend_daily_min_coverage"]
        self.egs_main.CONF["suspend_daily_min_coverage"] = 0.95

    def tearDown(self) -> None:
        self.egs_main.CONF["suspend_daily_min_coverage"] = self.old_threshold

    def test_partial_daily_response_rejects_suspend_inference(self) -> None:
        all_codes = {f"{i:06d}.SZ" for i in range(100)}
        partial_daily = pd.DataFrame({"ts_code": sorted(all_codes)[:90]})

        with self.assertRaisesRegex(RuntimeError, "suspend daily completeness too low"):
            self.egs_main._validated_suspend_traded_codes(
                partial_daily,
                all_codes,
                "20260529",
            )

    def test_valid_daily_response_returns_only_missing_codes_as_suspended(self) -> None:
        all_codes = [f"{i:06d}.SZ" for i in range(100)]
        traded = all_codes[:98]
        stock_list = pd.DataFrame({"ts_code": all_codes})
        daily = pd.DataFrame({"ts_code": traded})
        saved = {}

        def fake_safe_api(_fn, *args, **kwargs):
            return daily

        def fake_save_cache(key, value):
            saved[key] = value

        self.egs_main.pro = SimpleNamespace(daily=lambda **kwargs: pd.DataFrame())
        with patch.object(self.egs_main, "load_cache", return_value=None), \
             patch.object(self.egs_main, "save_cache", side_effect=fake_save_cache), \
             patch.object(self.egs_main, "get_stock_list", return_value=stock_list), \
             patch.object(self.egs_main, "safe_api", side_effect=fake_safe_api):
            suspended = self.egs_main.get_suspend_info(["20260529", "20260528", "20260527"])

        self.assertEqual(suspended, set(all_codes[98:]))
        self.assertEqual(saved["suspend_20260529_v2"], set(all_codes[98:]))

    def test_empty_daily_responses_still_skip_suspend_filter(self) -> None:
        stock_list = pd.DataFrame({"ts_code": ["000001.SZ", "000002.SZ"]})
        saved = {}

        def fake_safe_api(_fn, *args, **kwargs):
            return pd.DataFrame()

        def fake_save_cache(key, value):
            saved[key] = value

        self.egs_main.pro = SimpleNamespace(daily=lambda **kwargs: pd.DataFrame())
        with patch.object(self.egs_main, "load_cache", return_value=None), \
             patch.object(self.egs_main, "save_cache", side_effect=fake_save_cache), \
             patch.object(self.egs_main, "get_stock_list", return_value=stock_list), \
             patch.object(self.egs_main, "safe_api", side_effect=fake_safe_api):
            suspended = self.egs_main.get_suspend_info(["20260529", "20260528", "20260527"])

        self.assertEqual(suspended, set())
        self.assertEqual(saved["suspend_20260529_v2"], set())


if __name__ == "__main__":
    unittest.main()

"""Offline contract tests for the pinned A-short Tushare client."""
from __future__ import annotations

import os
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runners import backtest_rank  # noqa: E402


def _fake_tushare(*, version: str, has_endpoint_attribute: bool):
    class DataApi:
        pass

    if has_endpoint_attribute:
        setattr(DataApi, "_DataApi__http_url", "https://old.invalid/dataapi")

    tushare = types.ModuleType("tushare")
    tushare.__version__ = version
    tushare.pro = types.SimpleNamespace(client=types.SimpleNamespace(DataApi=DataApi))
    tushare.pro_api = mock.Mock(return_value=object())
    pro = types.ModuleType("tushare.pro")
    client = types.ModuleType("tushare.pro.client")
    client.DataApi = DataApi
    return tushare, {
        "tushare": tushare,
        "tushare.pro": pro,
        "tushare.pro.client": client,
    }


class TushareRuntimeContractTests(unittest.TestCase):
    def test_backtest_rejects_unpinned_tushare_before_client_creation(self):
        tushare, modules = _fake_tushare(version="9.9.9", has_endpoint_attribute=True)
        with mock.patch.dict(sys.modules, modules), mock.patch.dict(
            os.environ, {"TUSHARE_TOKEN": "masked-test-token"}
        ):
            with self.assertRaisesRegex(RuntimeError, "tushare==1.4.29"):
                backtest_rank._tushare_pro()
        tushare.pro_api.assert_not_called()

    def test_backtest_rejects_private_endpoint_shape_drift_before_client_creation(self):
        tushare, modules = _fake_tushare(version="1.4.29", has_endpoint_attribute=False)
        with mock.patch.dict(sys.modules, modules), mock.patch.dict(
            os.environ, {"TUSHARE_TOKEN": "masked-test-token"}
        ):
            with self.assertRaisesRegex(RuntimeError, "_DataApi__http_url"):
                backtest_rank._tushare_pro()
        tushare.pro_api.assert_not_called()

    def test_requirements_and_production_callers_share_the_pinned_initializer(self):
        self.assertIn("tushare==1.4.29", (ROOT / "requirements-a-short.txt").read_text(encoding="utf-8"))
        callers = [
            ROOT / "A-EGS" / "egs_main.py",
            ROOT / "runners" / "backtest_rank.py",
            ROOT / "runners" / "materialize_execution_price_data_tushare.py",
            ROOT / "runners" / "a_short_iv_feed_probe.py",
        ]
        for path in callers:
            source = path.read_text(encoding="utf-8")
            self.assertIn("init_tushare_pro", source, path)
            self.assertNotIn("_DataApi__http_url", source, path)


if __name__ == "__main__":
    unittest.main()

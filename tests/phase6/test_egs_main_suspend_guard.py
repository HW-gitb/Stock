import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd
from jsonschema import Draft7Validator


ROOT = Path(__file__).resolve().parents[2]
EGS_SCRIPT = ROOT / "A-EGS" / "egs_main.py"
DATA_HEALTH_SCHEMA = ROOT / "schemas" / "data_health.schema.json"


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
        self.old_log_dir = self.egs_main.LOG_DIR
        self.tmp_log_dir = tempfile.TemporaryDirectory()
        self.egs_main.LOG_DIR = self.tmp_log_dir.name
        self.egs_main.CONF["suspend_daily_min_coverage"] = 0.95
        self.egs_main._LAST_SUSPEND_DAILY_COVERAGE_OBSERVATION = None

    def tearDown(self) -> None:
        self.egs_main.CONF["suspend_daily_min_coverage"] = self.old_threshold
        self.egs_main.LOG_DIR = self.old_log_dir
        self.egs_main._LAST_SUSPEND_DAILY_COVERAGE_OBSERVATION = None
        self.tmp_log_dir.cleanup()

    def test_partial_daily_response_rejects_suspend_inference(self) -> None:
        all_codes = {f"{i:06d}.SZ" for i in range(100)}
        partial_daily = pd.DataFrame({"ts_code": sorted(all_codes)[:90]})

        with self.assertRaisesRegex(RuntimeError, "suspend daily completeness too low"):
            self.egs_main._validated_suspend_traded_codes(
                partial_daily,
                all_codes,
                "20260529",
            )

        payload = json.loads((Path(self.tmp_log_dir.name) / "suspend_daily_coverage_20260529.json").read_text(encoding="utf-8"))
        self.assertEqual(payload["status"], "fail_low_coverage")
        self.assertEqual(payload["stock_universe_count"], 100)
        self.assertEqual(payload["traded_in_universe_count"], 90)
        self.assertAlmostEqual(payload["coverage_ratio"], 0.90)
        self.assertAlmostEqual(payload["min_coverage"], 0.95)

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
        self.assertEqual(saved["suspend_20260529_v3"]["members"], sorted(all_codes[98:]))
        self.assertEqual(saved["suspend_20260529_v3"]["status"], "known_hit")
        payload = json.loads((Path(self.tmp_log_dir.name) / "suspend_daily_coverage_20260529.json").read_text(encoding="utf-8"))
        self.assertEqual(payload["status"], "pass")
        self.assertEqual(payload["trade_date"], "20260529")
        self.assertEqual(payload["daily_payload_row_count"], 98)
        self.assertEqual(payload["suspended_count"], 2)
        self.assertAlmostEqual(payload["coverage_ratio"], 0.98)
        self.assertEqual(
            self.egs_main._current_suspend_daily_coverage_observation()["status"],
            "pass",
        )

    def test_empty_daily_responses_block_suspend_filter(self) -> None:
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
            with self.assertRaisesRegex(RuntimeError, "suspend source unavailable"):
                self.egs_main.get_suspend_info(["20260529", "20260528", "20260527"])

        self.assertNotIn("suspend_20260529_v3", saved)
        payload = json.loads((Path(self.tmp_log_dir.name) / "suspend_daily_coverage_20260529.json").read_text(encoding="utf-8"))
        self.assertEqual(payload["status"], "no_daily_payload_blocked")
        self.assertEqual(payload["stock_universe_count"], 2)
        self.assertEqual(payload["attempted_trade_dates"], ["20260529", "20260528", "20260527"])

    def test_data_health_includes_latest_suspend_coverage_observation(self) -> None:
        self.egs_main._record_suspend_daily_coverage_observation(
            as_of="20260529",
            trade_date="20260529",
            status="pass",
            stock_universe_count=100,
            daily_payload_row_count=98,
            traded_in_universe_count=98,
            suspended_count=2,
            coverage_ratio=0.98,
            min_coverage=0.95,
            attempted_trade_dates=["20260529"],
        )
        watch_df = pd.DataFrame({
            "tier": ["Tier1"],
            "close": [10.0],
            "pe": [20.0],
            "pb": [2.0],
            "l1_name": ["行业A"],
            "l2_name": ["行业B"],
        })
        analysis_input = {
            "schema_name": "analysis_input",
            "schema_version": self.egs_main.ANALYSIS_INPUT_SCHEMA_VERSION,
            "source": {
                "screening_engine_version": self.egs_main.EGS_VERSION,
                "data_provider": "tushare",
            },
            "market_context": {
                "margin_coverage": {
                    "reference_date": None, "effective_ref_date": None,
                    "row_count": 0, "universe_size": 0,
                    "coverage_complete": False, "status": "unavailable",
                },
            },
            "candidates": [{"data_quality": {"completeness_score": 100}}],
        }

        health = self.egs_main.build_data_health(
            df_full=watch_df,
            watch_df=watch_df,
            tier1_final=watch_df,
            analysis_input=analysis_input,
            latest_td="20260529",
            analysis_path=str(EGS_SCRIPT),
            snapshot_path=str(EGS_SCRIPT),
            candidates_path=str(EGS_SCRIPT),
            tier1_csv_path=str(EGS_SCRIPT),
            full_csv_path=str(EGS_SCRIPT),
        )

        self.assertEqual(health["metrics"]["suspend_daily_coverage"]["status"], "pass")
        self.assertAlmostEqual(
            health["metrics"]["suspend_daily_coverage"]["coverage_ratio"],
            0.98,
        )
        self.assertEqual(health["schema_version"], "1.11.0")
        schema = json.loads(DATA_HEALTH_SCHEMA.read_text(encoding="utf-8"))
        Draft7Validator.check_schema(schema)
        self.assertEqual(schema["properties"]["schema_version"]["const"], "1.11.0")
        self.assertFalse(list(Draft7Validator(schema).iter_errors(health)))

    def test_export_data_health_validates_schema_before_write(self) -> None:
        invalid_health = {
            "schema_name": "data_health",
            "schema_version": "1.11.0",
            "generated_at": "2026-06-01T00:00:00+08:00",
            "trade_date": "20260529",
            "preset": "a_short",
            "market": "A",
            "source": {
                "screening_engine": "egs_main.py",
                "screening_engine_version": self.egs_main.EGS_VERSION,
                "data_provider": "tushare",
                "api_families": ["daily"],
                "l3_mode": "today",
                "l3_pit_strict": False,
            },
            "overall_status": "ok",
            "errors": [],
            "warnings": [],
            "metrics": {
                "full_count": 1,
                "watch_count": 1,
                "final_count": 1,
                "tier1_count": 1,
                "close_missing_or_nonpositive_count": 0,
                "pe_ttm_or_pe_missing_count": 0,
                "pb_missing_count": 0,
                "watch_l1_unknown_count": 0,
                "watch_l2_unknown_count": 0,
                "full_l2_unknown_count": 0,
                "short_history_candidate_count": 0,
                "watch_pool_reconciliation": {
                    "status": "pass",
                    "reason": "eligible_pool_exhausted",
                    "target_count": 15,
                    "eligible_count": 1,
                    "expected_count": 1,
                    "actual_count": 1,
                    "shortfall_count": 14,
                },
                "sw_industry_membership": self.egs_main._sw_industry_source_not_observed(),
                "rank_universe_reconciliation": self.egs_main._rank_reconciliation_not_observed(),
                "suspend_daily_coverage": {
                    "schema_name": "suspend_daily_coverage_log",
                    "schema_version": "1.0.0",
                    "status": "not_observed",
                },
                "moneyflow_coverage": {
                    "reference_date": "20260529",
                    "effective_ref_date": None,
                    "lag_sessions": None,
                    "fallback_applied": False,
                    "fallback_reason": None,
                    "requested_trade_dates": [],
                    "observed_trade_dates": [],
                    "row_count": 0,
                    "universe_size": 0,
                    "target_universe_size": 0,
                    "target_complete_count": 0,
                    "coverage_complete": False,
                    "status": "unavailable",
                },
                "completeness_score_min": 100,
                "completeness_score_below_95_count": 0,
                "completeness_score_below_75_count": 0,
                "unexpected_metric": 1,
            },
            "outputs_checked": {},
            "limitations": [],
        }
        with tempfile.TemporaryDirectory() as tmp:
            analysis_path = Path(tmp) / "analysis_input.json"
            with patch.object(self.egs_main, "build_data_health", return_value=invalid_health):
                with self.assertRaisesRegex(ValueError, "unexpected_metric"):
                    self.egs_main.export_data_health(
                        df_full=pd.DataFrame(),
                        watch_df=pd.DataFrame(),
                        tier1_final=pd.DataFrame(),
                        analysis_input={},
                        latest_td="20260529",
                        analysis_path=str(analysis_path),
                        snapshot_path=str(Path(tmp) / "snapshot.json"),
                        candidates_path=str(Path(tmp) / "candidates.csv"),
                        tier1_csv_path=str(Path(tmp) / "tier1.csv"),
                        full_csv_path=str(Path(tmp) / "full.csv"),
                    )
            self.assertFalse((Path(tmp) / "data_health.json").exists())


if __name__ == "__main__":
    unittest.main()

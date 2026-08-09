import importlib.util
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
EGS_SCRIPT = ROOT / "A-EGS" / "egs_main.py"
DATA_HEALTH_SCHEMA = ROOT / "schemas" / "data_health.schema.json"


def _load_egs_module():
    old_argv = sys.argv[:]
    sys.argv = [str(EGS_SCRIPT), "--help"]
    try:
        spec = importlib.util.spec_from_file_location(
            "egs_main_sw_watch_health_under_test",
            EGS_SCRIPT,
        )
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        return module
    finally:
        sys.argv = old_argv


def _safe_call(fn, *args, **kwargs):
    kwargs.pop("default", None)
    kwargs.pop("retries", None)
    return fn(*args, **kwargs)


def _classifications():
    l1 = pd.DataFrame({
        "index_code": ["801000.SI"],
        "industry_code": ["801000"],
        "industry_name": ["一级行业"],
    })
    l2 = pd.DataFrame({
        "index_code": ["801010.SI", "801020.SI"],
        "industry_name": ["二级甲", "二级乙"],
        "parent_code": ["801000", "801000"],
    })
    return l1, l2


def _canonical_members():
    return pd.DataFrame({
        "con_code": ["000001.SZ", "000002.SZ"],
        "index_code": ["801010.SI", "801020.SI"],
        "in_date": ["20200101", "20200101"],
        "out_date": ["", ""],
    })


class SwIndustrySourceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.egs_main = _load_egs_module()

    def setUp(self) -> None:
        self.old_today = self.egs_main.TODAY
        self.old_min = self.egs_main.SW_INDUSTRY_MIN_ACTIVE
        self.egs_main.SW_INDUSTRY_MIN_ACTIVE = 2
        self.egs_main._LAST_SW_INDUSTRY_SOURCE_OBSERVATION = None

    def tearDown(self) -> None:
        self.egs_main.TODAY = self.old_today
        self.egs_main.SW_INDUSTRY_MIN_ACTIVE = self.old_min
        self.egs_main._LAST_SW_INDUSTRY_SOURCE_OBSERVATION = None

    def test_current_run_uses_l1_fast_path_and_normalizes_official_aliases(self) -> None:
        l1, l2 = _classifications()
        calls = []

        def index_classify(*, level):
            return l1 if level == "L1" else l2

        def index_member_all(**kwargs):
            calls.append(kwargs)
            return pd.DataFrame({
                "ts_code": ["000001.SZ", "000002.SZ"],
                "l2_code": ["801010.SI", "801020.SI"],
                "in_date": ["20200101", "20200101"],
                "out_date": ["", ""],
                "is_new": ["Y", "Y"],
            })

        def index_member(**_kwargs):
            raise AssertionError("current complete fast path must not call L2 fallback")

        self.egs_main.TODAY = self.egs_main.datetime.now().strftime("%Y%m%d")
        self.egs_main.pro = SimpleNamespace(
            index_classify=index_classify,
            index_member_all=index_member_all,
            index_member=index_member,
        )
        with patch.object(self.egs_main, "load_cache", return_value=None), \
             patch.object(self.egs_main, "save_cache"), \
             patch.object(self.egs_main, "safe_api", side_effect=_safe_call):
            mapping = self.egs_main.get_sw_industry_map()

        self.assertEqual(set(mapping), {"000001.SZ", "000002.SZ"})
        self.assertEqual(calls[0]["l1_code"], "801000.SI")
        self.assertEqual(calls[0]["is_new"], "Y")
        observation = self.egs_main._current_sw_industry_source_observation()
        self.assertEqual(observation["status"], "pass")
        self.assertEqual(observation["source"], "index_member_all_l1_current")
        self.assertEqual(observation["request_group_count"], 1)
        self.assertTrue(observation["fast_path_used"])
        self.assertFalse(observation["fallback_used"])

    def test_fast_path_limit_hit_falls_back_instead_of_accepting_truncation(self) -> None:
        l1, l2 = _classifications()
        limited = pd.DataFrame({
            "ts_code": ["000001.SZ"] * 2000,
            "l2_code": ["801010.SI"] * 2000,
            "in_date": ["20200101"] * 2000,
            "out_date": [""] * 2000,
        })

        def index_classify(*, level):
            return l1 if level == "L1" else l2

        def index_member_all(**_kwargs):
            return limited

        canonical = _canonical_members().set_index("index_code")

        def index_member(*, index_code, **_kwargs):
            return canonical.loc[[index_code]].reset_index()

        self.egs_main.TODAY = self.egs_main.datetime.now().strftime("%Y%m%d")
        self.egs_main.pro = SimpleNamespace(
            index_classify=index_classify,
            index_member_all=index_member_all,
            index_member=index_member,
        )
        with patch.object(self.egs_main, "load_cache", return_value=None), \
             patch.object(self.egs_main, "save_cache"), \
             patch.object(self.egs_main, "safe_api", side_effect=_safe_call):
            mapping = self.egs_main.get_sw_industry_map()

        self.assertEqual(set(mapping), {"000001.SZ", "000002.SZ"})
        observation = self.egs_main._current_sw_industry_source_observation()
        self.assertEqual(observation["source"], "index_member_l2_history")
        self.assertTrue(observation["fallback_used"])
        self.assertIn("row_limit", observation["message"])

    def test_historical_run_skips_current_only_fast_path(self) -> None:
        l1, l2 = _classifications()

        def index_classify(*, level):
            return l1 if level == "L1" else l2

        def index_member_all(**_kwargs):
            raise AssertionError("historical PIT run must not use current-only membership")

        canonical = _canonical_members().set_index("index_code")

        def index_member(*, index_code, **_kwargs):
            return canonical.loc[[index_code]].reset_index()

        self.egs_main.TODAY = "20210101"
        self.egs_main.pro = SimpleNamespace(
            index_classify=index_classify,
            index_member_all=index_member_all,
            index_member=index_member,
        )
        with patch.object(self.egs_main, "load_cache", return_value=None), \
             patch.object(self.egs_main, "save_cache"), \
             patch.object(self.egs_main, "safe_api", side_effect=_safe_call):
            mapping = self.egs_main.get_sw_industry_map()

        self.assertEqual(set(mapping), {"000001.SZ", "000002.SZ"})
        observation = self.egs_main._current_sw_industry_source_observation()
        self.assertEqual(observation["source"], "index_member_l2_history")
        self.assertFalse(observation["fast_path_used"])
        self.assertTrue(observation["fallback_used"])
        self.assertEqual(observation["message"], "decision_as_of_requires_pit_history")


class WatchPoolHealthTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.egs_main = _load_egs_module()

    def _health(self, *, actual_count, eligible_count, sidecar_warnings=None):
        frame = pd.DataFrame({
            "ts_code": [f"{i:06d}.SZ" for i in range(actual_count)],
            "tier": ["Tier1"] * actual_count,
            "close": [10.0] * actual_count,
            "pe": [20.0] * actual_count,
            "pb": [2.0] * actual_count,
            "l1_name": ["一级行业"] * actual_count,
            "l2_name": ["二级行业"] * actual_count,
        })
        analysis_input = {
            "schema_name": "analysis_input",
            "schema_version": self.egs_main.ANALYSIS_INPUT_SCHEMA_VERSION,
            "price_data_through": "20260714",
            "source": {
                "screening_engine_version": self.egs_main.EGS_VERSION,
                "data_provider": "tushare",
            },
            "market_context": {
                "margin_coverage": {
                    "reference_date": "20260714",
                    "effective_ref_date": None,
                    "row_count": 0,
                    "universe_size": 0,
                    "coverage_complete": False,
                    "status": "unavailable",
                },
            },
            "candidates": [
                {"data_quality": {"completeness_score": 100}}
                for _ in range(actual_count)
            ],
        }
        return self.egs_main.build_data_health(
            df_full=frame,
            watch_df=frame,
            tier1_final=frame.head(5),
            analysis_input=analysis_input,
            latest_td="20260714",
            analysis_path=str(EGS_SCRIPT),
            snapshot_path=str(EGS_SCRIPT),
            candidates_path=str(EGS_SCRIPT),
            tier1_csv_path=str(EGS_SCRIPT),
            full_csv_path=str(EGS_SCRIPT),
            watch_eligible_count=eligible_count,
            sidecar_warnings=sidecar_warnings,
        )

    def test_eligible_pool_exhaustion_is_accounted_without_false_health_warning(self) -> None:
        health = self._health(actual_count=13, eligible_count=13)

        self.egs_main.validate_json_schema(
            health,
            schema_path=str(DATA_HEALTH_SCHEMA),
            label="watch pool health test",
        )
        checks = {item["check"] for item in health["warnings"]}
        self.assertNotIn("watch_pool", checks)
        reconciliation = health["metrics"]["watch_pool_reconciliation"]
        self.assertEqual(reconciliation["status"], "pass")
        self.assertEqual(reconciliation["reason"], "eligible_pool_exhausted")
        self.assertEqual(reconciliation["target_count"], 15)
        self.assertEqual(reconciliation["eligible_count"], 13)
        self.assertEqual(reconciliation["actual_count"], 13)
        self.assertEqual(reconciliation["shortfall_count"], 2)

    def test_unexplained_watch_export_loss_is_an_error(self) -> None:
        health = self._health(actual_count=12, eligible_count=13)

        self.assertEqual(health["overall_status"], "error")
        self.assertIn(
            "watch_pool_reconciliation",
            {item["check"] for item in health["errors"]},
        )
        reconciliation = health["metrics"]["watch_pool_reconciliation"]
        self.assertEqual(reconciliation["status"], "fail")
        self.assertEqual(reconciliation["reason"], "output_count_mismatch")

    def test_comparison_sidecar_failure_is_visible_as_health_warning(self) -> None:
        warning = self.egs_main._comparison_sidecar_warning(
            "theme_overlay", NameError("name 'json' is not defined"),
        )
        health = self._health(
            actual_count=13,
            eligible_count=13,
            sidecar_warnings=[warning],
        )

        self.egs_main.validate_json_schema(
            health,
            schema_path=str(DATA_HEALTH_SCHEMA),
            label="comparison sidecar health test",
        )
        self.assertEqual(health["overall_status"], "warn")
        self.assertIn(warning, health["warnings"])
        self.assertIn("NameError: name 'json' is not defined", warning["message"])

    def test_cninfo_unknown_source_is_visible_as_health_warning(self) -> None:
        warning = self.egs_main._cninfo_health_warning({
            "requested_count": 13,
            "known_clear_count": 0,
            "advisory_hit_count": 0,
            "unknown_count": 13,
            "unknown_reasons": {"empty_announcements": 13},
        })
        health = self._health(
            actual_count=13,
            eligible_count=13,
            sidecar_warnings=[warning],
        )

        self.egs_main.validate_json_schema(
            health,
            schema_path=str(DATA_HEALTH_SCHEMA),
            label="cninfo health warning test",
        )
        self.assertEqual(health["overall_status"], "warn")
        self.assertIn(warning, health["warnings"])
        self.assertEqual(warning["check"], "cninfo_regulatory_advisory")
        self.assertEqual(warning["unknown_reasons"], {"empty_announcements": 13})

    def test_consistency_validator_rejects_forged_watch_accounting(self) -> None:
        health = self._health(actual_count=13, eligible_count=13)
        health["metrics"]["watch_pool_reconciliation"]["reason"] = "target_met"

        with self.assertRaisesRegex(ValueError, "watch_pool_reconciliation"):
            self.egs_main.validate_data_health_consistency(health)

    def test_consistency_validator_rejects_passing_low_coverage_sw_source(self) -> None:
        health = self._health(actual_count=13, eligible_count=13)
        health["metrics"]["sw_industry_membership"] = {
            "status": "pass",
            "source": "index_member_all_l1_current",
            "as_of": "20260714",
            "active_count": 2999,
            "min_active": 3000,
            "request_group_count": 31,
            "fast_path_used": True,
            "fallback_used": False,
            "cache_hit": False,
            "message": None,
        }

        with self.assertRaisesRegex(ValueError, "minimum coverage"):
            self.egs_main.validate_data_health_consistency(health)


if __name__ == "__main__":
    unittest.main()

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
    default = kwargs.pop("default", None)
    retries = kwargs.pop("retries", 3)
    errors = kwargs.pop("errors", None)
    for attempt in range(retries):
        try:
            result = fn(*args, **kwargs)
            if result is not None and len(result) > 0:
                return result
            return default
        except Exception as exc:
            if attempt == retries - 1:
                if errors is not None:
                    errors.append(exc)
                    return default
                raise
    return default


def _classifications():
    l1 = pd.DataFrame({
        "index_code": ["801000.SI"],
        "industry_code": ["801000"],
        "industry_name": ["一级行业"],
        "src": ["SW2021"],
    })
    l2 = pd.DataFrame({
        "index_code": ["801783.SI", "801780.SI"],
        "industry_name": ["股份制银行Ⅱ", "银行"],
        "parent_code": ["801000", "801000"],
        "src": ["SW2021", "SW2021"],
    })
    return l1, l2


def _canonical_members():
    return pd.DataFrame({
        "con_code": ["000001.SZ", "000002.SZ"],
        "index_code": ["801783.SI", "801780.SI"],
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
        classify_calls = []
        calls = []

        def index_classify(*, level, src, fields):
            classify_calls.append({"level": level, "src": src, "fields": fields})
            return l1 if level == "L1" else l2

        def index_member_all(**kwargs):
            calls.append(kwargs)
            return pd.DataFrame({
                "ts_code": ["000001.SZ", "000002.SZ"],
                "l2_code": ["801783.SI", "801780.SI"],
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
        self.assertEqual(mapping["000001.SZ"]["l2_code"], "801783.SI")
        self.assertNotEqual(mapping["000001.SZ"]["l1_name"], "未知")
        master = self.egs_main.build_master(
            pd.DataFrame({
                "ts_code": ["000001.SZ", "000002.SZ"],
                "pct_20d": [1.0, 1.0],
            }),
            pd.DataFrame({
                "ts_code": ["000001.SZ", "000002.SZ"],
                "qfq_close": [10.0, 10.0],
                "qfq_source_trade_date": ["20260812", "20260812"],
                "pct_20d": [1.0, 1.0],
            }),
            pd.DataFrame({
                "ts_code": ["000001.SZ", "000002.SZ"],
                "close": [10.0, 10.0],
                "source_trade_date": ["20260812", "20260812"],
            }),
            pd.DataFrame(),
            mapping,
            {"deduct_30d": set()},
        )
        self.assertEqual(
            master.loc[master["ts_code"] == "000001.SZ", "l2_name"].item(),
            "股份制银行Ⅱ",
        )
        self.assertEqual([call["level"] for call in classify_calls], ["L2", "L1"])
        self.assertTrue(all(call["src"] == "SW2021" for call in classify_calls))
        self.assertTrue(all("src" in call["fields"].split(",") for call in classify_calls))
        self.assertEqual(calls[0]["l1_code"], "801000.SI")
        self.assertEqual(calls[0]["is_new"], "Y")
        observation = self.egs_main._current_sw_industry_source_observation()
        self.assertEqual(observation["status"], "pass")
        self.assertEqual(observation["source"], "index_member_all_l1_current")
        self.assertEqual(observation["request_group_count"], 1)
        self.assertTrue(observation["fast_path_used"])
        self.assertFalse(observation["fallback_used"])
        self.assertEqual(observation["classification_standard"], "SW2021")
        self.assertEqual(observation["observed_sources"], ["SW2021"])

    def test_fast_path_limit_hit_falls_back_instead_of_accepting_truncation(self) -> None:
        l1, l2 = _classifications()
        limited = pd.DataFrame({
            "ts_code": ["000001.SZ"] * 2000,
            "l2_code": ["801010.SI"] * 2000,
            "in_date": ["20200101"] * 2000,
            "out_date": [""] * 2000,
        })

        def index_classify(*, level, src, fields):
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

        def index_classify(*, level, src, fields):
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
        self.assertEqual(observation["classification_standard"], "SW2021")
        self.assertEqual(observation["observed_sources"], ["SW2021"])

    def test_source_observation_preserves_provider_value_while_binding_case_insensitively(self) -> None:
        l1, l2 = _classifications()
        l1 = l1.copy()
        l2 = l2.copy()
        l1["src"] = "sw2021"
        l2["src"] = "sw2021"

        def index_classify(*, level, src, fields):
            return l1 if level == "L1" else l2

        def index_member_all(**_kwargs):
            return pd.DataFrame({
                "ts_code": ["000001.SZ", "000002.SZ"],
                "l2_code": ["801783.SI", "801780.SI"],
                "in_date": ["20200101", "20200101"],
                "out_date": ["", ""],
                "is_new": ["Y", "Y"],
            })

        self.egs_main.TODAY = self.egs_main.datetime.now().strftime("%Y%m%d")
        self.egs_main.pro = SimpleNamespace(
            index_classify=index_classify,
            index_member_all=index_member_all,
            index_member=lambda **_kwargs: pd.DataFrame(),
        )
        with patch.object(self.egs_main, "load_cache", return_value=None), \
             patch.object(self.egs_main, "save_cache"), \
             patch.object(self.egs_main, "safe_api", side_effect=_safe_call):
            self.egs_main.get_sw_industry_map()

        observation = self.egs_main._current_sw_industry_source_observation()
        self.assertEqual(observation["classification_standard"], "SW2021")
        self.assertEqual(observation["observed_sources"], ["sw2021"])

    def test_wrong_classification_source_fails_before_members_and_cache_write(self) -> None:
        for source_shape in ("SW2014", "mixed", "missing"):
            with self.subTest(source_shape=source_shape):
                l1, l2 = _classifications()
                if source_shape == "SW2014":
                    l1["src"] = "SW2014"
                    l2["src"] = "SW2014"
                elif source_shape == "mixed":
                    l2.loc[1, "src"] = "SW2014"
                else:
                    l1 = l1.drop(columns=["src"])
                    l2 = l2.drop(columns=["src"])

                member_calls = []

                def index_classify(*, level, src, fields):
                    return l1 if level == "L1" else l2

                def index_member_all(**kwargs):
                    member_calls.append(("index_member_all", kwargs))
                    return pd.DataFrame()

                def index_member(**kwargs):
                    member_calls.append(("index_member", kwargs))
                    return pd.DataFrame()

                self.egs_main.pro = SimpleNamespace(
                    index_classify=index_classify,
                    index_member_all=index_member_all,
                    index_member=index_member,
                )
                with patch.object(self.egs_main, "load_cache", return_value=None), \
                     patch.object(self.egs_main, "save_cache") as save_cache, \
                     patch.object(self.egs_main, "safe_api", side_effect=_safe_call):
                    with self.assertRaisesRegex(RuntimeError, "source binding|missing required"):
                        self.egs_main.get_sw_industry_map()

                self.assertEqual(member_calls, [])
                save_cache.assert_not_called()
                observation = self.egs_main._current_sw_industry_source_observation()
                self.assertEqual(observation["status"], "fail")
                self.assertEqual(observation["source"], "index_classify")
                expected_standard = {
                    "SW2014": "SW2014",
                    "mixed": None,
                    "missing": None,
                }[source_shape]
                expected_sources = {
                    "SW2014": ["SW2014"],
                    "mixed": ["SW2014", "SW2021"],
                    "missing": [],
                }[source_shape]
                self.assertEqual(observation["classification_standard"], expected_standard)
                self.assertEqual(observation["observed_sources"], expected_sources)
                self.assertNotEqual(observation["status"], "not_observed")

    def test_blank_classification_source_fails_before_members_and_reports_missing_rows(self) -> None:
        l1, l2 = _classifications()
        l2 = l2.copy()
        l2.loc[0, "src"] = ""
        member_calls = []

        def index_classify(*, level, src, fields):
            return l1 if level == "L1" else l2

        def index_member(**kwargs):
            member_calls.append(kwargs)
            return _canonical_members()

        self.egs_main.TODAY = "20210101"
        self.egs_main.pro = SimpleNamespace(
            index_classify=index_classify,
            index_member=index_member,
        )
        with patch.object(self.egs_main, "load_cache", return_value=None), \
             patch.object(self.egs_main, "save_cache") as save_cache, \
             patch.object(self.egs_main, "safe_api", side_effect=_safe_call):
            with self.assertRaisesRegex(RuntimeError, "missing_source_count=1"):
                self.egs_main.get_sw_industry_map()

        observation = self.egs_main._current_sw_industry_source_observation()
        self.assertEqual(observation["classification_standard"], "SW2021")
        self.assertEqual(observation["observed_sources"], ["SW2021"])
        self.assertEqual(member_calls, [])
        save_cache.assert_not_called()

    def test_classification_empty_or_exception_records_failure_before_members(self) -> None:
        for failure in ("exception", "empty"):
            with self.subTest(failure=failure):
                l1, l2 = _classifications()
                member_calls = []

                def index_classify(*, level, src, fields):
                    if level == "L2" and failure == "exception":
                        raise RuntimeError("synthetic classification failure")
                    if level == "L2":
                        return pd.DataFrame()
                    return l1

                def index_member_all(**kwargs):
                    member_calls.append(("index_member_all", kwargs))
                    return pd.DataFrame()

                def index_member(**kwargs):
                    member_calls.append(("index_member", kwargs))
                    return pd.DataFrame()

                self.egs_main.pro = SimpleNamespace(
                    index_classify=index_classify,
                    index_member_all=index_member_all,
                    index_member=index_member,
                )
                with patch.object(self.egs_main, "load_cache", return_value=None), \
                     patch.object(self.egs_main, "save_cache") as save_cache, \
                     patch.object(self.egs_main, "safe_api", side_effect=_safe_call):
                    with self.assertRaisesRegex(RuntimeError, r"index_classify:L2"):
                        self.egs_main.get_sw_industry_map()

                observation = self.egs_main._current_sw_industry_source_observation()
                self.assertEqual(observation["status"], "fail")
                self.assertEqual(observation["source"], "index_classify")
                self.assertEqual(member_calls, [])
                save_cache.assert_not_called()

    def test_l2_batch_failures_are_settled_and_abort_without_partial_cache(self) -> None:
        l1, l2 = _classifications()
        self.egs_main.TODAY = "20210101"
        for category in ("exception", "empty", "bad_shape"):
            with self.subTest(category=category):
                member_calls = []

                def index_classify(*, level, src, fields):
                    return l1 if level == "L1" else l2

                def index_member(**kwargs):
                    member_calls.append(kwargs["index_code"])
                    if category == "exception":
                        raise RuntimeError("synthetic member failure")
                    if category == "empty":
                        return pd.DataFrame()
                    return pd.DataFrame({"wrong": [1]})

                self.egs_main.pro = SimpleNamespace(
                    index_classify=index_classify,
                    index_member=index_member,
                    index_member_all=lambda **kwargs: pd.DataFrame(),
                )
                with patch.object(self.egs_main, "load_cache", return_value=None), \
                     patch.object(self.egs_main, "save_cache") as save_cache, \
                     patch.object(self.egs_main, "safe_api", side_effect=_safe_call):
                    with self.assertRaisesRegex(RuntimeError, "l2_batch"):
                        self.egs_main.get_sw_industry_map()

                observation = self.egs_main._current_sw_industry_source_observation()
                self.assertEqual(observation["status"], "fail")
                self.assertEqual(observation["source"], "index_member_l2_history")
                self.assertIn(f"{category}=2", observation["message"])
                self.assertIn("failed_count=2", observation["message"])
                self.assertLessEqual(observation["message"].count("801"), 10)
                self.assertEqual(len(member_calls), 6 if category == "exception" else 2)
                save_cache.assert_not_called()

    def test_l2_batch_empty_group_directory_is_explicitly_fail_closed(self) -> None:
        l1, _l2 = _classifications()
        empty_l2 = pd.DataFrame({
            "index_code": [pd.NA],
            "industry_name": ["空组"],
            "parent_code": ["801000"],
            "src": ["SW2021"],
        })
        member_calls = []

        def index_classify(*, level, src, fields):
            return l1 if level == "L1" else empty_l2

        def index_member(**kwargs):
            member_calls.append(kwargs)
            return _canonical_members()

        self.egs_main.TODAY = "20210101"
        self.egs_main.pro = SimpleNamespace(
            index_classify=index_classify,
            index_member=index_member,
        )
        with patch.object(self.egs_main, "load_cache", return_value=None), \
             patch.object(self.egs_main, "save_cache") as save_cache, \
             patch.object(self.egs_main, "safe_api", side_effect=_safe_call):
            with self.assertRaisesRegex(RuntimeError, "no_l2_groups"):
                self.egs_main.get_sw_industry_map()

        observation = self.egs_main._current_sw_industry_source_observation()
        self.assertIn("l2_batch:no_l2_groups", observation["message"])
        self.assertEqual(member_calls, [])
        save_cache.assert_not_called()

    def test_l2_batch_row_limit_is_settled_as_bad_shape_without_partial_cache(self) -> None:
        l1, l2 = _classifications()
        limit = self.egs_main.SW_INDEX_MEMBER_ALL_ROW_LIMIT

        def index_classify(*, level, src, fields):
            return l1 if level == "L1" else l2

        def index_member(*, index_code, **_kwargs):
            if index_code == "801783.SI":
                return pd.DataFrame({
                    "con_code": ["000001.SZ"] * limit,
                    "index_code": [index_code] * limit,
                    "in_date": ["20200101"] * limit,
                    "out_date": [""] * limit,
                })
            return _canonical_members().query("index_code == @index_code").copy()

        self.egs_main.TODAY = "20210101"
        self.egs_main.pro = SimpleNamespace(
            index_classify=index_classify,
            index_member=index_member,
        )
        with patch.object(self.egs_main, "load_cache", return_value=None), \
             patch.object(self.egs_main, "save_cache") as save_cache, \
             patch.object(self.egs_main, "safe_api", side_effect=_safe_call):
            with self.assertRaisesRegex(RuntimeError, "row_limit_hit"):
                self.egs_main.get_sw_industry_map()

        observation = self.egs_main._current_sw_industry_source_observation()
        self.assertIn("bad_shape=1", observation["message"])
        self.assertIn("row_limit_hit", observation["message"])
        save_cache.assert_not_called()

    def test_unresolved_l2_parent_fails_before_any_member_call(self) -> None:
        l1, l2 = _classifications()
        l2 = l2.copy()
        l2.loc[1, "parent_code"] = "899999"
        member_calls = []

        def index_classify(*, level, src, fields):
            return l1 if level == "L1" else l2

        def index_member(**kwargs):
            member_calls.append(kwargs)
            return _canonical_members()

        self.egs_main.pro = SimpleNamespace(
            index_classify=index_classify,
            index_member=index_member,
            index_member_all=lambda **kwargs: pd.DataFrame(),
        )
        with patch.object(self.egs_main, "load_cache", return_value=None), \
             patch.object(self.egs_main, "save_cache") as save_cache, \
             patch.object(self.egs_main, "safe_api", side_effect=_safe_call):
            with self.assertRaisesRegex(RuntimeError, "unresolved_parent_count=1"):
                self.egs_main.get_sw_industry_map()

        observation = self.egs_main._current_sw_industry_source_observation()
        self.assertEqual(observation["source"], "index_classify")
        self.assertIn("l2_total=2", observation["message"])
        self.assertIn("899999", observation["message"])
        self.assertEqual(member_calls, [])
        save_cache.assert_not_called()

    def test_null_and_whitespace_sw_codes_fail_parent_closure_before_members(self) -> None:
        cases = ("l1_index_code_null", "l1_industry_code_null", "l2_parent_null", "l2_parent_whitespace")
        for case in cases:
            with self.subTest(case=case):
                l1, l2 = _classifications()
                if case == "l1_index_code_null":
                    l1.loc[0, "index_code"] = pd.NA
                    l2.loc[0, "parent_code"] = pd.NA
                elif case == "l1_industry_code_null":
                    l1.loc[0, "industry_code"] = pd.NA
                    l2.loc[0, "parent_code"] = pd.NA
                elif case == "l2_parent_null":
                    l2.loc[0, "parent_code"] = pd.NA
                else:
                    l2.loc[0, "parent_code"] = " 801000"
                member_calls = []

                def index_classify(*, level, src, fields):
                    return l1 if level == "L1" else l2

                def index_member(**kwargs):
                    member_calls.append(kwargs)
                    return _canonical_members()

                self.egs_main.TODAY = "20210101"
                self.egs_main.pro = SimpleNamespace(
                    index_classify=index_classify,
                    index_member=index_member,
                )
                with patch.object(self.egs_main, "load_cache", return_value=None), \
                     patch.object(self.egs_main, "save_cache") as save_cache, \
                     patch.object(self.egs_main.time, "sleep", return_value=None):
                    with self.assertRaisesRegex(RuntimeError, "unresolved_parent_count=1"):
                        self.egs_main.get_sw_industry_map()

                observation = self.egs_main._current_sw_industry_source_observation()
                self.assertIn("sample=", observation["message"])
                self.assertEqual(member_calls, [])
                save_cache.assert_not_called()

    def test_real_safe_api_retries_transient_classification_then_passes(self) -> None:
        l1, l2 = _classifications()
        attempts = {"L2": 0}

        def index_classify(*, level, src, fields):
            if level == "L2":
                attempts[level] += 1
                if attempts[level] == 1:
                    raise RuntimeError("transient classification failure")
                return l2
            return l1

        canonical = _canonical_members()

        def index_member(*, index_code, **_kwargs):
            return canonical[canonical["index_code"] == index_code].copy()

        self.egs_main.TODAY = "20210101"
        self.egs_main.pro = SimpleNamespace(index_classify=index_classify, index_member=index_member)
        with patch.object(self.egs_main, "load_cache", return_value=None), \
             patch.object(self.egs_main, "save_cache"), \
             patch.object(self.egs_main.time, "sleep", return_value=None):
            mapping = self.egs_main.get_sw_industry_map()

        self.assertEqual(set(mapping), {"000001.SZ", "000002.SZ"})
        self.assertEqual(attempts["L2"], 2)
        self.assertEqual(
            self.egs_main._current_sw_industry_source_observation()["status"],
            "pass",
        )

    def test_real_safe_api_retries_persistent_classification_failure(self) -> None:
        l1, _l2 = _classifications()
        attempts = {"L2": 0}

        def index_classify(*, level, src, fields):
            if level == "L2":
                attempts[level] += 1
                raise RuntimeError("persistent classification failure")
            return l1

        member_calls = []

        def index_member(**kwargs):
            member_calls.append(kwargs)
            return _canonical_members()

        self.egs_main.TODAY = "20210101"
        self.egs_main.pro = SimpleNamespace(index_classify=index_classify, index_member=index_member)
        with patch.object(self.egs_main, "load_cache", return_value=None), \
             patch.object(self.egs_main, "save_cache") as save_cache, \
             patch.object(self.egs_main.time, "sleep", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "index_classify:L2:exception=RuntimeError"):
                self.egs_main.get_sw_industry_map()

        self.assertEqual(attempts["L2"], 3)
        self.assertEqual(member_calls, [])
        save_cache.assert_not_called()

    def test_real_safe_api_retries_transient_l2_group_then_passes(self) -> None:
        l1, l2 = _classifications()
        attempts = {"801783.SI": 0, "801780.SI": 0}
        canonical = _canonical_members()

        def index_classify(*, level, src, fields):
            return l1 if level == "L1" else l2

        def index_member(*, index_code, **_kwargs):
            attempts[index_code] += 1
            if index_code == "801783.SI" and attempts[index_code] == 1:
                raise RuntimeError("transient member failure")
            return canonical[canonical["index_code"] == index_code].copy()

        self.egs_main.TODAY = "20210101"
        self.egs_main.pro = SimpleNamespace(index_classify=index_classify, index_member=index_member)
        with patch.object(self.egs_main, "load_cache", return_value=None), \
             patch.object(self.egs_main, "save_cache"), \
             patch.object(self.egs_main.time, "sleep", return_value=None):
            mapping = self.egs_main.get_sw_industry_map()

        self.assertEqual(set(mapping), {"000001.SZ", "000002.SZ"})
        self.assertEqual(attempts["801783.SI"], 2)
        self.assertEqual(attempts["801780.SI"], 1)

    def test_real_safe_api_retries_persistent_l2_group_and_aborts_batch(self) -> None:
        l1, l2 = _classifications()
        attempts = {"801783.SI": 0, "801780.SI": 0}
        canonical = _canonical_members()

        def index_classify(*, level, src, fields):
            return l1 if level == "L1" else l2

        def index_member(*, index_code, **_kwargs):
            attempts[index_code] += 1
            if index_code == "801783.SI":
                raise RuntimeError("persistent member failure")
            return canonical[canonical["index_code"] == index_code].copy()

        self.egs_main.TODAY = "20210101"
        self.egs_main.pro = SimpleNamespace(index_classify=index_classify, index_member=index_member)
        with patch.object(self.egs_main, "load_cache", return_value=None), \
             patch.object(self.egs_main, "save_cache") as save_cache, \
             patch.object(self.egs_main.time, "sleep", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "l2_batch"):
                self.egs_main.get_sw_industry_map()

        self.assertEqual(attempts["801783.SI"], 3)
        self.assertEqual(attempts["801780.SI"], 1)
        observation = self.egs_main._current_sw_industry_source_observation()
        self.assertIn("exception=1", observation["message"])
        save_cache.assert_not_called()

    def test_semantically_invalid_cache_is_refetched(self) -> None:
        l1, l2 = _classifications()
        invalid_cache = {
            "000001.SZ": {
                "l1_name": "未知", "l1_code": "801000", "l2_name": "x", "l2_code": "801783.SI"
            },
            "000002.SZ": {
                "l1_name": "一", "l1_code": "801000", "l2_name": "二", "l2_code": "801780.SI"
            },
        }

        def index_classify(*, level, src, fields):
            return l1 if level == "L1" else l2

        def index_member_all(**kwargs):
            return pd.DataFrame({
                "ts_code": ["000001.SZ", "000002.SZ"],
                "l2_code": ["801783.SI", "801780.SI"],
                "in_date": ["20200101", "20200101"],
                "out_date": ["", ""],
                "is_new": ["Y", "Y"],
            })

        self.egs_main.TODAY = self.egs_main.datetime.now().strftime("%Y%m%d")
        self.egs_main.pro = SimpleNamespace(
            index_classify=index_classify,
            index_member_all=index_member_all,
            index_member=lambda **kwargs: pd.DataFrame(),
        )
        with patch.object(self.egs_main, "load_cache", return_value=invalid_cache), \
             patch.object(self.egs_main, "save_cache") as save_cache, \
             patch.object(self.egs_main, "safe_api", side_effect=_safe_call):
            mapping = self.egs_main.get_sw_industry_map()

        self.assertEqual(set(mapping), {"000001.SZ", "000002.SZ"})
        self.assertNotEqual(mapping["000001.SZ"]["l1_name"], "未知")
        save_cache.assert_called_once()

    def test_valid_sw2021_cache_hit_records_source_bound_observation(self) -> None:
        cached = {
            "000001.SZ": {
                "l1_name": "一级", "l1_code": "801000", "l2_name": "二级一", "l2_code": "801783.SI"
            },
            "000002.SZ": {
                "l1_name": "一级", "l1_code": "801000", "l2_name": "二级二", "l2_code": "801780.SI"
            },
        }
        self.egs_main.pro = SimpleNamespace()
        with patch.object(self.egs_main, "load_cache", return_value=cached), \
             patch.object(self.egs_main, "save_cache") as save_cache:
            result = self.egs_main.get_sw_industry_map()

        self.assertEqual(result, cached)
        observation = self.egs_main._current_sw_industry_source_observation()
        self.assertEqual(observation["classification_standard"], "SW2021")
        self.assertEqual(observation["observed_sources"], ["SW2021"])
        self.assertEqual(observation["message"], "cache_key_source_binding")
        save_cache.assert_not_called()

    def test_classification_standard_helper_rejects_invalid_observed_sources(self) -> None:
        for observed in ([], ["SW2014"], ["SW2021", "SW2014"]):
            with self.subTest(observed=observed):
                with self.assertRaises(RuntimeError):
                    self.egs_main._classification_standard_from_observed_sources(observed)

    def test_target_board_failure_reports_full_counts_ratio_and_bounded_sample(self) -> None:
        l1, l2 = _classifications()
        target_codes = [f"000{i:03d}.SZ" for i in range(1, 14)]

        def index_classify(*, level, src, fields):
            return l1 if level == "L1" else l2

        def index_member_all(**kwargs):
            return pd.DataFrame({
                "ts_code": ["000001.SZ", "000002.SZ"],
                "l2_code": ["801783.SI", "801780.SI"],
                "in_date": ["20200101", "20200101"],
                "out_date": ["", ""],
                "is_new": ["Y", "Y"],
            })

        self.egs_main.TODAY = self.egs_main.datetime.now().strftime("%Y%m%d")
        self.egs_main.pro = SimpleNamespace(
            index_classify=index_classify,
            index_member_all=index_member_all,
            index_member=lambda **kwargs: pd.DataFrame(),
            stock_basic=lambda **kwargs: pd.DataFrame(),
        )
        with patch.object(
            self.egs_main,
            "get_stock_list",
            return_value=pd.DataFrame({"ts_code": target_codes}),
        ), patch.object(self.egs_main, "load_cache", return_value=None), \
             patch.object(self.egs_main, "save_cache") as save_cache, \
             patch.object(self.egs_main, "safe_api", side_effect=_safe_call):
            with self.assertRaisesRegex(RuntimeError, "missing_count=11") as raised:
                self.egs_main.get_sw_industry_map()

        message = str(raised.exception)
        self.assertIn("target_count=13", message)
        self.assertIn("missing_ratio=0.846154", message)
        self.assertIn("sample=", message)
        self.assertNotIn("000014.SZ", message)
        observation = self.egs_main._current_sw_industry_source_observation()
        self.assertEqual(observation["message"], message.split(": ", 1)[-1])
        self.assertEqual(observation["status"], "fail")
        save_cache.assert_not_called()

    def test_sw2021_cache_generation_does_not_read_v6(self) -> None:
        l1, l2 = _classifications()
        loaded_keys = []

        def index_classify(*, level, src, fields):
            return l1 if level == "L1" else l2

        def index_member_all(**_kwargs):
            return pd.DataFrame({
                "ts_code": ["000001.SZ", "000002.SZ"],
                "l2_code": ["801783.SI", "801780.SI"],
                "in_date": ["20200101", "20200101"],
                "out_date": ["", ""],
                "is_new": ["Y", "Y"],
            })

        self.egs_main.TODAY = self.egs_main.datetime.now().strftime("%Y%m%d")
        self.egs_main.pro = SimpleNamespace(
            index_classify=index_classify,
            index_member_all=index_member_all,
            index_member=lambda **_kwargs: pd.DataFrame(),
        )

        def load_cache(key):
            loaded_keys.append(key)
            return None

        with patch.object(self.egs_main, "load_cache", side_effect=load_cache), \
             patch.object(self.egs_main, "save_cache"), \
             patch.object(self.egs_main, "safe_api", side_effect=_safe_call):
            self.egs_main.get_sw_industry_map()

        self.assertEqual(loaded_keys, [f"sw_industry_map_sw2021_v7_{self.egs_main.TODAY}"])


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
            "classification_standard": "SW2021",
            "observed_sources": ["SW2021"],
        }

        with self.assertRaisesRegex(ValueError, "minimum coverage"):
            self.egs_main.validate_data_health_consistency(health)

    def test_schema_and_consistency_accept_truthful_failed_sw_source(self) -> None:
        for standard, observed_sources in (("SW2014", ["SW2014"]), (None, [])):
            with self.subTest(standard=standard):
                health = self._health(actual_count=13, eligible_count=13)
                health["metrics"]["sw_industry_membership"].update({
                    "status": "fail",
                    "classification_standard": standard,
                    "observed_sources": observed_sources,
                    "source": "index_classify",
                    "as_of": "20260714",
                    "active_count": None,
                    "request_group_count": 1,
                    "message": "classification failure",
                })

                self.egs_main.validate_json_schema(
                    health,
                    schema_path=str(DATA_HEALTH_SCHEMA),
                    label="truthful failed SW source test",
                )
                self.egs_main.validate_data_health_consistency(health)


if __name__ == "__main__":
    unittest.main()

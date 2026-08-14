"""egs_main 选股侧两处修复的回归测试(phase6 guard 风格,与 test_egs_main_relisted_guard 同 harness)：

1) filter_l0 主板 only：排除创业板/科创板/北交所 + **B 股(沪 900·深 200)**——回归原内联前缀表漏排 B 股。
2) get_holder_reductions PIT：移除原"未来 30 日"第二段 stk_holdertrade 查询(按 ann_date 抓 as_of 之后才公告的
   减持 = 历史 --as-of/回测 look-ahead)；只保留一段 ann_date<=as_of 的查询。
"""
import importlib.util
import os
import sys
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd


_SAVED_TUSHARE_TOKEN = None


def setUpModule():
    # hermetic(回归 Codex P2):egs_main import 需 TUSHARE_TOKEN(修复后用 pro_api(TOKEN) 配 pro);CI/reviewer 环境无 token 时
    # 自注入 dummy(pro_api(token) 不写 ~/tk.csv、不联网),使本文件不依赖外部 env —— 否则 no-token 时 mod.pro is None /
    # pro.stk_holdertrade AttributeError 会让 import-side-effect / holder 测试 fail。
    global _SAVED_TUSHARE_TOKEN
    _SAVED_TUSHARE_TOKEN = os.environ.get("TUSHARE_TOKEN")
    if not _SAVED_TUSHARE_TOKEN:
        os.environ["TUSHARE_TOKEN"] = "dummy_hermetic_token"


def tearDownModule():
    if _SAVED_TUSHARE_TOKEN is None:
        os.environ.pop("TUSHARE_TOKEN", None)


ROOT = Path(__file__).resolve().parents[2]
EGS_SCRIPT = ROOT / "A-EGS" / "egs_main.py"


def _load_egs_module():
    old_argv = sys.argv[:]
    sys.argv = [str(EGS_SCRIPT), "--help"]
    try:
        spec = importlib.util.spec_from_file_location("egs_main_board_holder_under_test", EGS_SCRIPT)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        return module
    finally:
        sys.argv = old_argv


class FilterL0BoardScopeTest(unittest.TestCase):
    """filter_l0 主板 only：排除非主板 + B 股(沪 900·深 200)。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.egs_main = _load_egs_module()

    def test_filter_l0_excludes_b_shares_and_other_non_main_boards(self) -> None:
        df_stocks = pd.DataFrame([
            {"ts_code": "600000.SH", "symbol": "600000", "name": "浦发银行", "list_status": "L"},   # 主板 SSE → 保留
            {"ts_code": "000001.SZ", "symbol": "000001", "name": "平安银行", "list_status": "L"},   # 主板 SZSE → 保留
            {"ts_code": "900901.SH", "symbol": "900901", "name": "外高B股", "list_status": "L"},    # 沪 B 股 → 排除
            {"ts_code": "200011.SZ", "symbol": "200011", "name": "深中冠B", "list_status": "L"},    # 深 B 股 → 排除
            {"ts_code": "300750.SZ", "symbol": "300750", "name": "某创业板", "list_status": "L"},   # 创业板 → 排除
            {"ts_code": "688981.SH", "symbol": "688981", "name": "某科创板", "list_status": "L"},   # 科创板 → 排除
            {"ts_code": "920001.BJ", "symbol": "920001", "name": "某北交所", "list_status": "L"},   # 北交所 → 排除
            {"ts_code": "600ABC.SH", "symbol": "600ABC", "name": "畸形码", "list_status": "L"},     # 非 6 位数字 → strict inclusion 排除
        ])
        # 空 stats(有列无行)→ filter_l0 跳过量能/涨跌过滤,只看板块 + 名称,使板块过滤单独可测。
        stats_df = pd.DataFrame(columns=["ts_code", "avg_amount_20d", "pct_20d"])
        out = self.egs_main.filter_l0(df_stocks, stats_df, set(), {}, set(), set())
        kept = set(out["ts_code"])
        self.assertEqual(kept, {"600000.SH", "000001.SZ"})
        self.assertNotIn("900901.SH", kept)   # 沪 B 股不再漏排
        self.assertNotIn("200011.SZ", kept)   # 深 B 股不再漏排
        self.assertNotIn("600ABC.SH", kept)   # 畸形码不再漏排(strict is_a_share_main_board inclusion)

    def test_live_delisting_suffix_and_explicit_risk_names_are_excluded(self) -> None:
        em = self.egs_main
        stocks = pd.DataFrame([
            {"ts_code": "600001.SH", "name": "康美退", "list_status": "L"},
            {"ts_code": "600002.SH", "name": "长油退", "list_status": "L"},
            {"ts_code": "600003.SH", "name": "退市风险警示", "list_status": "L"},
            {"ts_code": "600004.SH", "name": "中国平安", "list_status": "L"},
            {"ts_code": "600005.SH", "name": "正常名称", "list_status": "D"},
            {"ts_code": "600006.SH", "name": "正常名称但状态缺失"},
            {"ts_code": "600007.SH", "name": "暂停上市", "list_status": "L"},
        ])
        stats = pd.DataFrame(columns=["ts_code", "avg_amount_20d", "pct_20d"])
        out = em.filter_l0(stocks, stats, set(), {}, set(), set())
        self.assertEqual(set(out["ts_code"]), {"600004.SH"})

    def test_analysis_input_delisting_fields_use_row_truth(self) -> None:
        em = self.egs_main
        bad = em._candidate_from_row(
            pd.Series({"ts_code": "600001.SH", "name": "康美退", "list_status": "D", "close": 10.0}),
            1, {"600001.SH"}, "20260714", set(), set(),
        )
        good = em._candidate_from_row(
            pd.Series({"ts_code": "600002.SH", "name": "中国平安", "list_status": "L", "close": 10.0}),
            1, {"600002.SH"}, "20260714", set(), set(),
        )
        self.assertTrue(bad["event_risk"]["delisting"]["delisting_warning"])
        self.assertFalse(good["event_risk"]["delisting"]["delisting_warning"])

    def test_missing_live_status_is_unknown_not_safe_false(self) -> None:
        em = self.egs_main
        stocks = pd.DataFrame([{"ts_code": "600008.SH", "name": "正常名称"}])
        stats = pd.DataFrame(columns=["ts_code", "avg_amount_20d", "pct_20d"])
        out = em.filter_l0(stocks, stats, set(), {}, set(), set())
        self.assertTrue(out.empty)

    def test_all_non_main_board_rows_produce_a_structural_empty_l0(self) -> None:
        stocks = pd.DataFrame([
            {"ts_code": "300001.SZ", "name": "创业板", "list_status": "L"},
            {"ts_code": "688001.SH", "name": "科创板", "list_status": "L"},
        ])
        stats = pd.DataFrame(columns=[
            "ts_code", "avg_amount_20d", "pct_20d", "price_observation_count",
        ])

        out = self.egs_main.filter_l0(
            stocks, stats, set(), {}, set(), set()
        )

        self.assertTrue(out.empty)
        self.assertIn("ts_code", out.columns)

    def test_missing_daily_stats_symbol_cannot_be_laundered_as_short_history(self) -> None:
        stocks = pd.DataFrame([
            {"ts_code": "600001.SH", "name": "正常一", "list_status": "L"},
            {"ts_code": "600002.SH", "name": "正常二", "list_status": "L"},
        ])
        stats = pd.DataFrame([{
            "ts_code": "600001.SH",
            "avg_amount_20d": 2e8,
            "pct_20d": 1.0,
            "price_observation_count": 61,
        }])

        with self.assertRaisesRegex(RuntimeError, "symbol coverage incomplete"):
            self.egs_main.filter_l0(
                stocks, stats, set(), {}, set(), set()
            )

    def test_sst_and_s_star_st_prefixes_are_excluded_but_s_controls_survive(self) -> None:
        em = self.egs_main
        stocks = pd.DataFrame([
            {"ts_code": "600009.SH", "name": "SST某", "list_status": "L"},
            {"ts_code": "600010.SH", "name": "S*ST某", "list_status": "L"},
            {"ts_code": "600011.SH", "name": "S公司", "list_status": "L"},
            {"ts_code": "600012.SH", "name": "某ST公司", "list_status": "L"},
        ])
        stats = pd.DataFrame(columns=["ts_code", "avg_amount_20d", "pct_20d"])
        for historical in (False, True):
            with patch.object(em, "_historical_replay_mode", return_value=historical):
                out = em.filter_l0(stocks, stats, set(), {}, set(), set())
            self.assertEqual(set(out["ts_code"]), {"600011.SH", "600012.SH"})

    def test_unknown_status_keeps_name_signal_and_unknown_marker(self) -> None:
        flags = self.egs_main.derive_delisting_flags(
            {"name": "康美退", "list_status": ""}, historical=False
        )
        self.assertIsNone(flags["st_flag"])
        self.assertTrue(flags["delisting_warning"])
        self.assertFalse(flags["known"])


class HistoricalNamePitTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.egs_main = _load_egs_module()

    def _stock_basic_rows(self):
        return pd.DataFrame([
            {"ts_code": "600000.SH", "symbol": "600000", "name": "当前正常名",
             "list_date": "20100101", "delist_date": "", "market": "主板", "list_status": "L"},
            {"ts_code": "000001.SZ", "symbol": "000001", "name": "当前正常名",
             "list_date": "20100101", "delist_date": "", "market": "主板", "list_status": "L"},
        ])

    def test_historical_stock_list_uses_active_namechange_row_for_st_veto(self):
        em = self.egs_main
        old_today, old_dt, old_pro = em.TODAY, em.TODAY_DT, em.pro
        em.TODAY, em.TODAY_DT = "20200115", datetime(2020, 1, 15)
        namechange_calls = []

        def stock_basic(**kwargs):
            return self._stock_basic_rows() if kwargs["list_status"] == "L" else pd.DataFrame()

        def namechange(**kwargs):
            namechange_calls.append(kwargs)
            return pd.DataFrame([
                {"ts_code": "600000.SH", "name": "*ST历史名", "start_date": "20190101",
                 "end_date": "20201231", "change_reason": "ST"},
                {"ts_code": "600000.SH", "name": "当前正常名", "start_date": "20210101",
                 "end_date": "", "change_reason": "撤销ST"},
                {"ts_code": "000001.SZ", "name": "当前正常名", "start_date": "20100101",
                 "end_date": "", "change_reason": "其他"},
            ])

        try:
            em.pro = SimpleNamespace(stock_basic=stock_basic, namechange=namechange)
            with patch.object(em, "load_cache", return_value=None), \
                 patch.object(em, "save_cache"), \
                 patch.object(em, "a_share_market_date", return_value="20260714"), \
                 patch.object(em, "safe_api", side_effect=lambda fn, *a, **kw: fn(*a, **kw)):
                stocks = em.get_stock_list()
                stats = pd.DataFrame(columns=["ts_code", "avg_amount_20d", "pct_20d"])
                kept = em.filter_l0(stocks, stats, set(), {}, set(), set())
        finally:
            em.TODAY, em.TODAY_DT, em.pro = old_today, old_dt, old_pro

        self.assertEqual(dict(zip(stocks["ts_code"], stocks["name"]))["600000.SH"], "*ST历史名")
        self.assertEqual(set(kept["ts_code"]), {"000001.SZ"})
        self.assertEqual(len(namechange_calls), 1)
        self.assertEqual(namechange_calls[0]["fields"],
                         "ts_code,name,start_date,end_date,change_reason")

    def test_historical_stock_list_does_not_reuse_current_name_cache(self):
        em = self.egs_main
        old_today, old_dt, old_pro = em.TODAY, em.TODAY_DT, em.pro
        em.TODAY, em.TODAY_DT = "20200115", datetime(2020, 1, 15)
        loaded_keys = []

        def stock_basic(**kwargs):
            return self._stock_basic_rows() if kwargs["list_status"] == "L" else pd.DataFrame()

        def namechange(**kwargs):
            return pd.DataFrame([
                {"ts_code": "600000.SH", "name": "*ST历史名", "start_date": "20190101",
                 "end_date": "20201231", "change_reason": "ST"},
                {"ts_code": "000001.SZ", "name": "当前正常名", "start_date": "20100101",
                 "end_date": "", "change_reason": "其他"},
            ])

        def load_cache(key):
            loaded_keys.append(key)
            # Simulate the shared current-mode cache that must not be queried
            # by a historical replay.
            if key.endswith("_cur"):
                return self._stock_basic_rows()
            return None

        try:
            em.pro = SimpleNamespace(stock_basic=stock_basic, namechange=namechange)
            with patch.object(em, "load_cache", side_effect=load_cache), \
                 patch.object(em, "save_cache"), \
                 patch.object(em, "a_share_market_date", return_value="20260714"), \
                 patch.object(em, "safe_api", side_effect=lambda fn, *a, **kw: fn(*a, **kw)):
                stocks = em.get_stock_list()
        finally:
            em.TODAY, em.TODAY_DT, em.pro = old_today, old_dt, old_pro

        self.assertEqual(loaded_keys, ["stock_list_20200115_v4_hist"])
        self.assertEqual(dict(zip(stocks["ts_code"], stocks["name"]))["600000.SH"], "*ST历史名")

    def test_historical_namechange_coverage_gap_aborts_instead_of_using_current_name(self):
        em = self.egs_main
        old_today, old_dt, old_pro = em.TODAY, em.TODAY_DT, em.pro
        em.TODAY, em.TODAY_DT = "20200115", datetime(2020, 1, 15)

        def stock_basic(**kwargs):
            return self._stock_basic_rows() if kwargs["list_status"] == "L" else pd.DataFrame()

        def namechange(**kwargs):
            return pd.DataFrame([
                {"ts_code": "600000.SH", "name": "当前正常名", "start_date": "20100101",
                 "end_date": "", "change_reason": "其他"},
            ])

        try:
            em.pro = SimpleNamespace(stock_basic=stock_basic, namechange=namechange)
            with patch.object(em, "load_cache", return_value=None), \
                 patch.object(em, "save_cache"), \
                 patch.object(em, "a_share_market_date", return_value="20260714"), \
                 patch.object(em, "safe_api", side_effect=lambda fn, *a, **kw: fn(*a, **kw)):
                with self.assertRaisesRegex(RuntimeError, "coverage incomplete"):
                    em.get_stock_list()
        finally:
            em.TODAY, em.TODAY_DT, em.pro = old_today, old_dt, old_pro

    def test_historical_namechange_end_date_is_inclusive(self):
        em = self.egs_main
        old_today, old_pro = em.TODAY, em.pro
        em.TODAY = "20200115"
        try:
            em.pro = SimpleNamespace(namechange=lambda **kwargs: pd.DataFrame([
                {"ts_code": "600000.SH", "name": "历史名", "start_date": "20190101",
                 "end_date": "20200115", "change_reason": "其他"},
            ]))
            names = em._historical_name_map(pd.DataFrame({"ts_code": ["600000.SH"]}))
        finally:
            em.TODAY, em.pro = old_today, old_pro

        self.assertEqual(names, {"600000.SH": "历史名"})

    def test_current_run_keeps_stock_basic_name_without_namechange_fetch(self):
        em = self.egs_main
        old_today, old_dt, old_pro = em.TODAY, em.TODAY_DT, em.pro
        em.TODAY, em.TODAY_DT = "20260714", datetime(2026, 7, 14)
        namechange_called = False

        def stock_basic(**kwargs):
            return self._stock_basic_rows() if kwargs["list_status"] == "L" else pd.DataFrame()

        def namechange(**kwargs):
            nonlocal namechange_called
            namechange_called = True
            raise AssertionError("current run must not fetch namechange")

        try:
            em.pro = SimpleNamespace(stock_basic=stock_basic, namechange=namechange)
            with patch.object(em, "load_cache", return_value=None), \
                 patch.object(em, "save_cache"), \
                 patch.object(em, "a_share_market_date", return_value="20260714"), \
                 patch.object(em, "safe_api", side_effect=lambda fn, *a, **kw: fn(*a, **kw)):
                stocks = em.get_stock_list()
        finally:
            em.TODAY, em.TODAY_DT, em.pro = old_today, old_dt, old_pro

        self.assertFalse(namechange_called)
        self.assertEqual(set(stocks["name"]), {"当前正常名"})

    def test_duplicate_status_rows_prefer_delisted_before_date_filter(self):
        em = self.egs_main
        old_today, old_dt, old_pro = em.TODAY, em.TODAY_DT, em.pro
        em.TODAY, em.TODAY_DT = "20260714", datetime(2026, 7, 14)

        def stock_basic(**kwargs):
            if kwargs["list_status"] == "L":
                return pd.DataFrame([{
                    "ts_code": "600001.SH", "symbol": "600001", "name": "正常名称",
                    "list_date": "20100101", "delist_date": "", "market": "主板", "list_status": "L",
                }])
            if kwargs["list_status"] == "D":
                return pd.DataFrame([{
                    "ts_code": "600001.SH", "symbol": "600001", "name": "正常名称",
                    "list_date": "20100101", "delist_date": "20260701", "market": "主板", "list_status": "D",
                }])
            return pd.DataFrame()

        try:
            em.pro = SimpleNamespace(stock_basic=stock_basic)
            with patch.object(em, "load_cache", return_value=None), \
                 patch.object(em, "save_cache"), \
                 patch.object(em, "a_share_market_date", return_value="20260714"), \
                 patch.object(em, "safe_api", side_effect=lambda fn, *a, **kw: fn(*a, **kw)):
                stocks = em.get_stock_list()
                self.assertTrue(stocks.empty)
        finally:
            em.TODAY, em.TODAY_DT, em.pro = old_today, old_dt, old_pro

    def _historical_delisting_case(self, active_name: str):
        em = self.egs_main
        old_today, old_dt, old_pro = em.TODAY, em.TODAY_DT, em.pro
        em.TODAY, em.TODAY_DT = "20200115", datetime(2020, 1, 15)

        def stock_basic(**kwargs):
            if kwargs["list_status"] == "D":
                return pd.DataFrame([{
                    "ts_code": "600001.SH", "symbol": "600001", "name": "康美退",
                    "list_date": "20100101", "delist_date": "20201231",
                    "market": "主板", "list_status": "D",
                }])
            return pd.DataFrame()

        def namechange(**kwargs):
            return pd.DataFrame([{
                "ts_code": "600001.SH", "name": active_name,
                "start_date": "20100101", "end_date": "",
                "change_reason": "历史名称",
            }])

        try:
            em.pro = SimpleNamespace(stock_basic=stock_basic, namechange=namechange)
            with patch.object(em, "load_cache", return_value=None), \
                 patch.object(em, "save_cache"), \
                 patch.object(em, "a_share_market_date", return_value="20260714"), \
                 patch.object(em, "safe_api", side_effect=lambda fn, *a, **kw: fn(*a, **kw)):
                stocks = em.get_stock_list()
                stats = pd.DataFrame(columns=["ts_code", "avg_amount_20d", "pct_20d"])
                kept = em.filter_l0(stocks, stats, set(), {}, set(), set())
        finally:
            em.TODAY, em.TODAY_DT, em.pro = old_today, old_dt, old_pro
        return stocks, kept

    def test_historical_as_of_before_delisting_uses_pit_name_and_keeps_stock(self):
        stocks, kept = self._historical_delisting_case("康美股份")
        self.assertEqual(dict(zip(stocks["ts_code"], stocks["name"]))["600001.SH"], "康美股份")
        self.assertEqual(set(kept["ts_code"]), {"600001.SH"})

    def test_historical_as_of_in_delisting_period_excludes_pit_suffix_name(self):
        _stocks, kept = self._historical_delisting_case("康美退")
        self.assertTrue(kept.empty)


class HolderReductionPitTest(unittest.TestCase):
    """get_holder_reductions：只一段 ann_date<=as_of 查询,无"未来 30 日"look-ahead。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.egs_main = _load_egs_module()

    def test_no_future_window_query_only_past_announcements(self) -> None:
        em = self.egs_main
        old_today, old_dt = em.TODAY, em.TODAY_DT
        em.TODAY, em.TODAY_DT = "20260530", datetime(2026, 5, 30)
        calls = []

        def fake_safe_api(fn, *a, **kw):
            calls.append(kw)
            return pd.DataFrame([
                {"ts_code": "600000.SH", "ann_date": "20260528", "in_de": "DE", "after_ratio": 4.0},  # ann<=as_of 近10日 → veto_10d
                {"ts_code": "000001.SZ", "ann_date": "20260505", "in_de": "DE", "after_ratio": 6.0},  # ann<=as_of >10日  → deduct_30d
            ])

        try:
            with patch.object(em, "load_cache", return_value=None), \
                 patch.object(em, "save_cache"), \
                 patch.object(em, "safe_api", side_effect=fake_safe_api):
                res = em.get_holder_reductions()
        finally:
            em.TODAY, em.TODAY_DT = old_today, old_dt

        # 修复核心:只 1 次 stk_holdertrade 查询、且 end_date 不晚于 as_of(无 dfuture 未来窗)。
        self.assertEqual(len(calls), 1)
        self.assertLessEqual(str(calls[0].get("end_date")), "20260530")
        self.assertEqual(res["veto_10d"], {"600000.SH"})
        self.assertEqual(res["deduct_30d"], {"000001.SZ"})


class HasCrashVetoSpecDeviationTest(unittest.TestCase):
    """钉住 has_crash_veto 的**有意偏离**口径(2026-06-19 审查决定保留,不对齐 spec Rule6「放量跌>8%」):
    单日跌>5% ∧ 收在当日振幅下 20% ∧ 次日收盘<(pre_close+close)/2(不修复)→ True;
    次日修复 / 跌幅不足(pct_chg 不<−5)任一不满足 → False。改 −8 或加放量都会让此处行为变化、被本测试抓。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.egs_main = _load_egs_module()

    def setUp(self) -> None:
        self._old = self.egs_main.CONF["daily_stats_min_rows"]
        self.egs_main.CONF["daily_stats_min_rows"] = 2

    def tearDown(self) -> None:
        self.egs_main.CONF["daily_stats_min_rows"] = self._old

    @staticmethod
    def _stock(code, crash_pct, after_close):
        # 3 日 chronological;precompute 按 trade_date DESC 排 → iloc[1]=0528(暴跌日)、iloc[0]=0529(次日)。
        # 暴跌日:high10/low9/close9(收在下 20%:(9−9)/(10−9)=0)/pre_close10 → recover_line=(10+9)/2=9.5;
        # 次日 close=after_close(<9.5=不修复→触发 / >9.5=修复→不触发);crash_pct = 暴跌日 pct_chg 字段。
        qfq_crash_close = 10.0 * (1.0 + crash_pct / 100.0)
        return [
            {"ts_code": code, "trade_date": "20260527", "open": 10.0, "high": 10.2, "low": 9.9,
             "close": 10.0, "qfq_open": 10.0, "qfq_high": 10.2, "qfq_low": 9.9, "qfq_close": 10.0,
             "pre_close": 10.0, "pct_chg": 0.0, "vol": 1000.0, "amount": 200000.0},
            {"ts_code": code, "trade_date": "20260528", "open": 10.0, "high": 10.0, "low": 9.0,
             "close": 9.0, "qfq_open": 10.0, "qfq_high": 10.0, "qfq_low": qfq_crash_close, "qfq_close": qfq_crash_close,
             "pre_close": 10.0, "pct_chg": crash_pct, "vol": 1000.0, "amount": 200000.0},
            {"ts_code": code, "trade_date": "20260529", "open": 9.0, "high": after_close + 0.2, "low": 8.8,
             "close": after_close, "qfq_open": 9.0, "qfq_high": after_close + 0.2, "qfq_low": 8.8, "qfq_close": after_close,
             "pre_close": 9.0, "pct_chg": 0.0, "vol": 1000.0, "amount": 200000.0},
        ]

    def test_crash_veto_caliber_threshold_and_recovery_gates(self) -> None:
        em = self.egs_main
        panel = pd.DataFrame(
            self._stock("600001.SH", -10.0, 9.0)     # 跌10% + 弱收 + 不修复(9.0<9.5)  → True
            + self._stock("600002.SH", -10.0, 9.6)   # 跌10% + 弱收 + **修复**(9.6>9.5) → False(recovery 门)
            + self._stock("600003.SH", -4.0, 9.0)     # 仅跌4%(pct_chg 不<−5) + 弱收+不修复 → False(阈值门)
        )
        stats = em.precompute_stock_stats({"600001.SH", "600002.SH", "600003.SH"}, panel)
        by = {r["ts_code"]: bool(r["has_crash_veto"]) for _, r in stats.iterrows()}
        self.assertTrue(by["600001.SH"])    # 跌>5% + 弱收 + 不修复 → 触发
        self.assertFalse(by["600002.SH"])   # 次日修复 → 不触发(recovery 门)
        self.assertFalse(by["600003.SH"])   # 跌幅<5% → 不触发(−5 阈值门,非 spec 的 −8)

    @staticmethod
    def _window_stock(code, crash_date):
        rows = []
        for date in pd.date_range("2026-05-23", "2026-05-29"):
            trade_date = date.strftime("%Y%m%d")
            rows.append({
                "ts_code": code, "trade_date": trade_date,
                "open": 10.0, "high": 10.2, "low": 9.8,
                "close": 10.0, "qfq_open": 10.0, "qfq_high": 10.2, "qfq_low": 9.8, "qfq_close": 10.0,
                "pre_close": 10.0, "pct_chg": 0.0,
                "vol": 1000.0, "amount": 200000.0,
            })

        crash_index = next(i for i, row in enumerate(rows) if row["trade_date"] == crash_date)
        rows[crash_index].update({"high": 10.0, "low": 9.0, "close": 9.0,
                                  "qfq_high": 10.0, "qfq_low": 9.0, "qfq_close": 9.0, "pct_chg": -10.0})
        rows[crash_index + 1].update({"high": 9.2, "low": 8.8, "close": 9.0,
                                      "qfq_high": 9.2, "qfq_low": 8.8, "qfq_close": 9.0, "pre_close": 9.0})
        return rows

    def test_crash_veto_scans_five_confirmed_days_not_six(self) -> None:
        em = self.egs_main
        panel = pd.DataFrame(
            self._window_stock("600004.SH", "20260524")  # DESC iloc[5]：第5个已有次日确认的交易日
            + self._window_stock("600005.SH", "20260523")  # DESC iloc[6]：第6个，必须在窗口外
        )
        stats = em.precompute_stock_stats({"600004.SH", "600005.SH"}, panel)
        by = {r["ts_code"]: bool(r["has_crash_veto"]) for _, r in stats.iterrows()}
        self.assertTrue(by["600004.SH"])
        self.assertFalse(by["600005.SH"])


class EgsImportNoTokenSideEffectTest(unittest.TestCase):
    """P0(Codex 审查补漏):egs_main import **不得调 ts.set_token**——set_token 在 import 期写 ~/tk.csv,
    是 import 文件副作用 + 沙箱/受限环境 PermissionError(会卡住只读单测)。egs_main 全程用本地 pro 客户端、
    不依赖全局 token,故改用 pro_api(TOKEN) 直传。与 a_short_iv_feed_probe 的 init-side-effect 不变式同精神。"""

    def test_import_does_not_call_set_token(self) -> None:
        try:
            import tushare
        except ImportError:
            self.skipTest("tushare 未安装")
        with patch.object(tushare, "set_token") as mock_st:
            mod = _load_egs_module()   # 现有 TUSHARE_TOKEN(测试 env)下 fresh import
        self.assertEqual(mock_st.call_count, 0)   # 0 = import 期不写 ~/tk.csv
        self.assertIsNotNone(mod.pro)             # pro 仍由 pro_api(TOKEN) 配好(行为不变)


if __name__ == "__main__":
    unittest.main()

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
            {"ts_code": "600000.SH", "symbol": "600000", "name": "浦发银行"},   # 主板 SSE → 保留
            {"ts_code": "000001.SZ", "symbol": "000001", "name": "平安银行"},   # 主板 SZSE → 保留
            {"ts_code": "900901.SH", "symbol": "900901", "name": "外高B股"},    # 沪 B 股 → 排除
            {"ts_code": "200011.SZ", "symbol": "200011", "name": "深中冠B"},    # 深 B 股 → 排除
            {"ts_code": "300750.SZ", "symbol": "300750", "name": "某创业板"},   # 创业板 → 排除
            {"ts_code": "688981.SH", "symbol": "688981", "name": "某科创板"},   # 科创板 → 排除
            {"ts_code": "920001.BJ", "symbol": "920001", "name": "某北交所"},   # 北交所 → 排除
            {"ts_code": "600ABC.SH", "symbol": "600ABC", "name": "畸形码"},     # 非 6 位数字 → strict inclusion 排除
        ])
        # 空 stats(有列无行)→ filter_l0 跳过量能/涨跌过滤,只看板块 + 名称,使板块过滤单独可测。
        stats_df = pd.DataFrame(columns=["ts_code", "avg_amount_20d", "pct_20d"])
        out = self.egs_main.filter_l0(df_stocks, stats_df, set(), {}, set(), set())
        kept = set(out["ts_code"])
        self.assertEqual(kept, {"600000.SH", "000001.SZ"})
        self.assertNotIn("900901.SH", kept)   # 沪 B 股不再漏排
        self.assertNotIn("200011.SZ", kept)   # 深 B 股不再漏排
        self.assertNotIn("600ABC.SH", kept)   # 畸形码不再漏排(strict is_a_share_main_board inclusion)


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
                {"ts_code": "600000.SH", "ann_date": "20260528", "in_de": "DE"},  # ann<=as_of 近10日 → veto_10d
                {"ts_code": "000001.SZ", "ann_date": "20260505", "in_de": "DE"},  # ann<=as_of >10日  → deduct_30d
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
        return [
            {"ts_code": code, "trade_date": "20260527", "open": 10.0, "high": 10.2, "low": 9.9,
             "close": 10.0, "pre_close": 10.0, "pct_chg": 0.0, "vol": 1000.0, "amount": 200000.0},
            {"ts_code": code, "trade_date": "20260528", "open": 10.0, "high": 10.0, "low": 9.0,
             "close": 9.0, "pre_close": 10.0, "pct_chg": crash_pct, "vol": 1000.0, "amount": 200000.0},
            {"ts_code": code, "trade_date": "20260529", "open": 9.0, "high": after_close + 0.2, "low": 8.8,
             "close": after_close, "pre_close": 9.0, "pct_chg": 0.0, "vol": 1000.0, "amount": 200000.0},
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
                "close": 10.0, "pre_close": 10.0, "pct_chg": 0.0,
                "vol": 1000.0, "amount": 200000.0,
            })

        crash_index = next(i for i, row in enumerate(rows) if row["trade_date"] == crash_date)
        rows[crash_index].update({"high": 10.0, "low": 9.0, "close": 9.0, "pct_chg": -10.0})
        rows[crash_index + 1].update({"high": 9.2, "low": 8.8, "close": 9.0, "pre_close": 9.0})
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

"""#6 突破口径迁移到 v14.2 spec(站稳 MA10 + 当日量>5日均量×1.2),旧涨停口径降为审计字段。

证明:
- precompute_stock_stats 产出的 is_breakout 按 spec 口径(MA10 + 放量1.2),不再是"近20日涨停≥3"。
- 旧口径保留为 limit_breakout_legacy(审计),且能与新 is_breakout 出现差异(口径真的换了)。
- is_breakout 不进 l4_score 评分公式 → 改它不动 TopN/排序(只改 derived_flags 标签面)。
"""
import importlib.util
import sys
import unittest
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
EGS_SCRIPT = ROOT / "A-EGS" / "egs_main.py"


def _load_egs_module():
    old_argv = sys.argv[:]
    sys.argv = [str(EGS_SCRIPT), "--help"]
    try:
        spec = importlib.util.spec_from_file_location("egs_main_breakout_spec_under_test", EGS_SCRIPT)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        return module
    finally:
        sys.argv = old_argv


def _days(code, closes_nf, amounts_nf):
    """构造单只逐日行(newest-first 传入;trade_date 递减)。high=close、low=close−0.1、
    pre_close=前一日 close(最老日 pre=自身)、pct_chg 正(避免 crash veto)。"""
    n = len(closes_nf)
    rows = []
    for i in range(n):
        close = float(closes_nf[i])
        pre_close = float(closes_nf[i + 1]) if i + 1 < n else close
        rows.append({
            "ts_code": code,
            "trade_date": 20260612 - i,          # newest-first → 递减
            "close": close,
            "amount": float(amounts_nf[i]),
            "pct_chg": 1.0,                       # 正,避免 has_crash_veto(<−5)
            "pre_close": pre_close,
            "high": close,                       # 仅当 close==pre_close×1.1 时才成涨停
            "low": close - 0.1,
        })
    return rows


class BreakoutSpecTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.egs = _load_egs_module()

    def setUp(self):
        self._min = self.egs.CONF.get("daily_stats_min_rows")
        self.egs.CONF["daily_stats_min_rows"] = 1     # 测试小样本:放开覆盖率门

    def tearDown(self):
        self.egs.CONF["daily_stats_min_rows"] = self._min

    def _stats(self, all_rows):
        df = pd.DataFrame(all_rows)
        codes = sorted(df["ts_code"].unique())
        out = self.egs.precompute_stock_stats(codes, df)
        return {r["ts_code"]: r for _, r in out.iterrows()}

    def test_spec_breakout_true_and_legacy_false(self):
        # close0=10.8≥ma10(10.08) 且 amt0 200>5日均(120)×1.2=144 → spec 突破;无涨停 → legacy False
        rows = _days("AAA.SZ", [10.8] + [10.0] * 11, [200.0] + [100.0] * 11)
        s = self._stats(rows)["AAA.SZ"]
        self.assertTrue(s["is_breakout"])
        self.assertFalse(s["limit_breakout_legacy"])

    def test_below_ma10_not_breakout(self):
        # close0=9<ma10(9.9):即使放量也非突破(MA10 门)
        rows = _days("BBB.SZ", [9.0] + [10.0] * 11, [200.0] + [100.0] * 11)
        self.assertFalse(self._stats(rows)["BBB.SZ"]["is_breakout"])

    def test_no_volume_not_breakout(self):
        # close0≥ma10 但量平(amt0=amt5)→ 非突破(放量门)
        rows = _days("CCC.SZ", [10.8] + [10.0] * 11, [100.0] * 12)
        self.assertFalse(self._stats(rows)["CCC.SZ"]["is_breakout"])

    def test_legacy_true_but_spec_false_proves_redefinition(self):
        # 近3日连续涨停(旧口径=突破)但量平 → 新 spec 口径非突破:证明口径真的换了
        rows = _days("DDD.SZ", [13.31, 12.1, 11.0] + [10.0] * 9, [100.0] * 12)
        s = self._stats(rows)["DDD.SZ"]
        self.assertTrue(s["limit_breakout_legacy"])      # 旧涨停口径仍可见(审计)
        self.assertFalse(s["is_breakout"])               # 新 spec:无放量 → 非突破

    def test_is_breakout_not_in_l4_score_scoring(self):
        # 守护:is_breakout 不出现在任何 l4_score 赋值行 → 口径变更不影响评分/TopN。
        src = EGS_SCRIPT.read_text(encoding="utf-8")
        offending = [ln.strip() for ln in src.splitlines()
                     if "l4_score" in ln and "=" in ln and "is_breakout" in ln]
        self.assertEqual(offending, [], f"is_breakout 渗入 l4_score 评分:{offending}")


if __name__ == "__main__":
    unittest.main()

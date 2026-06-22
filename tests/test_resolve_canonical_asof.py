#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""resolve_canonical_asof 纯函数核心测试（零网络，注入 now + 交易日历）.

覆盖：canonical 收敛（窗口内任意时刻→同一决策日）、端午长假回退、周一盘前/盘后滚动、15:00 收盘边界、
确定性、空窗口报错、main 接线；以及「解析器只做 canonical、不暴露 explicit -AsOf 分类」（防谓词漂移）。
"""
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

import pandas as pd

from runners.resolve_canonical_asof import main as resolver_main
from runners.resolve_canonical_asof import resolve_canonical_asof

# 正常周（无假）：…6/25 Thu, 6/26 Fri, 6/29 Mon, 6/30 Tue, 7/1 Wed…
NORMAL_WEEK = ["20260624", "20260625", "20260626", "20260629", "20260630", "20260701"]
# 端午周：6/19 Fri 为端午休市（不在交易日历）；6/18 Thu 为节前最后已结算交易日，6/22 Mon 复市。
DUANWU_WEEK = ["20260615", "20260616", "20260617", "20260618", "20260622", "20260623", "20260624"]


class ResolveCanonicalAsofTest(unittest.TestCase):
    # ── canonical（省略 as_of）：正常周窗口内任意时刻 → 同一个即将到来的周一 6/29 ──
    def test_friday_after_close_rolls_to_monday(self):
        r = resolve_canonical_asof(datetime(2026, 6, 26, 16, 0), NORMAL_WEEK)
        self.assertEqual(r["as_of"], "20260629")
        self.assertEqual(r["last_settled"], "20260626")

    def test_saturday_resolves_to_monday(self):
        r = resolve_canonical_asof(datetime(2026, 6, 27, 11, 30), NORMAL_WEEK)
        self.assertEqual(r["as_of"], "20260629")
        self.assertEqual(r["last_settled"], "20260626")

    def test_sunday_resolves_to_monday(self):
        r = resolve_canonical_asof(datetime(2026, 6, 28, 23, 0), NORMAL_WEEK)
        self.assertEqual(r["as_of"], "20260629")

    def test_monday_before_close_is_monday(self):
        # 周一盘前：周一未收盘 → canonical=周一（价格由 egs 回退到上周五；新闻到运行时刻）
        r = resolve_canonical_asof(datetime(2026, 6, 29, 9, 30), NORMAL_WEEK)
        self.assertEqual(r["as_of"], "20260629")
        self.assertEqual(r["last_settled"], "20260626")

    def test_monday_after_close_rolls_to_tuesday(self):
        # 周一收盘后：周一已收盘 → 实际为周二决策（窗口外，但行为须定义）
        r = resolve_canonical_asof(datetime(2026, 6, 29, 15, 30), NORMAL_WEEK)
        self.assertEqual(r["as_of"], "20260630")
        self.assertEqual(r["last_settled"], "20260629")

    def test_friday_before_close_is_friday(self):
        # 周五盘前跑 → 周五未收盘 → canonical=周五（价格回退到周四）
        r = resolve_canonical_asof(datetime(2026, 6, 26, 9, 0), NORMAL_WEEK)
        self.assertEqual(r["as_of"], "20260626")
        self.assertEqual(r["last_settled"], "20260625")

    # ── 15:00 收盘边界 ──
    def test_close_boundary_exactly_1500_is_settled(self):
        r = resolve_canonical_asof(datetime(2026, 6, 29, 15, 0, 0), NORMAL_WEEK)
        self.assertEqual(r["as_of"], "20260630")  # 15:00 整 → 周一已收盘 → 滚周二

    def test_close_boundary_one_second_before_1500_not_settled(self):
        r = resolve_canonical_asof(datetime(2026, 6, 29, 14, 59, 59), NORMAL_WEEK)
        self.assertEqual(r["as_of"], "20260629")  # 14:59:59 → 周一未收盘 → 仍周一

    # ── 端午长假：Thursday/周末跑都收敛到复市周一 6/22，节前基准=6/18 ──
    def test_duanwu_thursday_after_close_to_monday(self):
        r = resolve_canonical_asof(datetime(2026, 6, 18, 16, 0), DUANWU_WEEK)
        self.assertEqual(r["as_of"], "20260622")        # 6/19 周五休市 → 下一交易日=周一
        self.assertEqual(r["last_settled"], "20260618")

    def test_duanwu_saturday_to_monday(self):
        # 用户真实场景：端午周六晚跑
        r = resolve_canonical_asof(datetime(2026, 6, 20, 23, 0), DUANWU_WEEK)
        self.assertEqual(r["as_of"], "20260622")
        self.assertEqual(r["run_date"], "20260620")
        self.assertEqual(r["last_settled"], "20260618")

    def test_duanwu_monday_morning_matches_real_run(self):
        # 复刻今天 08:24 的真实运行：canonical=20260622、节前基准=20260618
        r = resolve_canonical_asof(datetime(2026, 6, 22, 8, 24), DUANWU_WEEK)
        self.assertEqual(r["as_of"], "20260622")
        self.assertEqual(r["last_settled"], "20260618")

    # ── 确定性 + 报错 ──
    def test_deterministic(self):
        now = datetime(2026, 6, 20, 23, 0)
        self.assertEqual(resolve_canonical_asof(now, DUANWU_WEEK),
                         resolve_canonical_asof(now, list(reversed(DUANWU_WEEK))))

    def test_no_unsettled_day_raises(self):
        # 日历只含过去交易日（无 now 之后的未收盘日）→ 无法解析 canonical
        past_only = ["20260615", "20260616", "20260617", "20260618"]
        with self.assertRaises(ValueError):
            resolve_canonical_asof(datetime(2026, 6, 20, 23, 0), past_only)

    def test_output_has_no_mode_field(self):
        # 解析器不返回 live/historical mode（canonical 恒 live；分类是 caller 的事，防谓词漂移）
        r = resolve_canonical_asof(datetime(2026, 6, 20, 23, 0), DUANWU_WEEK)
        self.assertEqual(set(r), {"as_of", "run_date", "last_settled"})


class ResolverMainWiringTest(unittest.TestCase):
    """main() 接线：注入假 pro(trade_cal) + now → resolve → 写 JSON（不联网）。"""

    class _FakePro:
        def trade_cal(self, **kw):
            return pd.DataFrame({"cal_date": DUANWU_WEEK})

    def test_main_writes_canonical_json(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "asof.json"
            rc = resolver_main(["--out", str(out)],
                               pro_factory=lambda: self._FakePro(),
                               now_dt=datetime(2026, 6, 20, 23, 0))
            self.assertEqual(rc, 0)
            payload = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(payload, {"as_of": "20260622", "run_date": "20260620",
                                       "last_settled": "20260618"})

    def test_main_does_not_accept_explicit_asof(self):
        # 解析器刻意不暴露 explicit --as-of 分类路径（防与 wrapper/egs/pipeline 的 as_of<run_date 谓词漂移）。
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "asof.json"
            with self.assertRaises(SystemExit):       # argparse 拒未知参数 --as-of
                resolver_main(["--as-of", "20260301", "--out", str(out)],
                              pro_factory=lambda: self._FakePro(),
                              now_dt=datetime(2026, 6, 20, 23, 0))


if __name__ == "__main__":
    unittest.main()

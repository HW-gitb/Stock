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
from runners.resolve_canonical_asof import resolve_canonical_asof, resolve_price_as_of

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


class ResolvePriceAsOfTest(unittest.TestCase):
    """One decision day must yield one price basis, whichever entry point asks."""

    def test_canonical_and_explicit_entries_agree_on_the_same_decision_day(self):
        """The defect this closes: two entries, two different price dates.

        The old wrapper took `last_settled` when `-AsOf` was omitted and the
        decision day itself when it was given, so the same decision day priced
        off two different sessions depending on how it was launched.
        """
        canonical = resolve_canonical_asof(datetime(2026, 6, 26, 16, 0), NORMAL_WEEK)
        explicit = resolve_price_as_of(canonical["as_of"], NORMAL_WEEK)
        self.assertEqual(explicit["price_as_of"], canonical["last_settled"])
        # ... and the retired behaviour really was different
        self.assertNotEqual(explicit["price_as_of"], canonical["as_of"])

    def test_prior_settled_is_the_trading_day_strictly_before_the_decision_day(self):
        self.assertEqual(
            resolve_price_as_of("20260629", NORMAL_WEEK)["price_as_of"], "20260626")
        # across a holiday the calendar decides, not the calendar-day arithmetic
        self.assertEqual(
            resolve_price_as_of("20260622", DUANWU_WEEK)["price_as_of"], "20260618")

    def test_a_historical_decision_day_is_not_priced_off_today(self):
        """`prior_settled` must be relative to the decision day, never to `now`.

        Anchoring on the run's own `last_settled` would feed a months-old replay
        today's close -- look-ahead, and worse than the behaviour being replaced.
        """
        resolved = resolve_price_as_of("20260617", DUANWU_WEEK)
        self.assertEqual(resolved["price_as_of"], "20260616")
        self.assertLess(resolved["price_as_of"], "20260617")

    def test_close_is_allowed_only_for_a_true_past_replay(self):
        """`close` on a LIVE decision day is the retired behaviour with a switch on it.

        The reviewer's probe: `as_of` = today, `now` = 15:30 (settled) used to be
        ALLOWED and returned that day's own close -- while the wrapper classifies
        exactly that case as `mode=live`.  Being settled is not enough; the
        predicate has to be the same `as_of < run_date` the wrapper and the
        pipeline already use.
        """
        replay = resolve_price_as_of("20260626", NORMAL_WEEK, price_basis="close",
                                     now_dt=datetime(2026, 6, 29, 10, 0))
        self.assertEqual(replay["price_as_of"], "20260626")
        for label, now in (("today_after_close", datetime(2026, 6, 26, 15, 30)),
                           ("today_at_the_bell", datetime(2026, 6, 26, 15, 0)),
                           ("intraday", datetime(2026, 6, 26, 14, 59, 59)),
                           ("future", datetime(2026, 6, 24, 16, 0))):
            with self.subTest(label):
                with self.assertRaises(ValueError):
                    resolve_price_as_of("20260626", NORMAL_WEEK, price_basis="close", now_dt=now)

    def test_close_on_a_live_day_would_reproduce_the_retired_same_day_behaviour(self):
        """Reverse control: what the refusal is protecting is not hypothetical."""
        as_of, now = "20260626", datetime(2026, 6, 26, 15, 30)
        with self.assertRaises(ValueError):
            resolve_price_as_of(as_of, NORMAL_WEEK, price_basis="close", now_dt=now)
        # the same day under the production basis prices off the PRIOR session
        self.assertEqual(
            resolve_price_as_of(as_of, NORMAL_WEEK)["price_as_of"], "20260625")

    def test_close_without_a_clock_is_refused_rather_than_assumed(self):
        with self.assertRaises(ValueError):
            resolve_price_as_of("20260626", NORMAL_WEEK, price_basis="close")

    def test_a_non_trading_decision_day_and_an_unknown_basis_fail_closed(self):
        with self.assertRaises(ValueError):
            resolve_price_as_of("20260619", DUANWU_WEEK)          # 端午休市
        with self.assertRaises(ValueError):
            resolve_price_as_of("20260629", NORMAL_WEEK, price_basis="settled")
        with self.assertRaises(ValueError):
            resolve_price_as_of("20260624", NORMAL_WEEK[3:])       # 窗口里没有更早的交易日

    def test_the_basis_travels_with_the_date(self):
        """The artifact has to be able to say which basis produced it."""
        for basis, now in (("prior_settled", None),
                           ("close", datetime(2026, 6, 29, 10, 0))):
            with self.subTest(basis):
                resolved = resolve_price_as_of("20260626", NORMAL_WEEK,
                                               price_basis=basis, now_dt=now)
                self.assertEqual(resolved["price_basis"], basis)
                self.assertEqual(resolved["decision_as_of"], "20260626")


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
                                       "last_settled": "20260618",
                                       "price_basis": "prior_settled",
                                       "price_as_of": "20260618"})
            # The identity that makes one basis out of two entry points: canonical's
            # own `last_settled` is exactly what `prior_settled` resolves for it.
            self.assertEqual(payload["price_as_of"], payload["last_settled"])

    def test_main_resolves_a_price_basis_for_an_explicit_decision_day(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "price.json"
            rc = resolver_main(["--price-as-of-for", "20260623", "--out", str(out)],
                               pro_factory=lambda: self._FakePro(),
                               now_dt=datetime(2026, 6, 20, 23, 0))
            self.assertEqual(rc, 0)
            payload = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(payload, {"decision_as_of": "20260623",
                                       "price_basis": "prior_settled",
                                       "price_as_of": "20260622"})

    def test_main_refuses_close_for_a_live_decision_day(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "price.json"
            with self.assertRaises(ValueError):
                resolver_main(["--price-as-of-for", "20260623", "--price-basis", "close",
                               "--out", str(out)],
                              pro_factory=lambda: self._FakePro(),
                              now_dt=datetime(2026, 6, 20, 23, 0))
            self.assertFalse(out.exists(), "a refused basis must not leave an artifact")

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

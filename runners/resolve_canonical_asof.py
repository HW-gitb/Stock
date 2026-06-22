#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A-short weekly cadence：canonical 决策日 (as_of) 解析器.

用户 2026-06-22 决定：周实盘可在「周五收盘后 → 周一收盘前」窗口内**多次**运行。为避免每次跑用不同的
as_of（→ forward_tracker / regime / overlay 同一周决策被当成多个 cohort 灌水），引入本解析器：窗口内
**任何时刻**运行都收敛到**同一个 canonical 决策日 as_of**。

锚点（用户选定）：canonical = **即将到来 / 当前尚未收盘的交易日**（next trading session not yet closed）。
  - 周五盘后 / 周六 / 周日 / 周一盘前 跑 → 全部收敛到「即将到来的周一」。
  - 周一盘前跑 → 周一（egs_main 盘中回退到上一已结算交易日做价格基准，新闻窗到运行时刻）。
  - 周一收盘(15:00)后跑 → 滚到周二（此时周一已收盘，实际在为周二决策）。窗口内不会发生。

职责边界（**只**解析 canonical，**不**做 explicit -AsOf 的 live/historical 分类）：
  - canonical as_of **永远是真交易日**（从 trade_cal 取），所以 egs_main 的 set_asof 交易日门、整个 PIT
    深层、67 处 as_of 消费面**全部不用动、不用审**——这是「锚周一」相对「放开非交易日门」的核心优势。
  - canonical 按定义恒为 **live**（即将到来/当前未收盘 → as_of >= run_date），caller 据此直接设
    `IsHistoricalAsOf=False`，无需本解析器返回 mode。
  - **显式 -AsOf 的 live/historical 分类由 caller（`weekly_screening.ps1`）用与 egs/pipeline 同一谓词
    `as_of < run_date` 在 PowerShell 侧判定**，本解析器刻意不暴露 explicit 分类路径，避免在两处各算一套
    谓词造成漂移（`as_of < run_date` vs `as_of < last_settled` 会在 [last_settled, run_date) 上分歧）。
  - 纯函数 `resolve_canonical_asof(now_dt, trading_days)` 不碰网络，注入 now + 交易日历即可全量测试；
    薄 `main()` 只负责拉 trade_cal（复用 pinned `init_tushare_pro`，不写 tk.csv）并把结果写 JSON。

只解析日期，不选股、不抓行情、不下单、不改任何决策/PIT 行为。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, time, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# A 股连续竞价 15:00 收盘（本地 = 市场时区 CST）。本机在中国本地跑，datetime.now() 即 CST，
# 与 weekly_screening.ps1 的 Get-Date 同源。收盘后该交易日 EOD 视为「已结算」（canonical 滚到下一交易日）。
A_SHARE_SESSION_CLOSE = time(15, 0)


def resolve_canonical_asof(now_dt, trading_days, *, session_close=A_SHARE_SESSION_CLOSE):
    """纯函数：把「运行时刻 now_dt」+「交易日历 trading_days」解析成 canonical 决策日 as_of。

    canonical = 最早一个「尚未收盘」的交易日（即将到来/当前未收盘的交易日），**按定义恒为 live**
    （as_of >= run_date）。本函数只解析 canonical，不做 explicit-as_of 的 live/historical 分类——
    那由 caller 用 `as_of < run_date` 谓词判定，与 egs/pipeline 一致（见模块 docstring「职责边界」）。

    参数：
      now_dt: datetime（本地/市场时区）。
      trading_days: YYYYMMDD 字符串可迭代（SSE is_open 交易日；需覆盖 now 前后若干交易日，调用方用 trade_cal 拉）。
      session_close: 收盘时刻（默认 15:00）。

    返回 dict：{as_of, run_date, last_settled}。确定性：同 now_dt + trading_days → 同输出（无 wall-clock 副作用）。
    """
    run_date = now_dt.strftime("%Y%m%d")
    td = sorted({str(d) for d in trading_days})
    now_t = now_dt.time()

    def _is_settled(d):
        # 交易日 d 在 now_dt 时刻是否「收盘已过」（EOD 已结算）。
        if d < run_date:
            return True
        if d == run_date:
            return now_t >= session_close
        return False  # 未来交易日，未收盘

    settled = [d for d in td if _is_settled(d)]
    last_settled = settled[-1] if settled else None

    unsettled = [d for d in td if not _is_settled(d)]
    if not unsettled:
        raise ValueError(
            "trading_days 未覆盖任何「尚未收盘」的交易日；无法解析 canonical as_of"
            "（请扩大日历窗口 fwd_days）")

    # 最早一个尚未收盘的交易日 = 即将到来/当前未收盘的交易日（恒为真交易日、恒 live）。
    return {"as_of": unsettled[0], "run_date": run_date, "last_settled": last_settled}


# ── 薄 main：拉 trade_cal（pinned init，不写 tk.csv）→ resolve → 写 JSON ───────────────
def _fetch_trading_days(pro, now_dt, *, back_days=20, fwd_days=20):
    """拉 now 前后窗口内的 SSE 交易日（is_open=1）。窗口 ±20 日覆盖最长 A 股长假（春节 ~9 日）+ 周末两侧。"""
    start = (now_dt - timedelta(days=back_days)).strftime("%Y%m%d")
    end = (now_dt + timedelta(days=fwd_days)).strftime("%Y%m%d")
    cal = pro.trade_cal(exchange="SSE", start_date=start, end_date=end, is_open="1", fields="cal_date")
    if cal is None or len(cal) == 0 or "cal_date" not in getattr(cal, "columns", []):
        raise SystemExit("[FATAL] trade_cal 拉取失败/空；无法解析 canonical as_of（检查网络 / TUSHARE_TOKEN / endpoint pin）")
    return sorted(str(d) for d in cal["cal_date"])


def _write_json_atomic(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write("\n")
    os.replace(tmp, path)


def main(argv=None, pro_factory=None, now_dt=None):
    # 刻意不提供 --as-of：本解析器只解析 canonical（省略 -AsOf 的路径）；显式 -AsOf 由 weekly_screening.ps1
    # 用 `as_of < run_date` 纯日期比较自行分类（与 egs/pipeline 同谓词），不经本解析器，避免谓词漂移。
    p = argparse.ArgumentParser(description="A-short weekly canonical 决策日 (as_of) 解析器（canonical-only）")
    p.add_argument("--out", help="把解析结果 JSON 写到此路径（weekly_screening.ps1 读取）")
    args = p.parse_args(argv)

    now = now_dt or datetime.now()
    if pro_factory is not None:
        pro = pro_factory()
    else:
        token = os.environ.get("TUSHARE_TOKEN")
        if not token:
            raise SystemExit("[FATAL] 需设置环境变量 TUSHARE_TOKEN")
        from runners.a_short_iv_feed_probe import init_tushare_pro  # pinned endpoint，不写 tk.csv
        pro = init_tushare_pro(token)

    trading_days = _fetch_trading_days(pro, now)
    result = resolve_canonical_asof(now, trading_days)

    if args.out:
        _write_json_atomic(args.out, result)
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

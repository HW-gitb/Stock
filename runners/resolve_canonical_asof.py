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

from engine.a_share_market_clock import a_share_market_wall_time

# A 股连续竞价 15:00 收盘（上海市场时区）。收盘后该交易日 EOD 视为「已结算」（canonical 滚到下一交易日）。
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
    # Test and integration callers may inject an absolute instant.  Preserve the
    # established naive-input seam as an already-normalized Shanghai wall time,
    # but never compare an aware non-Shanghai time directly with the 15:00 wall
    # clock.
    if now_dt.tzinfo is not None:
        now_dt = a_share_market_wall_time(now_dt)

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


#: The only two price bases the A-short weekly recognises.  `prior_settled` is
#: the production basis; `close` exists solely so historical research can ask for
#: the decision day's own close without the main path growing a second behaviour.
PRICE_BASES = ("prior_settled", "close")


def resolve_price_as_of(decision_as_of, trading_days, *, price_basis="prior_settled",
                        now_dt=None, session_close=A_SHARE_SESSION_CLOSE):
    """纯函数：把「决策日 + 口径」解析成唯一的价格基准日。

    存在的理由是**同一个决策日过去会得出两个价格基准**：canonical 路径（省略
    ``-AsOf``）取 ``last_settled``，显式 ``-AsOf`` 路径直接取 ``as_of`` 本身。
    同一决策日、两条入口、两种价格——而脚本自己的用法说明里就写着显式 ``-AsOf``。

    ``prior_settled``（默认，也是生产口径）= **严格早于决策日的那个交易日**。对
    canonical 而言它与 ``last_settled`` 恒等：canonical as_of 是最早一个尚未收盘的
    交易日，紧邻它之前的交易日正是最后一个已收盘的。对显式历史 as_of 而言它是决策
    日的前一交易日——不会像旧的 ``last_settled`` 那样把**今天**的收盘价喂给一次
    历史回放（那是 look-ahead），也不再是旧的「取 as_of 当日收盘」那第二种行为。

    ``close`` = 决策日**当日**收盘，**只给真·过去回放**：判据就是 wrapper 与
    egs/pipeline 共用的那一条 ``as_of < run_date``，不另造第二套谓词。「今天、已收盘」
    这一格**也拒**——脚本对它的分类恰是 ``mode=live``，而在 live 决策日取当日收盘
    正是本函数要消灭的那个旧行为（``$PriceAsOf = $AsOf``）；允许它等于把删掉的第二
    种价格行为用一个开关装回来。未来日、盘中、非交易日同样 fail-closed。判 historical
    需要 ``now_dt``。

    返回 dict：``{decision_as_of, price_basis, price_as_of}``——口径与日期一起返回，
    调用方把两者都记进产物，事后能看出这次用的是哪一档。
    """
    if price_basis not in PRICE_BASES:
        raise ValueError(f"未知 price_basis: {price_basis!r}；只接受 {list(PRICE_BASES)}")
    decision = str(decision_as_of)
    td = sorted({str(d) for d in trading_days})
    if decision not in td:
        raise ValueError(
            f"决策日 {decision} 不在提供的交易日历里；无法解析价格基准"
            "（非交易日，或日历窗口没覆盖到它）")

    if price_basis == "prior_settled":
        earlier = [d for d in td if d < decision]
        if not earlier:
            raise ValueError(
                f"交易日历里没有早于 {decision} 的交易日；无法解析 prior_settled 价格基准"
                "（请扩大日历窗口 back_days）")
        return {"decision_as_of": decision, "price_basis": price_basis, "price_as_of": earlier[-1]}

    # close：只允许真·过去回放（as_of < run_date），且必须给出 now_dt 才能判定。
    if now_dt is None:
        raise ValueError("price_basis=close 需要 now_dt 才能判断决策日是否为历史回放")
    if now_dt.tzinfo is not None:
        now_dt = a_share_market_wall_time(now_dt)
    run_date = now_dt.strftime("%Y%m%d")
    if decision >= run_date:
        raise ValueError(
            f"price_basis=close 只能用于真·过去回放（as_of < run_date）；{decision} 相对运行日 "
            f"{run_date} 是 live 决策日——在 live 日取当日收盘正是本刀删掉的第二种价格行为，"
            "不得用开关装回来")
    return {"decision_as_of": decision, "price_basis": price_basis, "price_as_of": decision}


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
    # 刻意不提供 --as-of 用于**分类**：live/historical 仍由 weekly_screening.ps1 用
    # `as_of < run_date` 纯日期比较自行判定（与 egs/pipeline 同谓词），不经本解析器，避免谓词漂移。
    # 但**价格基准**必须两条入口同源，否则就是本刀要消灭的双口径，故显式 as_of 也走
    # 这里的 `--price-as-of-for`（只解析价格日，不做 live/historical 分类）。
    p = argparse.ArgumentParser(description="A-short weekly canonical 决策日 (as_of) / 价格基准解析器")
    p.add_argument("--out", help="把解析结果 JSON 写到此路径（weekly_screening.ps1 读取）")
    p.add_argument("--price-as-of-for", metavar="YYYYMMDD",
                   help="只解析该决策日的价格基准（显式 -AsOf 路径用），不解析 canonical as_of")
    p.add_argument("--price-basis", choices=list(PRICE_BASES), default="prior_settled",
                   help="价格基准口径；生产恒为 prior_settled，close 仅供显式历史研究")
    args = p.parse_args(argv)

    now = now_dt or a_share_market_wall_time()
    if pro_factory is not None:
        pro = pro_factory()
    else:
        token = os.environ.get("TUSHARE_TOKEN")
        if not token:
            raise SystemExit("[FATAL] 需设置环境变量 TUSHARE_TOKEN")
        from runners.a_short_iv_feed_probe import init_tushare_pro  # pinned endpoint，不写 tk.csv
        pro = init_tushare_pro(token)

    if args.price_as_of_for:
        # The explicit-`-AsOf` path.  A historical decision day can sit far outside
        # the default +-20d window, so anchor the fetch on that day instead of now.
        anchor = datetime.strptime(args.price_as_of_for, "%Y%m%d")
        trading_days = _fetch_trading_days(pro, anchor)
        result = resolve_price_as_of(args.price_as_of_for, trading_days,
                                     price_basis=args.price_basis, now_dt=now)
    else:
        trading_days = _fetch_trading_days(pro, now)
        result = resolve_canonical_asof(now, trading_days)
        # Same basis, same function, one source: canonical's `last_settled` must be
        # exactly what `prior_settled` resolves for its own decision day.
        result["price_basis"] = args.price_basis
        result["price_as_of"] = resolve_price_as_of(
            result["as_of"], trading_days,
            price_basis=args.price_basis, now_dt=now)["price_as_of"]

    if args.out:
        _write_json_atomic(args.out, result)
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

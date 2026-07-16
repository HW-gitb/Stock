#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A-short 50ETF IV feed — 构建 runner(批① part 1;PIT-safe).

探测(`a_short_iv_feed_probe`,commit `84044dd`)已证 2000 积分可拿 510050 期权 + 标的、且可反解。
本 runner 把它落成 IV feed:逐 PIT 日(trade_date ≤ as_of)对 510050 **欧式**期权用 Black-Scholes
**反解隐含波动率**(近月平值 call/put 取平均)→ 近月 + 次月 **总方差线性插值到恒定到期(30d)**
→ 得每日 IV → **252日滚动百分位**;另逐日算 50ETF **已实现波动 HV**(末 HV_WINDOW 交易日对数收益年化)
→ feed artifact(date / iv_value / iv_percentile_252d / hv_value)。#6 IV-HV 标签由引擎按 iv_value/hv_value 比值产出(advisory)。

50ETF 期权为欧式,BS 直接适用。无风险利率 r / 红利率 q 为可配近似(feasibility 级,非定价级)。
纯函数(bs_price / implied_vol / atm_iv_for_maturity / constant_maturity_iv / realized_vol / build_daily_iv /
rolling_percentile_252)可用合成 fixture 单测;真实 Tushare 调用复用探测的 fetch,执行期授权。
不动 production / egs_main / V14.2,不真钱、不 ship-gate。
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from pathlib import Path

# Ensure the project root is importable when run directly as `python runners\<this>.py`
# (sys.path[0] is then runners/, so `from runners.*` in main() would fail without this).
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import jsonschema  # noqa: E402
import pandas as pd  # noqa: E402

SCHEMA_NAME = "a_short_iv_feed"
SCHEMA_VERSION = "1.1.0"          # 1.1.0:#6 IV-HV——series 增 hv_value(50ETF 已实现波动),params 增 hv_window
UNDERLYING = "510050.SH"
SCHEMA_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "schemas", "a_short_iv_feed.schema.json")

RISK_FREE = 0.02                 # 近似无风险利率(可配;feasibility 级)
DIV_YIELD = 0.0                  # 近似红利率(50ETF 有分红;v1 取 0,文档标注近似)
CONST_MATURITY_DAYS = 30        # 恒定到期目标(天)
MIN_T_DAYS = 5                  # 太近月(剩余 < 5 日)不稳,跳过
ROLL_WINDOW = 252              # 252 日滚动百分位
MIN_ROLL_OBS = 60             # 滚动百分位最少观测(< 此则 percentile=None)
HV_WINDOW = 21               # #6 IV-HV:已实现波动回看窗(交易日;≈ 30 日历日恒定到期 IV 的可比口径)
HV_ANNUALIZE = 252           # 已实现波动年化因子(× √252)


# ── Black-Scholes(欧式)+ 隐含波动率反解 ────────────────────────────────────
def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def bs_price(S: float, K: float, T: float, r: float, q: float, sigma: float, cp: str) -> float:
    cp = "C" if str(cp).upper() in ("C", "CALL", "认购") else "P"
    fwd, disc = S * math.exp(-q * T), math.exp(-r * T)
    if sigma <= 0 or T <= 0:                       # 内在价值
        return max(fwd - K * disc, 0.0) if cp == "C" else max(K * disc - fwd, 0.0)
    srt = sigma * math.sqrt(T)
    d1 = (math.log(S / K) + (r - q + 0.5 * sigma * sigma) * T) / srt
    d2 = d1 - srt
    if cp == "C":
        return S * math.exp(-q * T) * _norm_cdf(d1) - K * disc * _norm_cdf(d2)
    return K * disc * _norm_cdf(-d2) - S * math.exp(-q * T) * _norm_cdf(-d1)


def implied_vol(price: float, S: float, K: float, T: float, r: float, q: float, cp: str,
                lo: float = 1e-4, hi: float = 5.0, tol: float = 1e-7, iters: int = 100):
    """二分反解 IV;价格在无套利区间外或输入非法 → None。"""
    if price is None or price <= 0 or S <= 0 or K <= 0 or T <= 0:
        return None
    flo = bs_price(S, K, T, r, q, lo, cp) - price
    fhi = bs_price(S, K, T, r, q, hi, cp) - price
    if flo > 0 or fhi < 0:                          # 价格越界(套利/数据脏)
        return None
    for _ in range(iters):
        mid = 0.5 * (lo + hi)
        fm = bs_price(S, K, T, r, q, mid, cp) - price
        if abs(fm) < tol:
            return mid
        if fm > 0:
            hi = mid
        else:
            lo = mid
    return 0.5 * (lo + hi)


# ── ATM / 恒定到期 ───────────────────────────────────────────────────────────
def atm_iv_for_maturity(spot: float, quotes: pd.DataFrame, T: float,
                        r: float = RISK_FREE, q: float = DIV_YIELD):
    """quotes: 同一到期、当日有效报价的合约(列 exercise_price/price/call_put)。
    取最接近现价的 call、put 各一,反解 IV,取可得者均值。无解 → None。"""
    if quotes is None or quotes.empty or spot is None or spot <= 0 or T <= 0:
        return None
    ivs = []
    for cp in ("C", "P"):
        side = quotes[quotes["call_put"].astype(str).str.upper().isin(
            ["C", "CALL", "认购"] if cp == "C" else ["P", "PUT", "认沽"])].copy()
        side = side.dropna(subset=["exercise_price", "price"])
        if side.empty:
            continue
        side["_dist"] = (pd.to_numeric(side["exercise_price"], errors="coerce") - spot).abs()
        row = side.sort_values("_dist").iloc[0]
        iv = implied_vol(float(row["price"]), spot, float(row["exercise_price"]), T, r, q, cp)
        if iv is not None:
            ivs.append(iv)
    return float(sum(ivs) / len(ivs)) if ivs else None


def constant_maturity_iv(near_iv, near_T, next_iv, next_T, target_T):
    """近月/次月 IV 按**总方差**(var = iv^2 · T)对 T 线性插值到 target_T,再换回 IV。
    target 落在 [near_T, next_T] 内插;否则取最近端(不外推过头)。需两腿齐全。"""
    if near_iv is None or next_iv is None or near_T <= 0 or next_T <= 0 or target_T <= 0:
        return None
    if near_T == next_T:
        return float(near_iv)
    lo_T, lo_iv, hi_T, hi_iv = (near_T, near_iv, next_T, next_iv) if near_T < next_T else (next_T, next_iv, near_T, near_iv)
    t = min(max(target_T, lo_T), hi_T)             # clamp 进区间,不外推
    w = (t - lo_T) / (hi_T - lo_T)
    var = (1 - w) * (lo_iv ** 2 * lo_T) + w * (hi_iv ** 2 * hi_T)
    return float(math.sqrt(max(var, 0.0) / t))


# ── 逐日构建 + 滚动百分位 ─────────────────────────────────────────────────────
def _valid_date_mask(s: pd.Series) -> pd.Series:
    return pd.to_datetime(s.astype(str), format="%Y%m%d", errors="coerce").notna()


def _days_between(d0: str, d1: str) -> int:
    a = pd.to_datetime(str(d0), format="%Y%m%d")
    b = pd.to_datetime(str(d1), format="%Y%m%d")
    return int((b - a).days)


def realized_vol(closes, window: int = HV_WINDOW, annualize: int = HV_ANNUALIZE):
    """50ETF 末 window 根 close 的对数收益**年化已实现波动(HV)**。需 ≥ window+1 根有效正收盘价
    (= window 个收益);不足/全非正/非有限 → None(绝不伪造)。样本std(n-1)× √annualize。"""
    vals = []
    for c in closes:
        try:
            cf = float(c)
        except (TypeError, ValueError):
            continue
        if math.isfinite(cf) and cf > 0:
            vals.append(cf)
    vals = vals[-(window + 1):]
    if len(vals) < window + 1:
        return None
    rets = [math.log(vals[i] / vals[i - 1]) for i in range(1, len(vals))]
    n = len(rets)
    mean = sum(rets) / n
    var = sum((x - mean) ** 2 for x in rets) / (n - 1)
    if not math.isfinite(var) or var < 0:
        return None
    return round(math.sqrt(var) * math.sqrt(annualize), 6)


def build_daily_iv(opt_basic: pd.DataFrame, opt_daily: pd.DataFrame, underlier: pd.DataFrame,
                   as_of: str, r: float = RISK_FREE, q: float = DIV_YIELD) -> pd.DataFrame:
    """逐 PIT 日(≤ as_of)算恒定到期 IV。返回 DataFrame[trade_date, iv_value]。
    opt_basic: ts_code/call_put/exercise_price/maturity_date(已是 510050 期权);
    opt_daily: ts_code/trade_date/settle/close(限上述合约);underlier: trade_date/close(510050)。"""
    as_of = str(as_of)
    if opt_basic is None or opt_daily is None or underlier is None or opt_basic.empty or opt_daily.empty or underlier.empty:
        return pd.DataFrame(columns=["trade_date", "iv_value"])
    basic = opt_basic.copy()
    basic["_mat"] = basic["maturity_date"].astype(str)
    basic = basic[_valid_date_mask(basic["_mat"])]
    meta = basic.set_index(basic["ts_code"].astype(str))[["call_put", "exercise_price", "_mat"]]

    od = opt_daily.copy()
    od["_td"] = od["trade_date"].astype(str)
    od = od[_valid_date_mask(od["_td"]) & (od["_td"] <= as_of)]
    od["price"] = pd.to_numeric(od.get("settle"), errors="coerce")
    od["price"] = od["price"].where(od["price"].fillna(0) > 0, pd.to_numeric(od.get("close"), errors="coerce"))

    und = underlier.copy()
    und["_td"] = und["trade_date"].astype(str)
    und = und[_valid_date_mask(und["_td"]) & (und["_td"] <= as_of)]
    und["close"] = pd.to_numeric(und["close"], errors="coerce")
    spot_by_date = und[und["close"].fillna(0) > 0].set_index("_td")["close"].to_dict()

    target_T = CONST_MATURITY_DAYS / 365.0
    sorted_dates = sorted(spot_by_date.keys())
    closes_in_order = [float(spot_by_date[dt]) for dt in sorted_dates]   # 50ETF 收盘序列(供 HV 回看)
    date_pos = {dt: i for i, dt in enumerate(sorted_dates)}
    rows = []
    for d in sorted_dates:
        spot = float(spot_by_date[d])
        day = od[(od["_td"] == d) & (od["price"].fillna(0) > 0)].copy()
        if day.empty:
            continue
        day["_code"] = day["ts_code"].astype(str)
        day = day.join(meta, on="_code")
        day = day.dropna(subset=["_mat", "exercise_price", "call_put"])
        if day.empty:
            continue
        day["_Tdays"] = day["_mat"].map(lambda m: _days_between(d, m))
        fut = day[day["_Tdays"] >= MIN_T_DAYS]
        mats = sorted(fut["_Tdays"].unique())
        if len(mats) < 2:
            continue
        near_days, next_days = mats[0], mats[1]
        near_iv = atm_iv_for_maturity(spot, fut[fut["_Tdays"] == near_days], near_days / 365.0, r, q)
        next_iv = atm_iv_for_maturity(spot, fut[fut["_Tdays"] == next_days], next_days / 365.0, r, q)
        cm = constant_maturity_iv(near_iv, near_days / 365.0, next_iv, next_days / 365.0, target_T)
        if cm is not None:
            hv = realized_vol(closes_in_order[: date_pos[d] + 1])      # PIT:仅用 ≤ d 的 50ETF 收盘
            rows.append({"trade_date": d, "iv_value": round(cm, 6), "hv_value": hv})
    return pd.DataFrame(rows, columns=["trade_date", "iv_value", "hv_value"])


def rolling_percentile_252(iv_df: pd.DataFrame) -> pd.DataFrame:
    """对 iv_value 加 252日滚动百分位(0-100,含当日;trailing 观测 < MIN_ROLL_OBS → None)。"""
    df = iv_df.sort_values("trade_date").reset_index(drop=True).copy()
    pcts = []
    vals = df["iv_value"].tolist()
    for i in range(len(vals)):
        window = vals[max(0, i - ROLL_WINDOW + 1): i + 1]
        if len(window) < MIN_ROLL_OBS:
            pcts.append(None)
            continue
        cur = vals[i]
        pcts.append(round(100.0 * sum(1 for x in window if x <= cur) / len(window), 4))
    df["iv_percentile_252d"] = pcts
    return df


def build_feed_summary(iv_df: pd.DataFrame, as_of: str, generated_at: str) -> dict:
    df = rolling_percentile_252(iv_df) if not iv_df.empty else iv_df.assign(iv_percentile_252d=[])
    series = [{"trade_date": str(r["trade_date"]), "iv_value": float(r["iv_value"]),
               "iv_percentile_252d": (None if pd.isna(r["iv_percentile_252d"]) else float(r["iv_percentile_252d"])),
               "hv_value": (None if pd.isna(r.get("hv_value")) else float(r["hv_value"]))}
              for _, r in df.iterrows()]
    return {
        "schema_name": SCHEMA_NAME,
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "as_of": as_of,
        "underlying": UNDERLYING,
        "params": {"risk_free": RISK_FREE, "div_yield": DIV_YIELD,
                   "const_maturity_days": CONST_MATURITY_DAYS, "min_t_days": MIN_T_DAYS,
                   "roll_window": ROLL_WINDOW, "min_roll_obs": MIN_ROLL_OBS, "hv_window": HV_WINDOW},
        "n_days": len(series),
        "series": series,
        "boundary": {"production": False, "real_money": False, "satisfies_ship_gate": False,
                     "iv_method": "bs_atm_constant_maturity_feasibility_grade"},
    }


def validate_feed_summary_consistency(summary: dict) -> None:
    if not _valid_date_mask(pd.Series([str(summary["as_of"])])).iloc[0]:
        raise ValueError(f"as_of {summary['as_of']} 不是合法日历日期")
    if summary["n_days"] != len(summary["series"]):
        raise ValueError("n_days 与 series 长度不一致")
    prev = None
    for pt in summary["series"]:
        if not _valid_date_mask(pd.Series([pt["trade_date"]])).iloc[0] or pt["trade_date"] > str(summary["as_of"]):
            raise ValueError(f"series 含非法或未来日期: {pt['trade_date']}(PIT 违规)")
        if prev is not None and pt["trade_date"] <= prev:
            raise ValueError("series trade_date 非严格升序/有重复")
        prev = pt["trade_date"]
        if pt["iv_value"] is None or pt["iv_value"] <= 0:
            raise ValueError("iv_value 必须 > 0")
        p = pt["iv_percentile_252d"]
        if p is not None and not (0.0 <= p <= 100.0):
            raise ValueError("iv_percentile_252d 不在 0-100")
        hv = pt.get("hv_value")
        if hv is not None and (not math.isfinite(float(hv)) or float(hv) < 0):
            raise ValueError("hv_value 必须 >= 0 或 null")


def write_feed(summary: dict, out_path: str) -> None:
    """唯一 sanctioned 写盘路径:schema + consistency 校验后原子写。"""
    with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
        schema = json.load(f)
    jsonschema.validate(summary, schema)
    validate_feed_summary_consistency(summary)
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    tmp = str(out_path) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    os.replace(tmp, out_path)


def main(argv=None, pro_factory=None):
    from datetime import datetime
    from runners.a_short_iv_feed_probe import (
        init_tushare_pro, fetch_probe_inputs, filter_50etf_options, _is_valid_yyyymmdd,
        build_fetch_failure_summary, write_fetch_failure_summary,
    )
    p = argparse.ArgumentParser(description="A-short 50ETF IV feed build (BS ATM constant-maturity → 252d pct)")
    p.add_argument("--as-of", required=True, help="YYYYMMDD")
    p.add_argument("--out", required=True)
    p.add_argument("--failure-receipt-out", default=None,
                   help="optional sanitized failure receipt; cleared at startup and written only when a provider call fails")
    p.add_argument("--confirm-fetch-authorized", action="store_true")
    args = p.parse_args(argv)
    if args.failure_receipt_out:
        # A weekly run can reuse an OS PID. Clear before any validation or fetch
        # so a cited receipt can only have been written by this invocation.
        Path(args.failure_receipt_out).unlink(missing_ok=True)
    if not args.confirm_fetch_authorized:
        raise SystemExit("[FATAL] 需 --confirm-fetch-authorized:本 build 会调用 Tushare,须用户授权")
    if not _is_valid_yyyymmdd(args.as_of):
        raise SystemExit(f"[FATAL] --as-of {args.as_of} 不是合法日历日期")
    if pro_factory is not None:
        pro = pro_factory()
    else:
        token = os.environ.get("TUSHARE_TOKEN")
        if not token:
            raise SystemExit("[FATAL] 需设置环境变量 TUSHARE_TOKEN")
        pro = init_tushare_pro(token)
    # 取满 ≥ ROLL_WINDOW 个交易日的 opt_daily,否则永远算不出 252d 分位
    # (R-ASHORT-IVFEED-BUILD-FETCH-WINDOW-NO-PERCENTILE)。
    opt_basic, opt_daily, underlier, report = fetch_probe_inputs(
        pro, args.as_of, lookback_days=ROLL_WINDOW * 2, max_trade_dates=ROLL_WINDOW + 30)
    print(f"[iv_build] fetch rows(basic/daily/underlier)="
          f"{report['opt_basic_rows']}/{report['opt_daily_rows']}/{report['underlier_rows']}; "
          f"trade_dates_probed={report['trade_dates_probed']}/{report['trade_dates_planned']}; "
          f"retry_recovered={len(report['retry_recoveries'])}; "
          f"opt_daily_fail_fast={report['opt_daily_fail_fast_triggered']}; "
          f"had_provider_error={report['had_provider_error']}")
    if report["had_provider_error"]:
        if args.failure_receipt_out:
            failure_summary = build_fetch_failure_summary(report, args.as_of)
            write_fetch_failure_summary(failure_summary, args.failure_receipt_out)
            print(f"[iv_build] sanitized failure receipt -> {args.failure_receipt_out}")
        raise SystemExit("[FATAL] provider-call failure;不构建 feed(已停止后续 opt_daily 请求；见脱敏失败收据)。")
    basic = filter_50etf_options(opt_basic)
    codes = set(basic["ts_code"].astype(str)) if not basic.empty else set()
    daily = opt_daily[opt_daily["ts_code"].astype(str).isin(codes)].copy() if codes and not opt_daily.empty else pd.DataFrame()
    iv_df = build_daily_iv(basic, daily, underlier, args.as_of)
    summary = build_feed_summary(iv_df, args.as_of,
                                 datetime.now().astimezone().isoformat(timespec="seconds"))
    latest_pct = summary["series"][-1]["iv_percentile_252d"] if summary["series"] else None
    if latest_pct is None:
        raise SystemExit(f"[FATAL] built feed 无可用最新 252d 分位(n_days={summary['n_days']} < MIN_ROLL_OBS={MIN_ROLL_OBS});"
                         "不写盘 — 需取更多历史交易日。Slice B 收不到能驱动 Rule3/M0.5/M1 的 feed。")
    write_feed(summary, args.out)
    print(f"[iv_build] n_days={summary['n_days']}; latest_iv_pct={latest_pct}; feed -> {args.out}")


if __name__ == "__main__":
    main()

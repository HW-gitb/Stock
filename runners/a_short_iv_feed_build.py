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
import hashlib
import json
import math
import os
import sys
from functools import lru_cache
from pathlib import Path

# Ensure the project root is importable when run directly as `python runners\<this>.py`
# (sys.path[0] is then runners/, so `from runners.*` in main() would fail without this).
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import jsonschema  # noqa: E402
import pandas as pd  # noqa: E402

SCHEMA_NAME = "a_short_iv_feed"
SCHEMA_VERSION = "1.2.0"          # 1.2.0:M0.5——PIT-safe IV delta/觉醒状态/Rule3 state producer
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

# v14.2 M0.5 producer contract.  ``iv_value`` is a decimal (0.20 = 20%),
# while the specification's IV movement thresholds are percentage points.
AWAKENING_LOW_IV_PERCENTILE = 10.0
AWAKENING_LOW_IV_DAYS = 5
AWAKENING_RISE_PCTPT = 5.0
AWAKENING_RELEASE_TOLERANCE_PCTPT = 1.0
AWAKENING_CASH_RECLAIM_PCT = 20.0
AWAKENING_STATE_SOURCE = "iv_series_state_machine_v1"
# M0.5 option (c): the current account contract cannot attribute same-day sell
# proceeds, so an active awakening is an explicit conservative degradation.
# Keep these labels in the producer module so weekly/Phase5/render cannot drift
# into separate authorities.
M05_CONSERVATIVE_MODE = "conservative_degradation"
M05_CONSERVATIVE_MODE_LABEL = "M0.5 保守降级模式"
M05_CONSERVATIVE_BLOCK_REASON = "M0.5 保守降级模式：本周不新建仓"


@lru_cache(maxsize=1)
def _rule3_thresholds() -> tuple[float, float] | None:
    """Read Rule3 thresholds from the reviewed runtime-policy authority.

    The IV producer must not carry a second copy of the 80/90 thresholds.  A
    malformed or unavailable policy fails closed to ``unknown`` rather than
    silently using stale literals.
    """
    try:
        from engine.a_short_runtime_config import load_runtime_configuration
        phase5 = load_runtime_configuration()["m67"]["phase5"]
        halve = float(phase5["iv_halve_pct"])
        nobuild = float(phase5["iv_nobuild_pct"])
    except (KeyError, TypeError, ValueError, ImportError):
        return None
    if not (math.isfinite(halve) and math.isfinite(nobuild)
            and 0.0 <= halve < nobuild <= 100.0):
        return None
    return halve, nobuild


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
    values = s.astype(str)
    return (values.str.fullmatch(r"[0-9]{8}", na=False)
            & pd.to_datetime(values, format="%Y%m%d", errors="coerce").notna())


def _days_between(d0: str, d1: str) -> int:
    a = pd.to_datetime(str(d0), format="%Y%m%d")
    b = pd.to_datetime(str(d1), format="%Y%m%d")
    return int((b - a).days)


def _normalise_trade_calendar(trade_calendar) -> tuple[str, ...] | None:
    """Return sorted unique exchange sessions, or ``None`` when unavailable.

    The producer receives this list from the same exchange ``trade_cal`` call
    that plans the option probes.  We never infer sessions from weekdays:
    exchange holidays are adjacent when they are absent from this list, while
    a real open session missing from the IV series remains a visible gap.
    """
    if trade_calendar is None:
        return None
    if isinstance(trade_calendar, pd.DataFrame):
        if "cal_date" not in trade_calendar.columns:
            return None
        values = trade_calendar["cal_date"].tolist()
    else:
        try:
            values = list(trade_calendar)
        except TypeError:
            return None
    normalised = [str(value) for value in values]
    if not normalised or not _valid_date_mask(pd.Series(normalised)).all():
        return None
    if len(normalised) != len(set(normalised)):
        return None
    return tuple(sorted(normalised))


def _calendar_session_positions(sessions: tuple[str, ...]) -> dict[str, int]:
    """Build the canonical session-to-position index for adjacency checks."""
    return {date: index for index, date in enumerate(sessions)}


def _trade_calendar_sha256(trade_dates: tuple[str, ...] | list[str] | None) -> str:
    """Hash the canonical ordered session list used by the M0.5 state machine."""
    dates = tuple(trade_dates or ())
    return hashlib.sha256("\n".join(dates).encode("ascii")).hexdigest() if dates else ""


def _calendar_metadata(trade_dates: tuple[str, ...] | None,
                       probed_dates: tuple[str, ...] | None,
                       source: str,
                       independent_trade_dates: tuple[str, ...] | None = None) -> dict:
    dates = tuple(trade_dates or ())
    probed = tuple(probed_dates or ())
    available = trade_dates is not None
    independent = tuple(independent_trade_dates or ())
    metadata = {
        "status": "available" if available else "calendar_unavailable",
        "source": source if available else "calendar_unavailable",
        "trade_dates": list(dates),
        "coverage_start": dates[0] if dates else None,
        "coverage_end": dates[-1] if dates else None,
        "n_trade_dates": len(dates),
        "trade_dates_sha256": _trade_calendar_sha256(dates),
        # Producer-side attempted-date fact. Read-side recomputation uses
        # this (or an independently supplied calendar), not the calendar list
        # being validated, so a row edit cannot redefine adjacency silently.
        "probed_trade_dates": list(probed),
        "probed_trade_dates_sha256": _trade_calendar_sha256(probed),
    }
    if available and independent_trade_dates is not None:
        metadata.update({
            "independent_source": "tushare.fund_daily",
            "independent_trade_dates": list(independent),
            "independent_trade_dates_sha256": _trade_calendar_sha256(independent),
        })
    return metadata


def _feed_dates_are_adjacent(
    d0: str,
    d1: str,
    trade_calendar=None,
    *,
    calendar_positions: dict[str, int] | None = None,
) -> bool:
    """Return true only when ``d0`` and ``d1`` are adjacent exchange sessions.

    ``None`` means the exchange calendar was unavailable, so the predicate is
    deliberately false (fail closed).  This single predicate is used for both
    the one-day IV delta and the five-observation awakening window.  Hot
    callers may pass the index built from the already-normalised calendar so
    the same session list is not normalised and indexed for every observation.
    """
    try:
        a, b = str(d0), str(d1)
        pd.to_datetime(a, format="%Y%m%d")
        pd.to_datetime(b, format="%Y%m%d")
    except (TypeError, ValueError):
        return False
    if a >= b:
        return False
    positions = calendar_positions
    if positions is None:
        sessions = _normalise_trade_calendar(trade_calendar)
        if sessions is None:
            return False
        positions = _calendar_session_positions(sessions)
    return a in positions and positions.get(b) == positions[a] + 1


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


def _finite_optional(value):
    """Return a finite float or ``None`` without treating bool as a number."""
    if isinstance(value, bool):
        return None
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def rule3_status_from_percentile(iv_percentile):
    """Derive the v14.2 Rule 3 market state from one IV percentile.

    This is the producer-side state.  Weekly/Phase5 consume the explicit
    result; the producer itself never silently turns the state into an action.
    """
    pct = _finite_optional(iv_percentile)
    if pct is None or not 0.0 <= pct <= 100.0:
        return "unknown"
    thresholds = _rule3_thresholds()
    if thresholds is None:
        return "unknown"
    halve, nobuild = thresholds
    if pct > nobuild:
        return "no_trade"
    if pct > halve:
        return "reduce_new_position_50pct"
    return "normal"


_M05_STATE_COLUMNS = (
    "iv_change_abs_1d_pctpt",
    "rule3_status",
    "awakening_status",
    "cash_reclaim_pct",
    "awakening_baseline_iv",
    "awakening_trigger_date",
    "awakening_release_date",
)

# These fields are the M0.5 producer output.  Version compatibility must be
# decided from the artifact shape as well as its declared label: a caller must
# not be able to relabel a 1.2.0-shaped artifact as 1.1.0 and skip recompute.
_M05_STATE_FIELD_SET = frozenset(_M05_STATE_COLUMNS)


def _summary_has_m05_content(summary: dict) -> bool:
    """Return whether an IV feed carries any 1.2.0/M0.5-only content."""
    if "calendar" in summary or "awakening" in summary:
        return True
    series = summary.get("series")
    if not isinstance(series, list):
        return False
    return any(
        isinstance(row, dict) and bool(_M05_STATE_FIELD_SET.intersection(row))
        for row in series
    )


def build_m05_state(iv_df: pd.DataFrame, trade_calendar=None) -> pd.DataFrame:
    """Build the PIT-safe M0.5 state machine for every IV observation.

    A trigger requires five *prior* consecutive observations below the 10th
    IV percentile and then a strict one-day IV rise above five percentage
    points.  The baseline is the IV immediately before that low-IV run.  A
    trigger remains active until IV returns within one percentage point of the
    baseline for one trading-day observation.  Missing inputs never clear an
    active trigger and otherwise yield ``unknown``.
    """
    calendar = _normalise_trade_calendar(trade_calendar)
    calendar_positions = _calendar_session_positions(calendar) if calendar is not None else None
    columns = list(iv_df.columns if iv_df is not None else [])
    if iv_df is None or iv_df.empty:
        return pd.DataFrame(columns=columns + [c for c in _M05_STATE_COLUMNS if c not in columns])
    raw_dates = [str(value) for value in iv_df["trade_date"].tolist()]
    if len(raw_dates) != len(set(raw_dates)):
        raise ValueError("M0.5 state input trade_date contains duplicates")
    if not _valid_date_mask(pd.Series(raw_dates)).all():
        raise ValueError("M0.5 state input trade_date contains invalid dates")
    df = iv_df.sort_values("trade_date").reset_index(drop=True).copy()
    iv_values = [_finite_optional(value) for value in df["iv_value"].tolist()]
    pct_values = [_finite_optional(value) for value in df["iv_percentile_252d"].tolist()]
    active = False
    baseline_iv = None
    trigger_date = None
    release_date = None
    rows = []

    for i, raw in df.iterrows():
        trade_date = str(raw["trade_date"])
        iv = iv_values[i]
        pct = pct_values[i]
        previous_iv = iv_values[i - 1] if i > 0 else None
        dates_adjacent = i > 0 and _feed_dates_are_adjacent(
            str(df.loc[i - 1, "trade_date"]),
            trade_date,
            calendar,
            calendar_positions=calendar_positions,
        )
        change = (round(abs(iv - previous_iv) * 100.0, 6)
                  if dates_adjacent and iv is not None and previous_iv is not None else None)
        rule3_status = rule3_status_from_percentile(pct)

        if active:
            # Never downgrade a live trigger on a missing/invalid observation.
            if iv is None or pct is None or baseline_iv is None:
                awakening_status = "active"
                cash_reclaim_pct = AWAKENING_CASH_RECLAIM_PCT
            elif abs(iv - baseline_iv) * 100.0 <= AWAKENING_RELEASE_TOLERANCE_PCTPT:
                active = False
                awakening_status = "inactive"
                cash_reclaim_pct = 0.0
                release_date = trade_date
            else:
                awakening_status = "active"
                cash_reclaim_pct = AWAKENING_CASH_RECLAIM_PCT
        else:
            low_run_start = i - AWAKENING_LOW_IV_DAYS
            baseline_index = low_run_start - 1
            enough_history = baseline_index >= 0
            history_contiguous = (
                enough_history
                and all(
                    _feed_dates_are_adjacent(
                        str(df.loc[j - 1, "trade_date"]),
                        str(df.loc[j, "trade_date"]),
                        calendar,
                        calendar_positions=calendar_positions,
                    )
                    for j in range(baseline_index + 1, i + 1)
                )
            )
            low_run = (
                history_contiguous
                and all(
                    pct_values[j] is not None
                    and pct_values[j] < AWAKENING_LOW_IV_PERCENTILE
                    and iv_values[j] is not None
                    for j in range(low_run_start, i)
                )
            )
            baseline = iv_values[baseline_index] if enough_history else None
            trigger = (
                low_run
                and baseline is not None
                and change is not None
                and change > AWAKENING_RISE_PCTPT
            )
            if trigger:
                active = True
                baseline_iv = round(float(baseline), 6)
                trigger_date = trade_date
                release_date = None
                awakening_status = "active"
                cash_reclaim_pct = AWAKENING_CASH_RECLAIM_PCT
            elif iv is None or pct is None or not enough_history or not history_contiguous:
                awakening_status = "unknown"
                cash_reclaim_pct = None
            else:
                awakening_status = "inactive"
                cash_reclaim_pct = 0.0

        rows.append({
            "iv_change_abs_1d_pctpt": change,
            "rule3_status": rule3_status,
            "awakening_status": awakening_status,
            "cash_reclaim_pct": cash_reclaim_pct,
            "awakening_baseline_iv": baseline_iv,
            "awakening_trigger_date": trigger_date,
            "awakening_release_date": release_date,
        })

    state = pd.DataFrame(rows, columns=list(_M05_STATE_COLUMNS))
    for column in _M05_STATE_COLUMNS:
        df[column] = state[column]
    return df


def build_feed_summary(iv_df: pd.DataFrame, as_of: str, generated_at: str,
                       trade_calendar=None, calendar_source: str = "tushare.trade_cal",
                       trade_dates_probed=None, independent_trade_dates=None) -> dict:
    calendar_dates = _normalise_trade_calendar(trade_calendar)
    probed_dates = _normalise_trade_calendar(trade_dates_probed)
    independent_dates = _normalise_trade_calendar(independent_trade_dates)
    df = rolling_percentile_252(iv_df) if not iv_df.empty else iv_df.assign(iv_percentile_252d=[])
    df = build_m05_state(df, trade_calendar=calendar_dates)
    series = [{"trade_date": str(r["trade_date"]), "iv_value": float(r["iv_value"]),
               "iv_percentile_252d": (None if pd.isna(r["iv_percentile_252d"]) else float(r["iv_percentile_252d"])),
               "hv_value": (None if pd.isna(r.get("hv_value")) else float(r["hv_value"])),
               "iv_change_abs_1d_pctpt": (None if pd.isna(r.get("iv_change_abs_1d_pctpt"))
                                           else float(r["iv_change_abs_1d_pctpt"])),
               "rule3_status": str(r.get("rule3_status") or "unknown"),
               "awakening_status": str(r.get("awakening_status") or "unknown"),
               "cash_reclaim_pct": (None if pd.isna(r.get("cash_reclaim_pct"))
                                     else float(r["cash_reclaim_pct"])),
               "awakening_baseline_iv": (None if pd.isna(r.get("awakening_baseline_iv"))
                                          else float(r["awakening_baseline_iv"])),
               "awakening_trigger_date": (None if pd.isna(r.get("awakening_trigger_date"))
                                           else str(r["awakening_trigger_date"])),
               "awakening_release_date": (None if pd.isna(r.get("awakening_release_date"))
                                           else str(r["awakening_release_date"]))}
              for _, r in df.iterrows()]
    latest = series[-1] if series else {
        "trade_date": None, "iv_change_abs_1d_pctpt": None, "rule3_status": "unknown",
        "awakening_status": "unknown", "cash_reclaim_pct": None,
        "awakening_baseline_iv": None, "awakening_trigger_date": None,
        "awakening_release_date": None,
    }
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
        "calendar": _calendar_metadata(calendar_dates, probed_dates, calendar_source,
                                        independent_dates),
        "awakening": {
            "trade_date": latest["trade_date"],
            "iv_change_abs_1d_pctpt": latest["iv_change_abs_1d_pctpt"],
            "rule3_status": latest["rule3_status"],
            "status": latest["awakening_status"],
            "cash_reclaim_pct": latest["cash_reclaim_pct"],
            "baseline_iv": latest["awakening_baseline_iv"],
            "trigger_date": latest["awakening_trigger_date"],
            "release_date": latest["awakening_release_date"],
            "production_effect_enabled": False,
            "source": AWAKENING_STATE_SOURCE,
        },
        "boundary": {"production": False, "real_money": False, "satisfies_ship_gate": False,
                     "iv_method": "bs_atm_constant_maturity_feasibility_grade"},
    }


def validate_feed_summary_consistency(summary: dict, *, trade_calendar=None,
                                      trade_dates_probed=None,
                                      independent_trade_dates=None) -> None:
    if summary.get("schema_name") not in (None, SCHEMA_NAME):
        raise ValueError("schema_name 必须是 a_short_iv_feed")
    # Older in-memory test/consumer fixtures predate the explicit envelope
    # fields; retain their existing 1.1 read compatibility only when the
    # artifact is genuinely legacy-shaped.  M0.5 content is never allowed to
    # hide behind a self-declared 1.1.0 label.
    has_m05_content = _summary_has_m05_content(summary)
    declared_schema_version = summary.get("schema_version")
    if declared_schema_version is None and has_m05_content:
        raise ValueError("携带 M0.5 字段的 IV feed 必须显式声明 schema_version=1.2.0")
    schema_version = str(declared_schema_version or "1.1.0")
    if schema_version not in {"1.1.0", SCHEMA_VERSION}:
        raise ValueError(f"不支持的 IV feed schema_version: {schema_version}")
    if schema_version == "1.1.0" and has_m05_content:
        raise ValueError("schema_version=1.1.0 不得携带 M0.5/calendar/awakening 字段")
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
    if schema_version != SCHEMA_VERSION:
        return
    calendar = summary.get("calendar")
    if not isinstance(calendar, dict):
        raise ValueError("schema 1.2.0 缺少 exchange trade calendar")
    calendar_status = calendar.get("status")
    calendar_dates = _normalise_trade_calendar(calendar.get("trade_dates"))
    probed_calendar_dates = _normalise_trade_calendar(calendar.get("probed_trade_dates"))
    if calendar_status == "available":
        calendar_source = calendar.get("source")
        if calendar_dates is None or probed_calendar_dates is None or not calendar_source:
            raise ValueError("available trade calendar 缺少 producer probe binding")
        if (calendar_dates[-1] > str(summary["as_of"])
                or probed_calendar_dates[-1] > str(summary["as_of"])):
            raise ValueError("trade calendar 含 as_of 之后的未来日期")
        if (calendar.get("coverage_start") != calendar_dates[0]
                or calendar.get("coverage_end") != calendar_dates[-1]):
            raise ValueError("trade calendar coverage 边界与日期列表不一致")
        if calendar.get("n_trade_dates") != len(calendar_dates):
            raise ValueError("trade calendar n_trade_dates 与日期列表不一致")
        if calendar.get("trade_dates_sha256") != _trade_calendar_sha256(calendar_dates):
            raise ValueError("trade calendar 日期哈希不一致")
        if calendar.get("probed_trade_dates_sha256") != _trade_calendar_sha256(probed_calendar_dates):
            raise ValueError("trade calendar probe 日期哈希不一致")
        if trade_dates_probed is not None:
            supplied_probed = _normalise_trade_calendar(trade_dates_probed)
            if supplied_probed is None or supplied_probed != probed_calendar_dates:
                raise ValueError("外部 trade_dates_probed 与 feed binding 不一致")
        independent_dates = None
        expected_independent_window = None
        if calendar_source == "tushare.trade_cal+fund_daily":
            independent_dates = _normalise_trade_calendar(calendar.get("independent_trade_dates"))
            if (independent_dates is None
                    or not calendar.get("independent_source")
                    or calendar.get("independent_source") != "tushare.fund_daily"):
                raise ValueError("独立 fund_daily 交易日绑定缺失")
            if any(date > str(summary["as_of"]) for date in independent_dates):
                raise ValueError("独立 fund_daily 交易日含 as_of 之后的未来日期")
            if (calendar.get("independent_trade_dates_sha256")
                    != _trade_calendar_sha256(independent_dates)):
                raise ValueError("独立 fund_daily 日期哈希不一致")
            expected_independent_window = tuple(
                date for date in independent_dates
                if calendar_dates[0] <= date <= calendar_dates[-1]
            )
            if expected_independent_window != calendar_dates:
                raise ValueError("trade_cal 与 fund_daily 交易日窗口不一致")
            if independent_trade_dates is not None:
                supplied_independent = _normalise_trade_calendar(independent_trade_dates)
                if supplied_independent is None or supplied_independent != independent_dates:
                    raise ValueError("外部 independent_trade_dates 与 feed binding 不一致")
        elif calendar_source == "tushare.trade_cal":
            if any(key in calendar for key in (
                    "independent_source", "independent_trade_dates",
                    "independent_trade_dates_sha256")):
                raise ValueError("旧 trade_cal 日历不得携带独立来源绑定")
        else:
            raise ValueError(f"不支持的交易日历来源: {calendar_source}")
        supplied_calendar = _normalise_trade_calendar(trade_calendar) if trade_calendar is not None else None
        if trade_calendar is not None and supplied_calendar is None:
            raise ValueError("外部 trade calendar 无效")
        if supplied_calendar is not None:
            trusted_calendar = supplied_calendar
            expected_window = tuple(
                date for date in supplied_calendar
                if calendar_dates[0] <= date <= calendar_dates[-1]
            )
            if expected_window != calendar_dates:
                raise ValueError("外部 trade calendar 未完整覆盖 feed 日历窗口")
            if expected_independent_window is not None and expected_window != expected_independent_window:
                raise ValueError("外部 trade calendar 未与 fund_daily 独立窗口对账")
            if expected_independent_window is not None:
                trusted_calendar = expected_independent_window
        else:
            if probed_calendar_dates != calendar_dates:
                raise ValueError("feed 日历与 producer probe 日期清单不一致")
            # Prefer the independent fund_daily observation when the producer
            # supplied it; the trade_cal list is then only a value to cross-check.
            trusted_calendar = (expected_independent_window
                                if expected_independent_window is not None
                                else probed_calendar_dates)
        if any(pt["trade_date"] not in trusted_calendar for pt in summary["series"]):
            raise ValueError("available trade calendar 未覆盖 IV series")
    elif calendar_status == "calendar_unavailable":
        if (calendar.get("trade_dates") != []
                or calendar.get("probed_trade_dates") != []
                or calendar.get("coverage_start") is not None
                or calendar.get("coverage_end") is not None
                or calendar.get("n_trade_dates") != 0
                or calendar.get("trade_dates_sha256") not in ("", None)
                or calendar.get("probed_trade_dates_sha256") not in ("", None)
                or calendar.get("independent_trade_dates") not in (None, [])
                or calendar.get("independent_trade_dates_sha256") not in ("", None)
                or calendar.get("independent_source") not in (None, "calendar_unavailable")):
            raise ValueError("calendar_unavailable 不得携带交易日绑定")
        if (trade_calendar is not None or trade_dates_probed is not None
                or independent_trade_dates is not None):
            raise ValueError("calendar_unavailable 不得携带外部交易日历")
        trusted_calendar = None
    else:
        raise ValueError("trade calendar status 非法")
    expected = build_m05_state(pd.DataFrame([
        {"trade_date": pt["trade_date"],
         "iv_value": pt["iv_value"],
         "iv_percentile_252d": pt["iv_percentile_252d"]}
        for pt in summary["series"]
    ]), trade_calendar=trusted_calendar)
    state_fields = (
        "iv_change_abs_1d_pctpt", "rule3_status", "awakening_status",
        "cash_reclaim_pct", "awakening_baseline_iv", "awakening_trigger_date",
        "awakening_release_date",
    )
    def _normalise_state_value(value):
        if value is None:
            return None
        try:
            if pd.isna(value):
                return None
        except (TypeError, ValueError):
            pass
        return value

    def _state_values_equal(expected_value, actual_value):
        expected_value = _normalise_state_value(expected_value)
        actual_value = _normalise_state_value(actual_value)
        if (isinstance(expected_value, (int, float))
                and not isinstance(expected_value, bool)
                and isinstance(actual_value, (int, float))
                and not isinstance(actual_value, bool)):
            return math.isclose(float(expected_value), float(actual_value), rel_tol=0.0, abs_tol=1e-6)
        return expected_value == actual_value

    for index, expected_row in expected.iterrows():
        actual = summary["series"][index]
        for field in state_fields:
            if not _state_values_equal(expected_row[field], actual.get(field)):
                raise ValueError(f"M0.5 state field {field} 与 IV series 不一致")
    latest = summary["series"][-1] if summary["series"] else {
        "trade_date": None, "iv_change_abs_1d_pctpt": None,
        "rule3_status": "unknown", "awakening_status": "unknown",
        "cash_reclaim_pct": None, "awakening_baseline_iv": None,
        "awakening_trigger_date": None, "awakening_release_date": None,
    }
    awakening = summary.get("awakening")
    if not isinstance(awakening, dict):
        raise ValueError("schema 1.2.0 缺少 M0.5 awakening state")
    mapping = {
        "trade_date": "trade_date",
        "iv_change_abs_1d_pctpt": "iv_change_abs_1d_pctpt",
        "rule3_status": "rule3_status",
        "status": "awakening_status",
        "cash_reclaim_pct": "cash_reclaim_pct",
        "baseline_iv": "awakening_baseline_iv",
        "trigger_date": "awakening_trigger_date",
        "release_date": "awakening_release_date",
    }
    for target, source in mapping.items():
        if not _state_values_equal(latest.get(source), awakening.get(target)):
            raise ValueError(f"M0.5 awakening.{target} 与最新 series 不一致")
    if awakening.get("production_effect_enabled") is not False:
        raise ValueError("第 1 刀 M0.5 生产端不得提前启用 production effect")
    if awakening.get("source") != AWAKENING_STATE_SOURCE:
        raise ValueError("M0.5 awakening source 不匹配")


def validate_feed_artifact(summary: dict, *, trade_calendar=None,
                           trade_dates_probed=None,
                           independent_trade_dates=None) -> None:
    """Validate schema and state binding at every sanctioned read/write door."""
    try:
        with open(SCHEMA_PATH, "r", encoding="utf-8") as handle:
            jsonschema.validate(summary, json.load(handle))
    except (OSError, json.JSONDecodeError, jsonschema.ValidationError) as exc:
        raise ValueError(f"IV feed schema validation failed: {type(exc).__name__}") from exc
    validate_feed_summary_consistency(
        summary, trade_calendar=trade_calendar, trade_dates_probed=trade_dates_probed,
        independent_trade_dates=independent_trade_dates,
    )


def validated_m05_series(summary: dict) -> list[dict]:
    """Return M0.5 rows only after the sanctioned artifact validation gate.

    A valid legacy 1.1.0 artifact remains readable for non-M0.5 consumers, but
    it deliberately yields no M0.5 rows.  Any 1.1.0 artifact carrying M0.5
    content is rejected by ``validate_feed_artifact`` before this point.
    """
    validate_feed_artifact(summary)
    if str(summary.get("schema_version") or "") != SCHEMA_VERSION:
        return []
    return list(summary.get("series") or [])


def write_feed(summary: dict, out_path: str, *, trade_calendar=None,
               trade_dates_probed=None, independent_trade_dates=None) -> None:
    """唯一 sanctioned 写盘路径:schema + consistency 校验后原子写。"""
    validate_feed_artifact(summary, trade_calendar=trade_calendar,
                           trade_dates_probed=trade_dates_probed,
                           independent_trade_dates=independent_trade_dates)
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    tmp = str(out_path) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2, allow_nan=False)
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
                                 datetime.now().astimezone().isoformat(timespec="seconds"),
                                 trade_calendar=report.get("trade_calendar"),
                                 calendar_source="tushare.trade_cal+fund_daily",
                                 trade_dates_probed=report.get("trade_dates_probed_dates"),
                                 independent_trade_dates=report.get("underlier_trade_dates"))
    latest_pct = summary["series"][-1]["iv_percentile_252d"] if summary["series"] else None
    if latest_pct is None:
        raise SystemExit(f"[FATAL] built feed 无可用最新 252d 分位(n_days={summary['n_days']} < MIN_ROLL_OBS={MIN_ROLL_OBS});"
                         "不写盘 — 需取更多历史交易日。Slice B 收不到能驱动 Rule3/M0.5/M1 的 feed。")
    write_feed(summary, args.out,
               trade_calendar=report.get("trade_calendar"),
               trade_dates_probed=report.get("trade_dates_probed_dates"),
               independent_trade_dates=report.get("underlier_trade_dates"))
    print(f"[iv_build] n_days={summary['n_days']}; latest_iv_pct={latest_pct}; feed -> {args.out}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A-short 50ETF IV feed — 可行性探测 runner(probe-first, PIT-safe).

Tushare 不直接给隐含波动率;50ETF IV 须自算(BS 反解 ATM/恒定到期 → IV 指数 → 252日分位)。
本 probe 评估 510050.SH 期权 + 标的价格能否支撑 **PIT 安全的** ATM IV 反解,再决定是否建 feed。

`computable=true` 的完整前提(第一性原理,非"表里有几行"):
- 真日期:`as_of / trade_date / maturity_date` 必须是合法 YYYYMMDD(`yyyyyyyy` 这类直接作废)。
- PIT:opt_daily / underlier 只取 `trade_date <= as_of`(杜绝未来数据泄漏)。
- 标的身份:underlier 必须是 510050.SH,且 `close>0` 的 PIT 有效天数足够(不是"任意一天正")。
- 必填字段 + 合约/双边/行权价档够。
- **可报价到期分布**:有有效报价的合约要覆盖 **≥2 个未来到期**(只在 opt_basic 里有、无报价的到期不算)。
- opt_daily PIT 覆盖天数、basic↔daily 合约重叠、期权/标的 **共同 PIT 日**、**共同日有效报价天数**(不是行数;杜绝集中单日)。
- ATM:在最新共同 PIT 日,有有效报价合约的行权价**跨越标的现价**。

纯函数 `assess_opt_coverage` / `validate_probe_summary_consistency`(合成 fixture 可测);真实
Tushare 调用在 `main` 薄层,**执行期用户授权**。不动 production / egs_main / V14.2,不真钱、不 ship-gate。
"""
from __future__ import annotations

import argparse
import json

import pandas as pd

SCHEMA_NAME = "a_short_iv_feed_probe_summary"
SCHEMA_VERSION = "1.0.0"
UNDERLYING = "510050.SH"

MIN_CONTRACTS = 20
MIN_STRIKES = 5
MIN_QUOTABLE_FUTURE_MATURITIES = 2     # 有有效报价覆盖的未来到期(近月+次月)
MIN_OPT_PIT_COVERAGE_DAYS = 15
MIN_BASIC_DAILY_OVERLAP = 20
MIN_COMMON_DATES = 15
MIN_VALID_QUOTE_DAYS = 15              # 共同日有效报价的天数(非行数)
MIN_UNDERLIER_DAYS = 15               # 标的 close>0 的 PIT 有效天数
REQUIRED_OPT_BASIC_FIELDS = ["ts_code", "call_put", "exercise_price", "maturity_date"]
REQUIRED_OPT_DAILY_FIELDS = ["ts_code", "trade_date", "settle", "close", "vol", "oi"]


def _valid_date_mask(s: pd.Series) -> pd.Series:
    """合法 YYYYMMDD 真日期的布尔掩码(yyyyyyyy / 空 → False)。"""
    return pd.to_datetime(s.astype(str), format="%Y%m%d", errors="coerce").notna()


def _is_valid_yyyymmdd(value) -> bool:
    return bool(_valid_date_mask(pd.Series([str(value)])).iloc[0])


def _pit_filter(df: pd.DataFrame, as_of: str) -> pd.DataFrame:
    """只保留 trade_date 合法且 <= as_of 的行(PIT)。"""
    if df is None or df.empty or "trade_date" not in df.columns:
        return pd.DataFrame()
    td = df["trade_date"].astype(str)
    return df[_valid_date_mask(td) & (td <= str(as_of))].copy()


def assess_opt_coverage(opt_basic_df: pd.DataFrame, opt_daily_df: pd.DataFrame,
                        underlier_daily_df: pd.DataFrame, as_of: str) -> dict:
    """评估 510050.SH 期权 + 标的价格能否 PIT-安全地 BS 反解 ATM IV。输入应已按标的过滤。"""
    reasons: list[str] = []
    as_of = str(as_of)
    basic = opt_basic_df if opt_basic_df is not None else pd.DataFrame()
    daily_raw = opt_daily_df if opt_daily_df is not None else pd.DataFrame()
    und_raw = underlier_daily_df if underlier_daily_df is not None else pd.DataFrame()

    as_of_is_valid_date = _is_valid_yyyymmdd(as_of)

    basic_missing = [f for f in REQUIRED_OPT_BASIC_FIELDS if f not in basic.columns]
    if basic_missing:
        reasons.append(f"opt_basic 缺字段: {','.join(basic_missing)}")
    daily_missing = [f for f in REQUIRED_OPT_DAILY_FIELDS if f not in daily_raw.columns]
    has_required_fields = len(daily_missing) == 0
    if daily_missing:
        reasons.append(f"opt_daily 缺字段: {','.join(daily_missing)}")

    # 标的身份 + PIT + close>0 有效天数
    underlier_is_510050 = ("ts_code" in und_raw.columns and not und_raw.empty
                           and (und_raw["ts_code"].astype(str) == UNDERLYING).any())
    if "ts_code" in und_raw.columns and not und_raw.empty:
        und = und_raw[und_raw["ts_code"].astype(str) == UNDERLYING].copy()
    else:
        und = pd.DataFrame()                     # 无 ts_code → 无法核身份 → 作废
    und = _pit_filter(und, as_of)
    und_valid_dates: set = set()
    if "close" in und.columns and not und.empty:
        uc = pd.to_numeric(und["close"], errors="coerce")
        und_valid_dates = set(und[uc.fillna(0) > 0]["trade_date"].astype(str))
    underlier_valid_days = len(und_valid_dates)

    # opt_daily PIT
    daily = _pit_filter(daily_raw, as_of)
    opt_pit_dates = set(daily["trade_date"].astype(str)) if ("trade_date" in daily.columns and not daily.empty) else set()
    opt_pit_coverage_days = len(opt_pit_dates)

    n_contracts = int(len(basic))
    n_call = n_put = n_strikes = n_maturities = n_valid_date_maturities = n_future_maturities = None
    future_maturity_set: set = set()
    if "call_put" in basic.columns and not basic.empty:
        cp = basic["call_put"].astype(str).str.upper()
        n_call = int(cp.isin(["C", "CALL", "认购"]).sum())
        n_put = int(cp.isin(["P", "PUT", "认沽"]).sum())
    if "exercise_price" in basic.columns and not basic.empty:
        n_strikes = int(pd.to_numeric(basic["exercise_price"], errors="coerce").dropna().nunique())
    if "maturity_date" in basic.columns and not basic.empty:
        md = basic["maturity_date"].dropna().astype(str)
        n_maturities = int(md.nunique())
        valid_md = md[_valid_date_mask(md)]            # 真日期才算
        n_valid_date_maturities = int(valid_md.nunique())
        future_maturity_set = set(valid_md[valid_md > as_of])
        n_future_maturities = int(len(future_maturity_set))

    overlap = set()
    if "ts_code" in basic.columns and "ts_code" in daily.columns and not basic.empty and not daily.empty:
        overlap = set(basic["ts_code"].dropna().astype(str)) & set(daily["ts_code"].dropna().astype(str))
    overlap_count = len(overlap)

    common_dates = opt_pit_dates & und_valid_dates
    common_pit_days = len(common_dates)

    # 共同 PIT 日 + 重叠合约上的有效非零报价(天数 + 行数 + 合约集 + 有报价的日期集 + 明细)
    valid_quote_rows = valid_quote_days = 0
    valid_quote_codes: set = set()
    valid_quote_dates: set = set()
    dv = pd.DataFrame()
    if has_required_fields and overlap_count > 0 and common_dates and not daily.empty:
        d = daily[daily["ts_code"].astype(str).isin(overlap)
                  & daily["trade_date"].astype(str).isin(common_dates)].copy()
        settle = pd.to_numeric(d.get("settle"), errors="coerce")
        close = pd.to_numeric(d.get("close"), errors="coerce")
        dv = d[(settle.fillna(0) > 0) | (close.fillna(0) > 0)].copy()
        dv["_td"] = dv["trade_date"].astype(str)
        valid_quote_rows = int(len(dv))
        valid_quote_dates = set(dv["_td"])
        valid_quote_days = len(valid_quote_dates)
        valid_quote_codes = set(dv["ts_code"].astype(str))

    # 有有效报价的合约覆盖的未来到期数(只在 opt_basic 里、无报价的到期不算)
    n_quotable_future_maturities = 0
    if "maturity_date" in basic.columns and future_maturity_set and valid_quote_codes:
        bq = basic[basic["ts_code"].astype(str).isin(valid_quote_codes)]
        n_quotable_future_maturities = len(set(bq["maturity_date"].astype(str)) & future_maturity_set)

    # ATM:用**最新可用估值日**(最新有有效报价的共同 PIT 日)当天的有效报价合约 + 当天标的现价,
    # 而不是全窗口历史报价(否则最新日全 0 时会用陈旧报价虚报)。行权价(>0)需跨越现价。
    spot_ref = None
    n_strikes_with_valid_quotes = 0
    atm_bracketed = False
    latest_usable_date = None
    if valid_quote_dates and underlier_is_510050 and "exercise_price" in basic.columns and not dv.empty:
        latest_usable_date = max(valid_quote_dates)
        codes_on_latest = set(dv[dv["_td"] == latest_usable_date]["ts_code"].astype(str))
        ur = und[und["trade_date"].astype(str) == latest_usable_date]
        sv = pd.to_numeric(ur.get("close"), errors="coerce").dropna() if not ur.empty else pd.Series(dtype=float)
        if codes_on_latest and not sv.empty:
            spot_ref = float(sv.iloc[0])
            strikes = pd.to_numeric(
                basic.loc[basic["ts_code"].astype(str).isin(codes_on_latest), "exercise_price"],
                errors="coerce").dropna()
            strikes = strikes[strikes > 0]
            n_strikes_with_valid_quotes = int(strikes.nunique())
            if not strikes.empty:
                atm_bracketed = bool((strikes <= spot_ref).any() and (strikes >= spot_ref).any())

    if not as_of_is_valid_date:
        reasons.append(f"as_of {as_of} 不是合法日历日期")
    if not underlier_is_510050:
        reasons.append("标的不是 510050.SH(或无 ts_code 列核验)")
    if n_contracts < MIN_CONTRACTS:
        reasons.append(f"合约数 {n_contracts} < {MIN_CONTRACTS}")
    if not (n_call and n_put):
        reasons.append("认购/认沽不齐(BS 反解需双边)")
    if not (n_strikes and n_strikes >= MIN_STRIKES):
        reasons.append(f"行权价档数 {n_strikes} < {MIN_STRIKES}")
    if n_quotable_future_maturities < MIN_QUOTABLE_FUTURE_MATURITIES:
        reasons.append(f"可报价未来到期数 {n_quotable_future_maturities} < {MIN_QUOTABLE_FUTURE_MATURITIES}(需有报价的近月+次月)")
    if opt_pit_coverage_days < MIN_OPT_PIT_COVERAGE_DAYS:
        reasons.append(f"opt_daily PIT 覆盖 {opt_pit_coverage_days} 日 < {MIN_OPT_PIT_COVERAGE_DAYS}")
    if overlap_count < MIN_BASIC_DAILY_OVERLAP:
        reasons.append(f"basic↔daily 合约重叠 {overlap_count} < {MIN_BASIC_DAILY_OVERLAP}")
    if common_pit_days < MIN_COMMON_DATES:
        reasons.append(f"期权/标的共同 PIT 日 {common_pit_days} < {MIN_COMMON_DATES}")
    if valid_quote_days < MIN_VALID_QUOTE_DAYS:
        reasons.append(f"共同日有效报价天数 {valid_quote_days} < {MIN_VALID_QUOTE_DAYS}(防集中单日)")
    if underlier_valid_days < MIN_UNDERLIER_DAYS:
        reasons.append(f"标的 close>0 的 PIT 天数 {underlier_valid_days} < {MIN_UNDERLIER_DAYS}")
    if not atm_bracketed:
        reasons.append("有效报价合约的行权价未跨越标的现价(无法定平值/插值 ATM)")

    computable = (
        as_of_is_valid_date
        and not basic_missing and has_required_fields and underlier_is_510050
        and n_contracts >= MIN_CONTRACTS
        and bool(n_call) and bool(n_put)
        and (n_strikes or 0) >= MIN_STRIKES
        and n_quotable_future_maturities >= MIN_QUOTABLE_FUTURE_MATURITIES
        and opt_pit_coverage_days >= MIN_OPT_PIT_COVERAGE_DAYS
        and overlap_count >= MIN_BASIC_DAILY_OVERLAP
        and common_pit_days >= MIN_COMMON_DATES
        and valid_quote_days >= MIN_VALID_QUOTE_DAYS
        and underlier_valid_days >= MIN_UNDERLIER_DAYS
        and atm_bracketed
    )
    return {
        "as_of_is_valid_date": bool(as_of_is_valid_date),
        "latest_usable_date": latest_usable_date,
        "n_contracts": n_contracts,
        "n_call": n_call,
        "n_put": n_put,
        "n_strikes": n_strikes,
        "n_maturities": n_maturities,
        "n_valid_date_maturities": n_valid_date_maturities,
        "n_future_maturities": n_future_maturities,
        "n_quotable_future_maturities": n_quotable_future_maturities,
        "opt_basic_missing_fields": basic_missing,
        "opt_daily_has_required_fields": has_required_fields,
        "opt_daily_missing_fields": daily_missing,
        "opt_pit_coverage_days": opt_pit_coverage_days,
        "basic_daily_overlap_count": overlap_count,
        "common_pit_days": common_pit_days,
        "valid_quote_days": valid_quote_days,
        "valid_quote_rows": valid_quote_rows,
        "underlier_is_510050": bool(underlier_is_510050),
        "underlier_valid_days": underlier_valid_days,
        "spot_ref": spot_ref,
        "n_strikes_with_valid_quotes": n_strikes_with_valid_quotes,
        "atm_bracketed": bool(atm_bracketed),
        "computable": bool(computable),
        "reasons": reasons,
    }


def build_probe_summary(assessment: dict, as_of: str, generated_at: str) -> dict:
    return {
        "schema_name": SCHEMA_NAME,
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "as_of": as_of,
        "underlying": UNDERLYING,
        "thresholds": {
            "min_contracts": MIN_CONTRACTS,
            "min_strikes": MIN_STRIKES,
            "min_quotable_future_maturities": MIN_QUOTABLE_FUTURE_MATURITIES,
            "min_opt_pit_coverage_days": MIN_OPT_PIT_COVERAGE_DAYS,
            "min_basic_daily_overlap": MIN_BASIC_DAILY_OVERLAP,
            "min_common_dates": MIN_COMMON_DATES,
            "min_valid_quote_days": MIN_VALID_QUOTE_DAYS,
            "min_underlier_days": MIN_UNDERLIER_DAYS,
            "required_opt_basic_fields": list(REQUIRED_OPT_BASIC_FIELDS),
            "required_opt_daily_fields": list(REQUIRED_OPT_DAILY_FIELDS),
        },
        "assessment": assessment,
        "computable": bool(assessment["computable"]),
        "boundary": {
            "production": False,
            "real_money": False,
            "satisfies_ship_gate": False,
            "builds_iv_feed": False,
        },
    }


def validate_probe_summary_consistency(summary: dict) -> None:
    """顶层/assessment 不矛盾,且 computable=true ⇒ 每个 PIT/质量门都达标(防手搓虚报)。"""
    a = summary["assessment"]
    t = summary["thresholds"]
    if bool(summary["computable"]) != bool(a["computable"]):
        raise ValueError("顶层 computable 与 assessment.computable 不一致")
    if a["opt_daily_has_required_fields"] != (len(a["opt_daily_missing_fields"]) == 0):
        raise ValueError("opt_daily_has_required_fields 与 missing_fields 不一致")
    if a["computable"]:
        if a["reasons"]:
            raise ValueError("computable=true 却携带 blocking reasons")
        if not _is_valid_yyyymmdd(summary["as_of"]):
            raise ValueError("computable=true 但 as_of 非合法日历日期")
        latest_usable_date = a.get("latest_usable_date")
        if not isinstance(latest_usable_date, str) or not _is_valid_yyyymmdd(latest_usable_date):
            raise ValueError("computable=true with invalid latest_usable_date")
        if latest_usable_date > str(summary["as_of"]):
            raise ValueError("computable=true with latest_usable_date after as_of")
        spot_ref = pd.to_numeric(pd.Series([a.get("spot_ref")]), errors="coerce").iloc[0]
        if pd.isna(spot_ref) or float(spot_ref) <= 0:
            raise ValueError("computable=true with missing or non-positive spot_ref")
        gates = [
            bool(a["as_of_is_valid_date"]),
            not a["opt_basic_missing_fields"],
            a["opt_daily_has_required_fields"],
            a["underlier_is_510050"],
            a["n_contracts"] >= t["min_contracts"],
            (a["n_call"] or 0) > 0 and (a["n_put"] or 0) > 0,
            (a["n_strikes"] or 0) >= t["min_strikes"],
            a["n_quotable_future_maturities"] >= t["min_quotable_future_maturities"],
            a["opt_pit_coverage_days"] >= t["min_opt_pit_coverage_days"],
            a["basic_daily_overlap_count"] >= t["min_basic_daily_overlap"],
            a["common_pit_days"] >= t["min_common_dates"],
            a["valid_quote_days"] >= t["min_valid_quote_days"],
            a["underlier_valid_days"] >= t["min_underlier_days"],
            a["n_strikes_with_valid_quotes"] > 0,
            bool(a["atm_bracketed"]),
        ]
        if not all(gates):
            raise ValueError("computable=true 但有 PIT/质量门未达标")


def main(argv=None):
    p = argparse.ArgumentParser(description="A-short 50ETF IV feed feasibility probe (probe-first, PIT-safe)")
    p.add_argument("--as-of", required=True, help="YYYYMMDD")
    p.add_argument("--out", required=True)
    p.add_argument("--confirm-fetch-authorized", action="store_true",
                   help="确认用户已授权本次 Tushare opt_basic/opt_daily/标的价格 探测调用")
    args = p.parse_args(argv)
    if not args.confirm_fetch_authorized:
        raise SystemExit("[FATAL] 需 --confirm-fetch-authorized:本 probe 会调用 Tushare,须用户授权")
    # NOTE: 真实 opt_basic/opt_daily/510050 daily 调用 + 过滤在执行期接线;
    # 纯评估 assess_opt_coverage / build_probe_summary / validate_probe_summary_consistency 已单测。
    raise SystemExit("[INFO] Tushare opt_basic/opt_daily/underlier fetch wiring is execution-time (authorized) work; "
                     "pure assessment contract is unit-tested. See design doc + tests.")


if __name__ == "__main__":
    main()

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
import os
import re
import sys
import time
from pathlib import Path

import jsonschema
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.a_short_tushare_client import init_tushare_pro

SCHEMA_NAME = "a_short_iv_feed_probe_summary"
SCHEMA_VERSION = "1.0.0"
UNDERLYING = "510050.SH"
SCHEMA_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "schemas", "a_short_iv_feed_probe_summary.schema.json")
FAILURE_RECEIPT_SCHEMA_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "schemas", "a_short_iv_feed_failure_receipt.schema.json",
)

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
OPT_DAILY_MAX_ATTEMPTS = 3
OPT_DAILY_RETRY_BACKOFF_SECONDS = 0.25
MAX_UNRECOVERED_OPT_DAILY_FAILURES = 1
RETRYABLE_OPT_DAILY_ERROR_CATEGORIES = frozenset({
    "rate_limit",
    "provider_server",
    "network",
})


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


def filter_50etf_options(opt_basic_df: pd.DataFrame) -> pd.DataFrame:
    """从 opt_basic 过滤出 50ETF(510050)期权。Tushare opt_basic 无干净标的列,
    用 name 含 '50ETF' 识别(执行期实测;识别不到 → 空 → 探测自然报 not computable)。"""
    if opt_basic_df is None or opt_basic_df.empty:
        return pd.DataFrame()
    if "name" not in opt_basic_df.columns:
        return opt_basic_df.iloc[0:0].copy()
    return opt_basic_df[opt_basic_df["name"].astype(str).str.contains("50ETF", na=False)].copy()


def run_probe(opt_basic_df: pd.DataFrame, opt_daily_df: pd.DataFrame,
              underlier_df: pd.DataFrame, as_of: str, generated_at: str) -> dict:
    """纯编排(无 I/O,可测):过滤 50ETF → 限定 opt_daily 到这些合约 → assess → build summary。"""
    basic = filter_50etf_options(opt_basic_df)
    codes = set(basic["ts_code"].astype(str)) if ("ts_code" in basic.columns and not basic.empty) else set()
    daily = opt_daily_df if opt_daily_df is not None else pd.DataFrame()
    if codes and not daily.empty and "ts_code" in daily.columns:
        daily = daily[daily["ts_code"].astype(str).isin(codes)].copy()
    else:
        daily = daily.iloc[0:0].copy() if not daily.empty else pd.DataFrame()
    assessment = assess_opt_coverage(basic, daily, underlier_df, as_of)
    return build_probe_summary(assessment, as_of, generated_at)


def write_probe_summary(summary: dict, out_path: str) -> None:
    """唯一 sanctioned 写盘路径:先 JSON schema + producer consistency 校验,再原子写。
    关闭 register forward-item(R-AIV consumer-validation):没有"不校验就写"的路径。"""
    with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
        schema = json.load(f)
    jsonschema.validate(summary, schema)               # 含 computable⇒字段 if/then 硬门
    validate_probe_summary_consistency(summary)         # 跨字段(latest≤as_of / spot>0 / 计数)硬门
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    tmp = str(out_path) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    os.replace(tmp, out_path)


def _categorize_error(exc) -> str:
    """粗分类(sanitized:只给类别,不外泄 token/url/raw 行)。"""
    msg = str(exc).lower()
    if any(k in msg for k in ("rate limit", "too many requests", "throttle", "429")):
        return "rate_limit"
    if any(k in msg for k in (
        "permission", "denied", "forbidden", "http 403", "403 forbidden",
        "权限", "积分", "quota", "没有", "无权",
    )):
        return "permission_or_quota"
    if any(k in msg for k in ("argument", "param", "field", "signature", "参数", "字段")):
        return "signature_or_args"
    if (any(k in msg for k in (
        "internal server", "service unavailable", "bad gateway", "gateway timeout", "gateway time-out",
        "http 500", "http 502", "http 503", "http 504",
    )) or re.search(r"\b5\d{2}\b", msg)):
        return "provider_server"
    if any(k in msg for k in (
        "timeout", "time-out", "timed out", "connection", "network", "ssl", "proxy", "max retries", "超时",
    )):
        return "network"
    return "other"


def _safe_pro_call(pro, method: str, **kw):
    """返回 (df, status)。status sanitized:endpoint / ok / rows / error_class / error_category,
    不含 token / url / 原始行。异常 → ok=False(供上层区分 provider 失败 vs 真无数据)。"""
    try:
        df = getattr(pro, method)(**kw)
        df = df if df is not None else pd.DataFrame()
        return df, {"endpoint": method, "ok": True, "rows": int(len(df)),
                    "error_class": None, "error_category": None}
    except Exception as exc:
        # sanitized:只打 endpoint/class/category,绝不 print str(exc)(可能含 url/token/raw 行)
        print(f"[probe] Tushare {method} 失败: {type(exc).__name__} ({_categorize_error(exc)})")
        return pd.DataFrame(), {"endpoint": method, "ok": False, "rows": 0,
                                "error_class": type(exc).__name__,
                                "error_category": _categorize_error(exc)}


def _safe_pro_call_with_retry(pro, method: str, *, max_attempts: int = 1,
                              retry_backoff_seconds: float = 0.0, sleep_fn=None, **kw):
    """Retry only transient/rate-limited calls; never retain exception text."""
    if max_attempts < 1:
        raise ValueError("max_attempts must be >= 1")
    sleeper = sleep_fn or time.sleep
    for attempt in range(1, max_attempts + 1):
        df, status = _safe_pro_call(pro, method, **kw)
        if status["ok"]:
            return df, {**status, "attempt_count": attempt, "retry_count": attempt - 1}
        if status["error_category"] not in RETRYABLE_OPT_DAILY_ERROR_CATEGORIES:
            return pd.DataFrame(), {**status, "attempt_count": attempt, "retry_count": attempt - 1}
        if attempt < max_attempts:
            sleeper(retry_backoff_seconds * (2 ** (attempt - 1)))
    return pd.DataFrame(), {**status, "attempt_count": max_attempts,
                             "retry_count": max_attempts - 1}


def build_fetch_failure_summary(report: dict, as_of: str) -> dict:
    """Create a strict, secret-safe operational receipt from failed endpoint statuses only."""
    grouped: dict[str, dict] = {}
    for status in report.get("endpoint_statuses") or []:
        if status.get("ok"):
            continue
        endpoint = str(status.get("endpoint") or "")
        group = grouped.setdefault(endpoint, {
            "endpoint": endpoint,
            "failure_count": 0,
            "total_attempt_count": 0,
            "error_categories": set(),
            "trade_dates": [],
        })
        group["failure_count"] += 1
        group["total_attempt_count"] += int(status.get("attempt_count") or 1)
        category = status.get("error_category")
        if category:
            group["error_categories"].add(str(category))
        trade_date = status.get("trade_date")
        if trade_date:
            group["trade_dates"].append(str(trade_date))

    failures = []
    for endpoint in sorted(grouped):
        group = grouped[endpoint]
        dates = sorted(set(group.pop("trade_dates")))
        group["error_categories"] = sorted(group["error_categories"])
        group["first_trade_date"] = dates[0] if dates else None
        group["last_trade_date"] = dates[-1] if dates else None
        failures.append(group)
    return {
        "schema_name": "a_short_iv_feed_failure_receipt",
        "schema_version": "1.0.0",
        "as_of": str(as_of),
        "status": "failed",
        "reason": "provider_call_failure",
        "trade_dates_planned": int(report.get("trade_dates_planned") or 0),
        "trade_dates_probed": int(report.get("trade_dates_probed") or 0),
        "retry_recovered_count": len(report.get("retry_recoveries") or []),
        "opt_daily_fail_fast_triggered": bool(report.get("opt_daily_fail_fast_triggered")),
        "failures": failures,
    }


def validate_fetch_failure_summary(summary: dict) -> None:
    """Validate the receipt shape and semantic dates before it is written."""
    with open(FAILURE_RECEIPT_SCHEMA_PATH, "r", encoding="utf-8") as f:
        jsonschema.validate(summary, json.load(f))
    if not _is_valid_yyyymmdd(summary["as_of"]):
        raise ValueError("failure receipt as_of is not a valid calendar date")
    if summary["trade_dates_probed"] > summary["trade_dates_planned"]:
        raise ValueError("failure receipt probed dates exceed planned dates")
    for failure in summary["failures"]:
        for field in ("first_trade_date", "last_trade_date"):
            value = failure[field]
            if value is not None and not _is_valid_yyyymmdd(value):
                raise ValueError(f"failure receipt {field} is not a valid calendar date")


def write_fetch_failure_summary(summary: dict, out_path: str) -> None:
    """Atomically write only validated, sanitized operational failure evidence."""
    validate_fetch_failure_summary(summary)
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    tmp = str(out_path) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    os.replace(tmp, out_path)


def fetch_probe_inputs(pro, as_of: str, lookback_days: int = 40, max_trade_dates: int = 25,
                       sleep_fn=None):
    """执行期:拉 SSE 期权合约/行情 + 510050 标的价。返回 (opt_basic, opt_daily, underlier, report)。
    report 含 per-endpoint sanitized status + had_provider_error(任一端点抛异常即 True),
    供 main 区分 provider 失败(中止、不写 summary) vs 真·覆盖不足(写 not-computable)。
    `max_trade_dates` 截取最近 N 个交易日的 opt_daily:probe 默认 25(smoke);IV-feed build 传大值
    (≥ ROLL_WINDOW)以便算 252d 分位(R-ASHORT-IVFEED-BUILD-FETCH-WINDOW-NO-PERCENTILE)。"""
    from datetime import datetime, timedelta
    start = (datetime.strptime(as_of, "%Y%m%d") - timedelta(days=lookback_days)).strftime("%Y%m%d")
    statuses = []
    opt_basic, s = _safe_pro_call(pro, "opt_basic", exchange="SSE",
                                  fields="ts_code,name,call_put,exercise_price,maturity_date,list_date,delist_date")
    statuses.append(s)
    cal, s = _safe_pro_call(pro, "trade_cal", exchange="SSE", start_date=start, end_date=as_of, is_open="1")
    statuses.append(s)
    dates = sorted(cal["cal_date"].astype(str).tolist())[-max_trade_dates:] if ("cal_date" in cal.columns and not cal.empty) else []
    frames = []
    opt_daily_attempted_dates = []
    retry_recoveries = []
    opt_daily_fail_fast_triggered = False
    unrecovered_opt_daily_failures = 0
    for d in dates:
        opt_daily_attempted_dates.append(d)
        od, s = _safe_pro_call_with_retry(
            pro, "opt_daily", max_attempts=OPT_DAILY_MAX_ATTEMPTS,
            retry_backoff_seconds=OPT_DAILY_RETRY_BACKOFF_SECONDS, sleep_fn=sleep_fn,
            trade_date=d, exchange="SSE", fields="ts_code,trade_date,settle,close,vol,oi",
        )
        if s["ok"] and s["retry_count"]:
            retry_recoveries.append({"endpoint": "opt_daily", "trade_date": d,
                                     "attempt_count": s["attempt_count"]})
        if not s["ok"]:
            statuses.append({**s, "trade_date": d})
            unrecovered_opt_daily_failures += 1
            if unrecovered_opt_daily_failures >= MAX_UNRECOVERED_OPT_DAILY_FAILURES:
                opt_daily_fail_fast_triggered = True
                break
        if not od.empty:
            frames.append(od)
    opt_daily = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    underlier, s = _safe_pro_call(pro, "fund_daily", ts_code=UNDERLYING, start_date=start, end_date=as_of,
                                  fields="ts_code,trade_date,close")
    statuses.append(s)
    had_provider_error = any(not st["ok"] for st in statuses)
    report = {
        "opt_basic_rows": int(len(opt_basic)), "opt_daily_rows": int(len(opt_daily)),
        "underlier_rows": int(len(underlier)), "trade_dates_planned": len(dates),
        "trade_dates_probed": len(opt_daily_attempted_dates),
        "endpoint_statuses": statuses, "had_provider_error": had_provider_error,
        "retry_recoveries": retry_recoveries,
        "opt_daily_fail_fast_triggered": opt_daily_fail_fast_triggered,
    }
    return opt_basic, opt_daily, underlier, report


def main(argv=None, pro_factory=None):
    from datetime import datetime
    p = argparse.ArgumentParser(description="A-short 50ETF IV feed feasibility probe (probe-first, PIT-safe)")
    p.add_argument("--as-of", required=True, help="YYYYMMDD")
    p.add_argument("--out", required=True)
    p.add_argument("--confirm-fetch-authorized", action="store_true",
                   help="确认用户已授权本次 Tushare opt_basic/opt_daily/fund_daily 探测调用")
    args = p.parse_args(argv)
    if not args.confirm_fetch_authorized:
        raise SystemExit("[FATAL] 需 --confirm-fetch-authorized:本 probe 会调用 Tushare,须用户授权")
    if not _is_valid_yyyymmdd(args.as_of):
        raise SystemExit(f"[FATAL] --as-of {args.as_of} 不是合法日历日期")
    if pro_factory is not None:
        pro = pro_factory()
    else:
        token = os.environ.get("TUSHARE_TOKEN")
        if not token:
            raise SystemExit("[FATAL] 需设置环境变量 TUSHARE_TOKEN")
        pro = init_tushare_pro(token)               # 不写 tk.csv;pin endpoint
    opt_basic, opt_daily, underlier, report = fetch_probe_inputs(pro, args.as_of)
    print(f"[probe] fetch report: rows(basic/daily/underlier)="
          f"{report['opt_basic_rows']}/{report['opt_daily_rows']}/{report['underlier_rows']}; "
          f"had_provider_error={report['had_provider_error']}; "
          f"statuses={[{k: st[k] for k in ('endpoint', 'ok', 'rows', 'error_class', 'error_category')} for st in report['endpoint_statuses']]}")
    # R-AIV-PROBE-EXEC-PROVIDER-ERROR-LINEAGE: provider 调用异常 → 中止、不写 summary,
    # 否则会把"无访问/签名错/配额"伪装成官方 not-computable 证据。
    if report["had_provider_error"]:
        raise SystemExit("[FATAL] provider-call failure(见上 fetch report);不写 not-computable 证据"
                         "(无法区分'无访问'与'无数据')。修端点/访问后重跑。")
    summary = run_probe(opt_basic, opt_daily, underlier, args.as_of,
                        datetime.now().astimezone().isoformat(timespec="seconds"))
    write_probe_summary(summary, args.out)             # 写盘前强制校验
    a = summary["assessment"]
    print(f"[probe] computable={summary['computable']}; reasons={a['reasons']}")
    print(f"[probe] summary -> {args.out}")


if __name__ == "__main__":
    main()

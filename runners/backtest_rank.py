#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Phase 2 rank backtest driver for the A-share short-term system.

Responsibilities:
1. Optionally generate historical candidate pools through A-EGS/egs_main.py,
   writing into an isolated backtest output tree (never the official tree).
2. Fetch a dedicated forward-daily price set (with adjustment factors and
   benchmark indices) that covers `[earliest_as_of, latest_as_of + max_window
   + buffer]`.
3. Default to excluding immature as-of dates (those without enough future
   trading days for the largest forward window).
4. Build rank/factor/Rule 6 statistics from generated analysis_input.json,
   using qfq-adjusted T+1 entry + costs + benchmark excess return.

Output isolation:
  * Generated candidate pools     -> result/a_short/backtest/generated/YYYYMMDD/
  * Forward daily cache           -> result/a_short/backtest/cache/forward_daily.pkl
  * Aggregate stats and reports   -> result/a_short/backtest/

The official screening output (result/a_short/YYYYMMDD/) is never touched.
"""

import argparse
import json
import os
import pickle
import subprocess
import sys
import time
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
RESULT_ROOT = ROOT / "result" / "a_short"
BACKTEST_DIR = RESULT_ROOT / "backtest"
GENERATED_DIR = BACKTEST_DIR / "generated"
BT_CACHE_DIR = BACKTEST_DIR / "cache"
FORWARD_DAILY_CACHE = BT_CACHE_DIR / "forward_daily.pkl"
EGS_SCRIPT = ROOT / "A-EGS" / "egs_main.py"
REPORT_SCHEMA = ROOT / "schemas" / "rank_backtest_report.schema.json"
EXPECTED_ANALYSIS_INPUT_SCHEMA = "1.1.0"


def _current_egs_version():
    """Read EGS_VERSION literal from egs_main.py without importing the module.
    Returns the version string (e.g. 'v7.6') or None if not found."""
    import re
    try:
        text = EGS_SCRIPT.read_text(encoding="utf-8")
    except OSError:
        return None
    m = re.search(r'^EGS_VERSION\s*=\s*"([^"]+)"', text, re.MULTILINE)
    return m.group(1) if m else None


def _current_egs_api_families():
    """Read EGS_API_FAMILIES list literal from egs_main.py via regex + ast.
    Single source of truth ensures data_health.json and backtest_report.json
    data_lineage.api_families.candidate_generation match. Returns the list,
    or a hardcoded fallback if parse fails (which would itself flag drift
    on next data_health check). Fallback is intentionally kept in sync; if
    you see this fallback get used, update both EGS_API_FAMILIES (canonical)
    and the fallback below."""
    import re, ast
    try:
        text = EGS_SCRIPT.read_text(encoding="utf-8")
    except OSError:
        text = ""
    m = re.search(r'^EGS_API_FAMILIES\s*=\s*(\[[^\]]+\])', text, re.MULTILINE)
    if m:
        try:
            parsed = ast.literal_eval(m.group(1))
            if isinstance(parsed, list) and all(isinstance(x, str) for x in parsed):
                return parsed
        except (ValueError, SyntaxError):
            pass
    # Fallback: must match egs_main.py:EGS_API_FAMILIES
    return [
        "daily", "daily_basic", "moneyflow", "fina_indicator",
        "stk_limit", "stock_basic", "trade_cal",
        "index_member_all", "index_member", "index_classify",
        "adj_factor", "concept", "concept_detail",
    ]

# A-share transaction cost defaults (double-sided, in pct):
#   buy commission 0.025% + sell commission 0.025% + stamp duty (sell) 0.05%
#   + transfer fee 0.001%*2 + slippage ~0.05%*2.
# Conservative round-trip: 0.16%.
DEFAULT_COST_PCT = 0.16

# Benchmarks: name -> Tushare index ts_code
BENCHMARKS = {
    "csi300": "000300.SH",
    "csi1000": "000852.SH",
}

ELIGIBLE_BENCHMARK = "eligible"
ESP_CAP_VALUE = 200.0


# ============================================================
# Generic helpers
# ============================================================

def parse_windows(value):
    windows = []
    for part in value.split(","):
        part = part.strip()
        if part:
            windows.append(int(part))
    return sorted(set(windows))


def _safe_load_analysis(path):
    """Return (data, ok). ok=False means the file should be regenerated."""
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return None, False
    if not isinstance(data, dict) or "candidates" not in data or "trade_date" not in data:
        return None, False
    return data, True


def load_analysis_inputs(source_root, date_filter=None):
    # None means "load all"; an empty collection means "load none".
    # This distinction prevents an empty selected_dates list from silently
    # turning into an all-generated backtest.
    date_filter = None if date_filter is None else set(date_filter)
    records = []
    for path in sorted(source_root.glob("20*/analysis_input.json")):
        data, ok = _safe_load_analysis(path)
        if not ok:
            print(f"[WARN] skip malformed {path.relative_to(ROOT)}")
            continue
        trade_date = data["trade_date"]
        if date_filter is not None and trade_date not in date_filter:
            continue
        for candidate in data.get("candidates", []):
            records.append(flatten_candidate(trade_date, path, candidate))
    return pd.DataFrame(records)


def flatten_candidate(trade_date, source_path, candidate):
    scores = candidate.get("scores", {})
    technical = candidate.get("technical", {})
    fundamental = candidate.get("fundamental", {})
    expectation = fundamental.get("expectation", {})
    selection = candidate.get("selection", {})
    derived_flags = candidate.get("derived_flags", {})
    data_quality = candidate.get("data_quality", {})
    event_risk = candidate.get("event_risk", {})
    rule6_checks = event_risk.get("rule6_checks", [])

    row = {
        "trade_date": trade_date,
        "source_file": str(source_path.relative_to(ROOT)),
        "ts_code": candidate.get("ts_code"),
        "name": candidate.get("name"),
        "l1_name": candidate.get("industry", {}).get("sw_l1_name"),
        "l2_name": candidate.get("industry", {}).get("sw_l2_name"),
        "board": candidate.get("board"),
        "rank": selection.get("rank"),
        "tier": selection.get("tier"),
        "final_score": scores.get("final_score"),
        "esp_score": scores.get("esp_score"),
        "cat_score": scores.get("cat_score"),
        "l4_score": scores.get("l4_score"),
        "l2_flags": scores.get("l2_flags"),
        "l4_flag": scores.get("l4_flag"),
        "entry_flag": selection.get("entry_flag"),
        "overheat_flag": derived_flags.get("overheat_flag"),
        "chasing_high": derived_flags.get("chasing_high"),
        "has_crash_veto": derived_flags.get("has_crash_veto"),
        "is_lock": derived_flags.get("is_lock"),
        "is_breakout": derived_flags.get("is_breakout"),
        "hard_veto": derived_flags.get("hard_veto"),
        "close": candidate.get("quote", {}).get("close"),
        "pct_20d": technical.get("pct_20d"),
        "pct_20d_n": technical.get("pct_20d_n"),
        "drawdown_20d": technical.get("drawdown_20d"),
        "q0_dt_yoy": expectation.get("q0_dt_yoy") or fundamental.get("profitability", {}).get("q0_dt_yoy"),
        "q1_dt_yoy": expectation.get("q1_dt_yoy") or fundamental.get("profitability", {}).get("q1_dt_yoy"),
        "esp_raw": expectation.get("esp_raw"),
        "completeness_score": data_quality.get("completeness_score"),
        "rule6_any_status": rule6_any_status(rule6_checks),
        "rule6_any_triggered": rule6_any_triggered(rule6_checks),
    }

    for check in rule6_checks:
        check_id = check.get("id")
        if not check_id:
            continue
        row[f"{check_id}_status"] = check.get("status")
        row[f"{check_id}_severity"] = check.get("severity")
        row[f"{check_id}_triggered"] = rule6_triggered(check)

    return row


def rule6_triggered(check):
    status = check.get("status")
    severity = check.get("severity")
    if status == "pass":
        return False
    if status in (None, "pending_data", "pending_llm", "unknown"):
        return None
    if severity in ("medium", "high", "critical"):
        return True
    return status in ("watch", "fail", "veto", "review")


def rule6_check_status(check):
    status = check.get("status")
    if rule6_triggered(check) is True:
        return "triggered"
    if status in ("pass", "pending_data", "pending_llm", "unknown"):
        return status
    if status is None:
        return "unknown"
    return str(status)


def rule6_any_status(rule6_checks):
    statuses = [rule6_check_status(check) for check in rule6_checks]
    if not statuses:
        return "unknown"
    if "triggered" in statuses:
        return "triggered"
    if "pending_llm" in statuses:
        return "pending_llm"
    if "pending_data" in statuses:
        return "pending_data"
    if "unknown" in statuses:
        return "unknown"
    return "pass"


def rule6_any_triggered(rule6_checks):
    status = rule6_any_status(rule6_checks)
    if status == "triggered":
        return True
    if status == "pass":
        return False
    return None


# ============================================================
# Tushare with retry
# ============================================================

def _pin_tushare_base_url():
    # tushare 1.4.29 hardcodes http://api.waditu.com/dataapi which 503s and
    # makes pro.<api>(...) silently return an empty DataFrame. Override the
    # default endpoint; allow TUSHARE_BASE_URL to point at a mirror if needed.
    import warnings
    from tushare.pro.client import DataApi
    base_url = os.environ.get("TUSHARE_BASE_URL", "https://api.tushare.pro/dataapi")
    attr = "_DataApi__http_url"
    if hasattr(DataApi, attr):
        setattr(DataApi, attr, base_url)
    else:
        warnings.warn(
            f"tushare.DataApi has no attribute {attr}; default URL not overridden "
            "(this codebase was written against tushare 1.4.29 internals)."
        )


def _tushare_pro():
    import tushare as ts
    _pin_tushare_base_url()
    token = os.environ.get("TUSHARE_TOKEN")
    if not token:
        raise RuntimeError("TUSHARE_TOKEN is required for backtest data fetches")
    ts.set_token(token)
    return ts.pro_api()


def _fn_label(fn):
    # tushare's pro.<api> are functools.partial objects without __name__.
    return (getattr(fn, "__name__", None)
            or getattr(getattr(fn, "func", None), "__name__", None)
            or repr(fn))


def _ts_call(fn, retries=3, base_delay=0.6, **kwargs):
    last_err = None
    name = _fn_label(fn)
    for attempt in range(retries):
        try:
            return fn(**kwargs)
        except Exception as e:
            last_err = e
            wait = base_delay * (2 ** attempt)
            print(f"[RETRY] {name} attempt {attempt + 1} failed ({e}); sleep {wait:.1f}s")
            time.sleep(wait)
    raise RuntimeError(f"Tushare call {name} failed after {retries} retries: {last_err}")


def _trade_calendar(pro, start_date, end_date):
    df = _ts_call(pro.trade_cal, exchange="SSE", start_date=start_date, end_date=end_date,
                  is_open="1", fields="cal_date")
    if df is None or df.empty:
        return []
    return sorted(df["cal_date"].astype(str).tolist())


def get_trade_dates_from_tushare(start_date, end_date):
    return _trade_calendar(_tushare_pro(), start_date, end_date)


def _shift_yyyymmdd(date_str, days):
    return (datetime.strptime(date_str, "%Y%m%d") + timedelta(days=days)).strftime("%Y%m%d")


# ============================================================
# Forward daily / adj / benchmark fetch + cache
# ============================================================

def fetch_forward_daily(asof_dates, max_window, buffer_days=5, refresh=False):
    """Fetch raw+adj daily prices and benchmark closes covering the forward window.

    Returns:
        dict with keys:
            "stocks"     -> DataFrame[ts_code, trade_date, open, close, adj_factor]
            "limits"     -> DataFrame[ts_code, trade_date, up_limit, down_limit]
            "benchmarks" -> dict[name -> DataFrame[trade_date, close]]
            "meta"       -> dict with date range / fetched_at / shape
    """
    if not asof_dates:
        return {"stocks": pd.DataFrame(columns=["ts_code", "trade_date", "open", "close", "adj_factor"]),
                "limits": pd.DataFrame(columns=["ts_code", "trade_date", "up_limit", "down_limit"]),
                "benchmarks": {},
                "meta": {"status": "no_asof"}}

    asof_sorted = sorted(set(asof_dates))
    start = asof_sorted[0]
    horizon_calendar_days = int((max_window + buffer_days + 2) * 1.7) + 14
    end = _shift_yyyymmdd(asof_sorted[-1], horizon_calendar_days)
    today = datetime.now().strftime("%Y%m%d")
    if end > today:
        end = today

    BT_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_signature = {"start": start, "end": end, "adj": "qfq_via_adj_factor",
                       "benchmarks": sorted(BENCHMARKS.keys())}

    if not refresh and FORWARD_DAILY_CACHE.exists():
        try:
            with FORWARD_DAILY_CACHE.open("rb") as f:
                cached = pickle.load(f)
            meta = cached.get("meta", {})
            stocks = cached.get("stocks")
            benches = cached.get("benchmarks", {})
            limits = cached.get("limits")
            sig_ok = (meta.get("start_date", "") <= start and meta.get("end_date", "") >= end
                      and meta.get("adj") == cache_signature["adj"]
                      and set(benches.keys()) >= set(BENCHMARKS.keys())
                      and isinstance(stocks, pd.DataFrame) and not stocks.empty
                      and isinstance(limits, pd.DataFrame) and not limits.empty)
            if sig_ok:
                print(f"[CACHE] forward_daily reused: {meta.get('start_date')}..{meta.get('end_date')} "
                      f"rows={len(stocks)} benchmarks={list(benches.keys())}")
                return {"stocks": stocks, "limits": limits, "benchmarks": benches, "meta": meta}
        except Exception as e:
            print(f"[CACHE] forward_daily ignored ({e}); will refetch.")

    print(f"[FETCH] forward_daily {start}..{end}")
    pro = _tushare_pro()
    trade_dates = _trade_calendar(pro, start, end)
    if not trade_dates:
        raise RuntimeError(f"Tushare trade_cal returned no dates for {start}..{end}")

    stock_frames = []
    adj_frames = []
    limit_frames = []
    for td in trade_dates:
        df = _ts_call(pro.daily, trade_date=td, fields="ts_code,trade_date,open,close")
        if df is not None and not df.empty:
            stock_frames.append(df)
        adj = _ts_call(pro.adj_factor, trade_date=td, fields="ts_code,trade_date,adj_factor")
        if adj is not None and not adj.empty:
            adj_frames.append(adj)
        lim = _ts_call(pro.stk_limit, trade_date=td, fields="ts_code,trade_date,up_limit,down_limit")
        if lim is not None and not lim.empty:
            limit_frames.append(lim)

    if not stock_frames:
        raise RuntimeError("Tushare pro.daily returned no rows for the forward window")
    stocks = pd.concat(stock_frames, ignore_index=True)
    stocks["trade_date"] = stocks["trade_date"].astype(str)
    adj_all = pd.concat(adj_frames, ignore_index=True) if adj_frames else \
        pd.DataFrame(columns=["ts_code", "trade_date", "adj_factor"])
    if not adj_all.empty:
        adj_all["trade_date"] = adj_all["trade_date"].astype(str)
        stocks = stocks.merge(adj_all, on=["ts_code", "trade_date"], how="left")
    else:
        stocks["adj_factor"] = 1.0
    stocks = stocks.drop_duplicates(subset=["ts_code", "trade_date"], keep="last")
    stocks = stocks.sort_values(["ts_code", "trade_date"]).reset_index(drop=True)
    # ffill within each ts_code, then fall back to 1.0 if a code has no adj_factor at all.
    stocks["adj_factor"] = stocks.groupby("ts_code")["adj_factor"].ffill()
    stocks["adj_factor"] = stocks["adj_factor"].fillna(1.0)

    limits = pd.concat(limit_frames, ignore_index=True) if limit_frames else \
        pd.DataFrame(columns=["ts_code", "trade_date", "up_limit", "down_limit"])
    if not limits.empty:
        limits["trade_date"] = limits["trade_date"].astype(str)
        limits = limits.drop_duplicates(subset=["ts_code", "trade_date"], keep="last")
        limits = limits.sort_values(["ts_code", "trade_date"]).reset_index(drop=True)

    benches = {}
    for name, ts_code in BENCHMARKS.items():
        bdf = _ts_call(pro.index_daily, ts_code=ts_code, start_date=start, end_date=end,
                       fields="trade_date,close")
        if bdf is None or bdf.empty:
            print(f"[WARN] benchmark {name} ({ts_code}) returned no rows")
            benches[name] = pd.DataFrame(columns=["trade_date", "close"])
            continue
        bdf["trade_date"] = bdf["trade_date"].astype(str)
        bdf = bdf.sort_values("trade_date").reset_index(drop=True)
        benches[name] = bdf

    meta = {"start_date": start, "end_date": end,
            "adj": cache_signature["adj"],
            "benchmarks": list(BENCHMARKS.keys()),
            "fetched_at": datetime.now().isoformat(timespec="seconds"),
            "stock_rows": int(len(stocks)),
            "stock_codes": int(stocks["ts_code"].nunique()),
            "limit_rows": int(len(limits))}

    with FORWARD_DAILY_CACHE.open("wb") as f:
        pickle.dump({"meta": meta, "stocks": stocks, "limits": limits, "benchmarks": benches}, f)
    print(f"[FETCH] forward_daily saved stocks={len(stocks)} codes={meta['stock_codes']} "
          f"limits={len(limits)} benchmarks={list(benches.keys())} -> {FORWARD_DAILY_CACHE.relative_to(ROOT)}")
    return {"stocks": stocks, "limits": limits, "benchmarks": benches, "meta": meta}


# ============================================================
# Forward return computation: qfq + T+1 open entry + costs + benchmark
# ============================================================

def _benchmark_returns(bench_df, base_date, future_date):
    if bench_df is None or bench_df.empty:
        return None
    cmap = dict(zip(bench_df["trade_date"], bench_df["close"]))
    b = cmap.get(base_date)
    f = cmap.get(future_date)
    if b is None or f is None or pd.isna(b) or pd.isna(f) or float(b) == 0:
        return None
    return (float(f) / float(b) - 1.0) * 100.0


def _fallback_limit_ratio(ts_code, name=None, board=None):
    symbol = str(ts_code).split(".")[0]
    name = "" if name is None else str(name)
    board = "" if board is None else str(board).lower()
    if "ST" in name.upper() or name.startswith("*ST"):
        return 1.05
    if board == "bj" or symbol.startswith(("8", "4", "920")):
        return 1.30
    if board in ("chinext", "star") or symbol.startswith(("300", "301", "688", "689")):
        return 1.20
    return 1.10


def _is_entry_limit_up(ts_code, name, board, trade_date, entry_open, base_close, limit_lookup):
    """Return (blocked, source). Prefer Tushare stk_limit; fallback to board rules."""
    lim = limit_lookup.get((ts_code, trade_date))
    if lim is not None and not pd.isna(lim) and float(lim) > 0:
        return float(entry_open) >= float(lim) * 0.999, "stk_limit"
    if base_close is None or pd.isna(base_close) or float(base_close) <= 0:
        return False, "missing_limit"
    ratio = _fallback_limit_ratio(ts_code, name=name, board=board)
    return float(entry_open) >= float(base_close) * ratio * 0.999, "fallback_board_rule"


def attach_forward_returns(samples, windows, daily_payload, cost_pct=DEFAULT_COST_PCT):
    samples = samples.copy()
    samples["entry_date"] = pd.NA
    samples["entry_unbuyable_reason"] = pd.NA
    for window in windows:
        samples[f"ret_{window}d_exit_date"] = pd.NA
        samples[f"ret_{window}d_close"] = pd.NA
        samples[f"ret_{window}d_t1"] = pd.NA
        samples[f"ret_{window}d_t1_net"] = pd.NA
        samples[f"ret_{window}d_status"] = "pending_no_future_price"
        for bname in BENCHMARKS:
            samples[f"ret_{window}d_{bname}"] = pd.NA
            samples[f"ret_{window}d_excess_{bname}"] = pd.NA

    stocks = daily_payload.get("stocks", pd.DataFrame())
    limits = daily_payload.get("limits", pd.DataFrame())
    benches = daily_payload.get("benchmarks", {})
    if samples.empty or stocks.empty:
        return samples

    trade_dates = sorted(stocks["trade_date"].dropna().astype(str).unique().tolist())
    date_pos = {date: idx for idx, date in enumerate(trade_dates)}

    cols = ["ts_code", "trade_date", "open", "close", "adj_factor"]
    lookup = {}
    for row in stocks[cols].itertuples(index=False):
        lookup[(row.ts_code, row.trade_date)] = (row.open, row.close, row.adj_factor)
    limit_lookup = {}
    if isinstance(limits, pd.DataFrame) and not limits.empty:
        for row in limits[["ts_code", "trade_date", "up_limit"]].itertuples(index=False):
            limit_lookup[(row.ts_code, str(row.trade_date))] = row.up_limit

    for idx, row in samples.iterrows():
        trade_date = str(row["trade_date"])
        ts_code = row["ts_code"]
        if trade_date not in date_pos:
            for window in windows:
                samples.at[idx, f"ret_{window}d_status"] = "pending_asof_not_in_future_cache"
            continue

        base_idx = date_pos[trade_date]
        # Need T+1 entry; if as_of itself is the very last trading day, no T+1.
        if base_idx + 1 >= len(trade_dates):
            for window in windows:
                samples.at[idx, f"ret_{window}d_status"] = "pending_no_t_plus_one"
            continue
        entry_date = trade_dates[base_idx + 1]
        entry_row = lookup.get((ts_code, entry_date))
        if entry_row is None or pd.isna(entry_row[0]) or pd.isna(entry_row[2]) or float(entry_row[0]) == 0:
            for window in windows:
                samples.at[idx, f"ret_{window}d_status"] = "pending_no_entry_price"
            continue
        entry_open, _entry_close, entry_adj = entry_row
        samples.at[idx, "entry_date"] = entry_date
        # base close (for close-to-close reference)
        base_row = lookup.get((ts_code, trade_date))
        base_close = base_row[1] if base_row else None
        base_adj = base_row[2] if base_row else None
        if base_close is None or pd.isna(base_close) or float(base_close) == 0:
            base_close = row.get("close")
            base_adj = entry_adj  # fallback

        blocked, block_source = _is_entry_limit_up(
            ts_code,
            row.get("name"),
            row.get("board"),
            entry_date,
            entry_open,
            base_close,
            limit_lookup,
        )
        if blocked:
            samples.at[idx, "entry_unbuyable_reason"] = f"limit_up:{block_source}"
            for window in windows:
                samples.at[idx, f"ret_{window}d_status"] = "pending_no_entry_limit_up"
            continue

        for window in windows:
            # T+1 open entry, then close on the Nth trading day after as_of.
            # Example: window=5 means buy T+1 open and exit T+5 close.
            exit_idx = base_idx + window
            if exit_idx >= len(trade_dates):
                samples.at[idx, f"ret_{window}d_status"] = "pending_immature_asof"
                continue
            exit_date = trade_dates[exit_idx]
            samples.at[idx, f"ret_{window}d_exit_date"] = exit_date
            exit_row = lookup.get((ts_code, exit_date))
            if exit_row is None or pd.isna(exit_row[1]) or pd.isna(exit_row[2]):
                samples.at[idx, f"ret_{window}d_status"] = "pending_missing_future_close"
                continue
            _exit_open, exit_close, exit_adj = exit_row

            # qfq-adjusted close-to-close
            try:
                cc = (float(exit_close) * float(exit_adj)) / (float(base_close) * float(base_adj)) - 1.0
                samples.at[idx, f"ret_{window}d_close"] = cc * 100.0
            except Exception:
                pass
            # qfq-adjusted T+1 open -> exit close
            try:
                t1 = (float(exit_close) * float(exit_adj)) / (float(entry_open) * float(entry_adj)) - 1.0
                t1_pct = t1 * 100.0
                samples.at[idx, f"ret_{window}d_t1"] = t1_pct
                samples.at[idx, f"ret_{window}d_t1_net"] = t1_pct - cost_pct
            except Exception:
                pass
            samples.at[idx, f"ret_{window}d_status"] = "ok"

            for bname in BENCHMARKS:
                bret = _benchmark_returns(benches.get(bname), entry_date, exit_date)
                if bret is not None:
                    samples.at[idx, f"ret_{window}d_{bname}"] = bret
                    t1_v = samples.at[idx, f"ret_{window}d_t1"]
                    if t1_v is not pd.NA and not pd.isna(t1_v):
                        samples.at[idx, f"ret_{window}d_excess_{bname}"] = float(t1_v) - bret

    return samples


# ============================================================
# Stats
# ============================================================

RET_VARIANTS = ["close", "t1", "t1_net"] + [f"excess_{b}" for b in BENCHMARKS] + [f"excess_{ELIGIBLE_BENCHMARK}"]


MIN_MONTHLY_OBS_FOR_T = 3  # 2 months gives std n-1=1 → wildly unstable t/Sharpe


def _cluster_stats(sub):
    """Compute std, monthly-clustered t-stat, monthly Sharpe from a DataFrame
    with columns ['trade_date', 'value']. Returns dict with None where
    sample size is insufficient.

    t-stat / Sharpe require >= MIN_MONTHLY_OBS_FOR_T distinct months with std>0.
    Below that, the n-1 denominator on std makes those metrics meaningless (e.g.
    n_m=2 with mean=+3% can show t=10 purely from sampling noise). std_pct is
    still emitted at n>=2 since pooled std is a sample-level summary.

    Why monthly clustering: same-month candidates share market regime and are
    not iid; treating all 180 samples as independent would overstate degrees
    of freedom. See memory/feedback-multidim-analysis.
    """
    vals = pd.to_numeric(sub["value"], errors="coerce")
    valid = sub.assign(value=vals).dropna(subset=["value"])
    out = {"std_pct": None, "monthly_t": None, "sharpe_monthly": None}
    if len(valid) < 2:
        return out
    out["std_pct"] = float(valid["value"].std())
    monthly = valid.groupby("trade_date")["value"].mean().dropna()
    if len(monthly) >= MIN_MONTHLY_OBS_FOR_T and monthly.std() > 0:
        mu_m, sd_m, n_m = monthly.mean(), monthly.std(), len(monthly)
        out["monthly_t"] = float(mu_m / (sd_m / np.sqrt(n_m)))
        out["sharpe_monthly"] = float(mu_m / sd_m)
    return out


def summarize_returns(samples, windows, subset="all", period_split="all"):
    """Aggregate stats per (window, variant). `subset` and `period_split` are
    labels that go into the output's identity columns so multiple slices
    (all / tier1_only × all / discovery / validation) can share one CSV
    without losing identity."""
    rows = []
    for window in windows:
        ok_status = samples[f"ret_{window}d_status"] == "ok"
        for variant in RET_VARIANTS:
            col = f"ret_{window}d_{variant}"
            if col not in samples.columns:
                continue
            sub = samples.loc[ok_status, ["trade_date", col]].rename(columns={col: "value"})
            ok = pd.to_numeric(sub["value"], errors="coerce").dropna()
            stats = _cluster_stats(sub)
            rows.append({
                "subset": subset,
                "period_split": period_split,
                "window": window,
                "variant": variant,
                "sample_count": int(len(samples)),
                "available_count": int(len(ok)),
                "pending_count": int(len(samples) - len(ok)),
                "mean_return_pct": float(ok.mean()) if len(ok) else None,
                "median_return_pct": float(ok.median()) if len(ok) else None,
                "std_pct": stats["std_pct"],
                "monthly_t": stats["monthly_t"],
                "sharpe_monthly": stats["sharpe_monthly"],
                "win_rate_pct": float((ok > 0).mean() * 100) if len(ok) else None,
            })
    return pd.DataFrame(rows)


def group_stats(samples, windows, group_col, label, variant="t1_net",
                subset="all", period_split="all"):
    rows = []
    if group_col not in samples.columns:
        return rows
    for window in windows:
        ret_col = f"ret_{window}d_{variant}"
        if ret_col not in samples.columns:
            continue
        for group_value, group_df in samples.groupby(group_col, dropna=False):
            sub = group_df[["trade_date", ret_col]].rename(columns={ret_col: "value"})
            ok = pd.to_numeric(sub["value"], errors="coerce").dropna()
            gv = "NaN" if pd.isna(group_value) else str(group_value)
            stats = _cluster_stats(sub)
            rows.append({
                "subset": subset,
                "period_split": period_split,
                "group_type": label,
                "group_field": group_col,
                "group_value": gv,
                "variant": variant,
                "window": window,
                "sample_count": int(len(group_df)),
                "available_count": int(len(ok)),
                "mean_return_pct": float(ok.mean()) if len(ok) else None,
                "median_return_pct": float(ok.median()) if len(ok) else None,
                "std_pct": stats["std_pct"],
                "monthly_t": stats["monthly_t"],
                "sharpe_monthly": stats["sharpe_monthly"],
                "win_rate_pct": float((ok > 0).mean() * 100) if len(ok) else None,
            })
    return rows


def monthly_stats(samples, windows, subset="all", period_split="all"):
    """Per (trade_date × variant × window) aggregates. Long format. Lets readers
    spot single-month dominance (e.g., Dec 2025 carrying the annual mean) and
    regime shifts (negative months clustered in H1) without re-computing.

    Rows with NaN trade_date are dropped: they cannot be attributed to a month
    and would render as a 'nan' bucket that pollutes time-series analysis.
    """
    rows = []
    for trade_date, dgrp in samples.groupby("trade_date", dropna=True):
        if pd.isna(trade_date):
            continue
        for window in windows:
            status_col = f"ret_{window}d_status"
            if status_col not in dgrp.columns:
                continue
            ok_status = dgrp[status_col] == "ok"
            for variant in RET_VARIANTS:
                col = f"ret_{window}d_{variant}"
                if col not in dgrp.columns:
                    continue
                ok = pd.to_numeric(dgrp.loc[ok_status, col], errors="coerce").dropna()
                rows.append({
                    "subset": subset,
                    "period_split": period_split,
                    "trade_date": str(trade_date),
                    "window": window,
                    "variant": variant,
                    "sample_count": int(len(dgrp)),
                    "available_count": int(len(ok)),
                    "mean_return_pct": float(ok.mean()) if len(ok) else None,
                    "median_return_pct": float(ok.median()) if len(ok) else None,
                    "std_pct": float(ok.std()) if len(ok) > 1 else None,
                    "win_rate_pct": float((ok > 0).mean() * 100) if len(ok) else None,
                })
    return pd.DataFrame(rows)


def build_group_columns(samples):
    samples = samples.copy()
    samples["rank_bucket"] = pd.cut(
        pd.to_numeric(samples["rank"], errors="coerce"),
        bins=[0, 5, 10, 15, 999],
        labels=["top_1_5", "top_6_10", "top_11_15", "other"],
    )
    samples["tier_group"] = samples["tier"].fillna("unknown").astype(str)
    samples["entry_flag_group"] = samples["entry_flag"].fillna("unknown").astype(str)
    samples["l4_flag_group"] = samples["l4_flag"].fillna("").astype(str)
    samples.loc[samples["l4_flag_group"].str.strip() == "", "l4_flag_group"] = "none"
    samples["has_l4_overheat"] = samples["l4_flag_group"].str.contains("OVERHEAT", na=False)
    samples["has_l4_breakout"] = samples["l4_flag_group"].str.contains("突破型", na=False)
    samples["has_l4_lock"] = samples["l4_flag_group"].str.contains("LOCK", na=False)
    samples["q0_dt_yoy_gt_200"] = pd.to_numeric(samples["q0_dt_yoy"], errors="coerce") > 200
    samples["q1_dt_yoy_gt_200"] = pd.to_numeric(samples["q1_dt_yoy"], errors="coerce") > 200
    samples["esp_raw_gt_200"] = pd.to_numeric(samples["esp_raw"], errors="coerce") > 200
    samples["l2_unknown"] = samples.get("l2_name", pd.Series("", index=samples.index)).fillna("").astype(str).isin(["未知", "unknown", ""])
    samples["final_score_bucket"] = pd.cut(
        pd.to_numeric(samples["final_score"], errors="coerce"),
        bins=[-1, 70, 80, 90, 101],
        labels=["lt_70", "70_80", "80_90", "90_plus"],
    )
    samples["final_score_bucket_fine"] = pd.cut(
        pd.to_numeric(samples["final_score"], errors="coerce"),
        bins=[-1, 60, 70, 75, 80, 85, 90, 101],
        labels=["lt_60", "60_70", "70_75", "75_80", "80_85", "85_90", "90_plus"],
    )
    samples["data_quality_bucket"] = pd.cut(
        pd.to_numeric(samples["completeness_score"], errors="coerce"),
        bins=[-1, 75, 90, 101],
        labels=["lt_75", "75_90", "90_plus"],
    )
    samples["risk_reasons"] = samples.apply(_risk_reasons_for_row, axis=1)
    return samples


def _risk_reasons_for_row(row):
    reasons = []
    if bool(row.get("chasing_high")) or str(row.get("entry_flag_group", "")) == "追高风险，周一确认":
        reasons.append("chasing_high")
    if bool(row.get("has_l4_overheat")) or bool(row.get("overheat_flag")):
        reasons.append("overheat")
    if bool(row.get("has_l4_lock")) or bool(row.get("is_lock")):
        reasons.append("lock")
    if bool(row.get("q0_dt_yoy_gt_200")) or bool(row.get("q1_dt_yoy_gt_200")) or bool(row.get("esp_raw_gt_200")):
        reasons.append("low_base_growth")
    if str(row.get("tier_group", "")) == "Tier2":
        reasons.append("tier2")
    if bool(row.get("l2_unknown")):
        reasons.append("unknown_industry")
    return "|".join(reasons) if reasons else "none"


PRIMARY_SUBSET = "tier1_only"  # main reporting view: Tier2 filler dilutes signal
LOW_TIER1_COUNT_THRESHOLD = 5


def build_date_warnings(samples, selected_dates,
                        low_tier1_threshold=LOW_TIER1_COUNT_THRESHOLD):
    """Build date-level health warnings for the JSON report.

    The primary report subset is Tier1-only. A selected date with very few
    Tier1 names is still useful for engineering validation, but should not be
    silently mixed into headline strategy interpretation.
    """
    warnings_out = []
    if samples is None or samples.empty:
        for trade_date in selected_dates:
            warnings_out.append({
                "trade_date": str(trade_date),
                "warning_type": "no_samples",
                "severity": "critical",
                "threshold": int(low_tier1_threshold),
                "sample_count": 0,
                "tier1_count": 0,
                "tier2_count": 0,
                "message": "Selected date has no loaded samples; report statistics cannot represent this period.",
            })
        return warnings_out

    df = samples.copy()
    if "tier_group" not in df.columns:
        df["tier_group"] = df.get("tier", pd.Series("unknown", index=df.index)).fillna("unknown").astype(str)
    selected_set = {str(d) for d in selected_dates}
    grouped_dates = set()

    for trade_date, dgrp in df.groupby("trade_date", dropna=True):
        trade_date = str(trade_date)
        grouped_dates.add(trade_date)
        if selected_set and trade_date not in selected_set:
            continue
        tier1_count = int((dgrp["tier_group"] == "Tier1").sum())
        tier2_count = int((dgrp["tier_group"] == "Tier2").sum())
        sample_count = int(len(dgrp))
        if tier1_count < low_tier1_threshold:
            severity = "critical" if tier1_count == 0 else "warning"
            warnings_out.append({
                "trade_date": trade_date,
                "warning_type": "low_tier1_count",
                "severity": severity,
                "threshold": int(low_tier1_threshold),
                "sample_count": sample_count,
                "tier1_count": tier1_count,
                "tier2_count": tier2_count,
                "message": (
                    f"Tier1 candidate count {tier1_count} is below "
                    f"{low_tier1_threshold}; treat Tier2 filler and this date's "
                    "headline strategy contribution as observation only."
                ),
            })

    for trade_date in sorted(selected_set - grouped_dates):
        warnings_out.append({
            "trade_date": trade_date,
            "warning_type": "no_samples",
            "severity": "critical",
            "threshold": int(low_tier1_threshold),
            "sample_count": 0,
            "tier1_count": 0,
            "tier2_count": 0,
            "message": "Selected date has no loaded samples; report statistics cannot represent this period.",
        })
    return warnings_out


def _factor_group_specs():
    return [
        ("rank_bucket", "rank"),
        ("tier_group", "tier"),
        ("entry_flag_group", "entry"),
        ("l4_flag_group", "technical_flag"),
        ("has_l4_overheat", "technical_flag"),
        ("has_l4_breakout", "technical_flag"),
        ("has_l4_lock", "technical_flag"),
        ("final_score_bucket", "score"),
        ("final_score_bucket_fine", "score"),
        ("data_quality_bucket", "data_quality"),
        ("l2_unknown", "data_quality"),
        ("overheat_flag", "risk_flag"),
        ("q0_dt_yoy_gt_200", "low_base_growth"),
        ("q1_dt_yoy_gt_200", "low_base_growth"),
        ("esp_raw_gt_200", "low_base_growth"),
    ]


def _build_stats_for_slice(samples, windows, subset_label, period_split_label):
    """Compute summary / factor / rule6 / monthly for ONE (subset, period_split) slice."""
    summary = summarize_returns(samples, windows, subset=subset_label, period_split=period_split_label)
    factor_rows = []
    for group_col, label in _factor_group_specs():
        factor_rows.extend(group_stats(samples, windows, group_col, label,
                                       subset=subset_label, period_split=period_split_label))
    rule6_rows = []
    rule6_status_cols = [c for c in samples.columns if c.startswith("rule6_") and c.endswith("_status")]
    for col in sorted(rule6_status_cols):
        rule6_rows.extend(group_stats(samples, windows, col, "rule6_status",
                                      subset=subset_label, period_split=period_split_label))
    monthly_df = monthly_stats(samples, windows, subset=subset_label, period_split=period_split_label)
    return summary, pd.DataFrame(factor_rows), pd.DataFrame(rule6_rows), monthly_df


def _period_split_masks(samples, split_date):
    """Return [(label, mask)] for the period_split dimension.

    Always includes 'all'. If split_date is a YYYYMMDD string, also emits
    'discovery' (trade_date < split_date) and 'validation' (trade_date >=
    split_date). Skips a split if its subset is empty.
    """
    td = pd.to_numeric(samples["trade_date"], errors="coerce")
    masks = [("all", pd.Series([True] * len(samples), index=samples.index))]
    if not split_date:
        return masks
    try:
        cutoff = int(str(split_date))
    except (TypeError, ValueError):
        return masks
    discovery_mask = td < cutoff
    validation_mask = td >= cutoff
    if discovery_mask.any():
        masks.append(("discovery", discovery_mask))
    if validation_mask.any():
        masks.append(("validation", validation_mask))
    return masks


def build_stats(samples, windows, split_date=None):
    """Build stats for cross-product of subsets × period_splits and stack them.

    Subsets:
      - 'all'         : every sample (Tier1 + Tier2 filler)
      - 'tier1_only'  : Tier == 'Tier1' subset (primary reporting view)

    Period splits (only emitted when split_date is set):
      - 'all'         : full date range (always emitted)
      - 'discovery'   : trade_date < split_date (in-sample rule discovery)
      - 'validation'  : trade_date >= split_date (out-of-sample validation)

    Reason for splits: avoid the data-mining trap of discovering AND validating
    rules on the same 24p sample. See findings_cc_24p §5 / reviewer suggestion.
    """
    samples = build_group_columns(samples)
    period_masks = _period_split_masks(samples, split_date)

    subset_specs = [("all", samples)]
    tier1_samples = samples[samples["tier_group"] == "Tier1"]
    if len(tier1_samples):
        subset_specs.append(("tier1_only", tier1_samples))

    summaries, factors, rule6s, monthlies = [], [], [], []
    for subset_label, subset_df in subset_specs:
        for split_label, split_mask in period_masks:
            mask_on_subset = split_mask.reindex(subset_df.index, fill_value=False)
            sliced = subset_df[mask_on_subset]
            if len(sliced) == 0:
                continue
            sum_d, fac_d, rul_d, mon_d = _build_stats_for_slice(
                sliced, windows, subset_label, split_label)
            summaries.append(sum_d)
            factors.append(fac_d)
            rule6s.append(rul_d)
            monthlies.append(mon_d)

    summary = pd.concat(summaries, ignore_index=True) if summaries else pd.DataFrame()
    factor_stats = pd.concat(factors, ignore_index=True) if factors else pd.DataFrame()
    rule6_stats = pd.concat(rule6s, ignore_index=True) if rule6s else pd.DataFrame()
    monthly_df = pd.concat(monthlies, ignore_index=True) if monthlies else pd.DataFrame()

    return summary, factor_stats, rule6_stats, monthly_df, samples


# ============================================================
# Eligible universe benchmark / strategy variants / portfolio stats
# ============================================================

def _board_from_code(ts_code):
    symbol = str(ts_code).split(".")[0]
    if symbol.startswith(("300", "301")):
        return "chinext"
    if symbol.startswith(("688", "689")):
        return "star"
    if symbol.startswith(("8", "4", "920")):
        return "bj"
    return "main"


def _full_rank_path(source_root, trade_date):
    return source_root / "_intermediate" / f"egs_full_{trade_date}.csv"


def _row_to_sample(row, trade_date, source_file, rank):
    l4_flag = "" if pd.isna(row.get("l4_flag")) else str(row.get("l4_flag"))
    return {
        "trade_date": str(trade_date),
        "source_file": str(source_file.relative_to(ROOT)) if hasattr(source_file, "relative_to") else str(source_file),
        "ts_code": row.get("ts_code"),
        "name": row.get("name"),
        "l1_name": row.get("l1_name"),
        "l2_name": row.get("l2_name"),
        "board": _board_from_code(row.get("ts_code")),
        "rank": rank,
        "tier": row.get("tier"),
        "final_score": row.get("final_score"),
        "esp_score": row.get("esp_score"),
        "cat_score": row.get("cat_score"),
        "l4_score": row.get("l4_score"),
        "l2_flags": row.get("l2_flags"),
        "l4_flag": row.get("l4_flag"),
        "entry_flag": row.get("entry_flag"),
        "overheat_flag": row.get("overheat_flag"),
        "chasing_high": row.get("chasing_high"),
        "has_crash_veto": row.get("has_crash_veto"),
        "is_lock": row.get("is_lock"),
        "is_breakout": row.get("is_breakout"),
        "hard_veto": row.get("hard_veto", False),
        "close": row.get("close"),
        "pct_20d": row.get("pct_20d"),
        "pct_20d_n": row.get("pct_20d_n"),
        "drawdown_20d": row.get("drawdown_20d"),
        "q0_dt_yoy": row.get("q0_dt_yoy"),
        "q1_dt_yoy": row.get("q1_dt_yoy"),
        "esp_raw": row.get("esp_raw"),
        "completeness_score": row.get("completeness_score", pd.NA),
        "rule6_any_status": "not_available_full_rank",
        "rule6_any_triggered": pd.NA,
        "variant_source": "full_rank",
    }


def _entry_flag_from_full(row):
    if bool(row.get("overheat_flag")) or bool(row.get("chasing_high")):
        return "追高风险，周一确认"
    br = pd.to_numeric(row.get("big_ratio"), errors="coerce")
    if not pd.isna(br) and br < -0.05:
        return "资金流背离"
    cs = pd.to_numeric(row.get("cat_score"), errors="coerce")
    p5 = pd.to_numeric(row.get("pct_5d_n"), errors="coerce")
    if not pd.isna(cs) and cs > 85 and not pd.isna(p5) and p5 > 5:
        return "题材过热"
    if "LOCK" in str(row.get("l4_flag", "")):
        return "需周一确认"
    return "可直接观察"


def _cap_l2_for_variant(t1_df, cap=15, threshold=20):
    if t1_df.empty or "l2_name" not in t1_df.columns:
        return t1_df
    l2_counts = t1_df["l2_name"].value_counts()
    overflow = set(l2_counts[l2_counts > threshold].index)
    if not overflow:
        return t1_df
    l2_seen, keep_idx = {}, []
    for idx, row in t1_df.iterrows():
        l2 = row.get("l2_name")
        cnt = l2_seen.get(l2, 0)
        if l2 in overflow and cnt >= cap:
            continue
        keep_idx.append(idx)
        l2_seen[l2] = cnt + 1
    return t1_df.loc[keep_idx]


def _diversified_top_for_variant(tier1, top_n=50):
    selected, l1c, l2c = [], {}, {}
    for _, row in tier1.iterrows():
        l1, l2 = row.get("l1_name"), row.get("l2_name")
        l1_key = l2 if l1 == "未知" else l1
        n = max(len(selected), 1)
        if l1c.get(l1_key, 0) / n > 0.4:
            continue
        if l2c.get(l2, 0) / n > 0.3:
            continue
        selected.append(row)
        l1c[l1_key] = l1c.get(l1_key, 0) + 1
        l2c[l2] = l2c.get(l2, 0) + 1
    return pd.DataFrame(selected, columns=tier1.columns).head(top_n)


def _recalc_esp_cap_scores(df, cap=ESP_CAP_VALUE):
    """Experimental rerank: replay score_l5 with an upper cap on esp_raw.

    This is intentionally local to backtest variants so we can validate the
    rule out-of-sample before promoting it into official EGS scoring.
    """
    df = df.copy()
    def _series(name, default=False):
        if name in df.columns:
            return df[name]
        return pd.Series(default, index=df.index)
    df["l2_flags"] = df.get("l2_flags", "").fillna("").astype(str)
    df["cat_flag"] = df.get("cat_flag", "").fillna("").astype(str)
    df["l4_flag"] = df.get("l4_flag", "").fillna("").astype(str)
    df["esp_raw_w"] = pd.to_numeric(df.get("esp_raw"), errors="coerce").clip(upper=cap).fillna(0.0)
    cov_mask = df["l2_flags"].str.contains("COV-LOW", na=False)
    df["esp_z"] = 0.0
    for mask in [~cov_mask, cov_mask]:
        sub_idx = df[mask].index
        for grp_name, idx in df.loc[sub_idx].groupby("z_group").groups.items():
            if grp_name == "独立池":
                continue
            vals = df.loc[idx, "esp_raw_w"]
            if len(vals) < 2:
                continue
            mu, sig = vals.mean(), vals.std()
            if pd.isna(sig) or sig < 1e-9:
                continue
            df.loc[idx, "esp_z"] = (df.loc[idx, "esp_raw_w"] - mu) / sig

    indep_mask = df["z_group"] == "独立池"
    df["esp_score"] = 0.0
    if indep_mask.any():
        x = df.loc[indep_mask, "esp_raw_w"]
        rng = x.max() - x.min()
        df.loc[indep_mask, "esp_score"] = ((x - x.min()) / rng * 50) if rng > 0 else 25.0

    def z2s(z):
        if pd.isna(z):
            return 50.0
        if z < -2.5:
            return 5
        if z < -1.5:
            return 12
        if z < -0.5:
            return 22
        if z < 0:
            return 32
        if z < 1:
            return 50
        if z < 2:
            return 68
        if z < 3:
            return 82
        return min(100, 95 + (z - 3) * 3)

    non_indep = ~indep_mask
    df.loc[non_indep, "esp_score"] = df.loc[non_indep, "esp_z"].apply(z2s)
    df.loc[cov_mask & non_indep, "esp_score"] = df.loc[cov_mask & non_indep, "esp_score"].clip(upper=50)
    df["egs_base"] = df["esp_score"] * 0.20 + df["cat_score"] * 0.30 + df["l4_score"] * 0.50
    df["mult"] = 1.0
    df.loc[df["l2_flags"].str.contains("ESP-Q", na=False), "mult"] *= 0.7
    df.loc[df["cat_flag"].str.contains("CAT-0", na=False), "mult"] *= 0.5
    df["deduct"] = 0.0
    df.loc[df.get("l1_flag") == "ITF-2", "deduct"] += 15
    df.loc[df.get("itf_adj") == True, "deduct"] += 10
    df["deduct"] += pd.to_numeric(df.get("reduce_penalty", 0), errors="coerce").fillna(0)
    df["deduct"] += pd.to_numeric(df.get("val_penalty", 0), errors="coerce").fillna(0)
    val_bonus = pd.to_numeric(df.get("val_bonus", 0), errors="coerce").fillna(0)
    df["final_score"] = ((df["egs_base"] * df["mult"]).clip(lower=df["egs_base"] * 0.3)
                         + val_bonus - df["deduct"]).clip(lower=0).round(2)
    p75 = df["final_score"].quantile(0.75)
    p55 = df["final_score"].quantile(0.55)
    df["tier"] = "Other"
    df.loc[df["final_score"] >= p55, "tier"] = "Tier2"
    df.loc[df["final_score"] >= p75, "tier"] = "Tier1"
    df.loc[df["final_score"] < 50, "tier"] = "Other"

    fin_coverage = pd.to_numeric(df.get("q0_dt_yoy"), errors="coerce").notna().sum() / max(len(df), 1)
    if fin_coverage >= 0.70:
        df.loc[(df["tier"] == "Tier1") & (pd.to_numeric(df["esp_raw"], errors="coerce").fillna(0) <= 0), "tier"] = "Tier2"
    df.loc[(df["tier"] == "Tier1") & _series("chasing_high").fillna(False).astype(bool), "tier"] = "Tier2"
    df.loc[(df["tier"] == "Tier1") & _series("overheat_flag").fillna(False).astype(bool), "tier"] = "Tier2"
    df.loc[df["l4_flag"].str.contains("TIER2_FORCED", na=False), "tier"] = "Tier2"
    df.loc[(df["tier"] == "Tier1") & (df["l2_name"] == "未知"), "tier"] = "Tier2"
    return df


def load_eligible_universe(source_root, selected_dates):
    rows = []
    for d in selected_dates:
        path = _full_rank_path(source_root, d)
        if not path.exists():
            print(f"[WARN] eligible universe missing {path.relative_to(ROOT)}")
            continue
        df = pd.read_csv(path)
        df = df[df["tier"].isin(["Tier1", "Tier2"])].copy()
        df = df.sort_values(["final_score", "l4_score", "pct_20d_n"], ascending=[False, False, False])
        for rank, (_, row) in enumerate(df.iterrows(), start=1):
            rows.append(_row_to_sample(row, d, path, rank))
    out = pd.DataFrame(rows)
    if not out.empty:
        out["variant_source"] = "eligible_universe"
    return out


def load_esp_cap_rerank_samples(source_root, selected_dates, watch_n=15):
    rows = []
    for d in selected_dates:
        path = _full_rank_path(source_root, d)
        if not path.exists():
            continue
        df = pd.read_csv(path)
        df = _recalc_esp_cap_scores(df, cap=ESP_CAP_VALUE)
        tier1 = df[df["tier"] == "Tier1"].sort_values(
            ["final_score", "l4_score", "pct_20d_n"], ascending=[False, False, False]
        )
        tier1 = _cap_l2_for_variant(tier1)
        top = _diversified_top_for_variant(tier1).head(watch_n).copy()
        if len(top) < watch_n:
            existing = set(top["ts_code"].tolist()) if "ts_code" in top.columns else set()
            fill = df[(df["tier"] == "Tier2") & (~df["ts_code"].isin(existing))] \
                .sort_values(["final_score", "l4_score", "pct_20d_n"], ascending=[False, False, False]) \
                .head(watch_n - len(top))
            if not fill.empty:
                top = pd.concat([top, fill[top.columns]], ignore_index=True)
        if top.empty:
            continue
        top["entry_flag"] = top.apply(_entry_flag_from_full, axis=1)
        for rank, (_, row) in enumerate(top.iterrows(), start=1):
            sample = _row_to_sample(row, d, path, rank)
            sample["strategy_variant"] = "esp_cap_200_rerank"
            rows.append(sample)
    return pd.DataFrame(rows)


def attach_eligible_excess(samples, eligible_samples, windows):
    samples = samples.copy()
    if eligible_samples.empty:
        return samples, pd.DataFrame()
    bench_rows = []
    for trade_date, dgrp in eligible_samples.groupby("trade_date", dropna=True):
        for window in windows:
            status_col = f"ret_{window}d_status"
            ret_col = f"ret_{window}d_t1"
            net_col = f"ret_{window}d_t1_net"
            if status_col not in dgrp.columns:
                continue
            ok_mask = dgrp[status_col] == "ok"
            vals = pd.to_numeric(dgrp.loc[ok_mask, ret_col], errors="coerce").dropna()
            net_vals = pd.to_numeric(dgrp.loc[ok_mask, net_col], errors="coerce").dropna()
            bench_rows.append({
                "trade_date": str(trade_date),
                "window": window,
                "eligible_count": int(len(dgrp)),
                "available_count": int(len(vals)),
                "mean_t1_pct": float(vals.mean()) if len(vals) else None,
                "mean_t1_net_pct": float(net_vals.mean()) if len(net_vals) else None,
                "median_t1_pct": float(vals.median()) if len(vals) else None,
                "win_rate_pct": float((vals > 0).mean() * 100) if len(vals) else None,
            })
    bench_df = pd.DataFrame(bench_rows)
    if bench_df.empty:
        return samples, bench_df
    for window in windows:
        key = bench_df[bench_df["window"] == window].set_index("trade_date")["mean_t1_pct"].to_dict()
        samples[f"ret_{window}d_{ELIGIBLE_BENCHMARK}"] = samples["trade_date"].astype(str).map(key)
        base = pd.to_numeric(samples[f"ret_{window}d_t1"], errors="coerce")
        bench = pd.to_numeric(samples[f"ret_{window}d_{ELIGIBLE_BENCHMARK}"], errors="coerce")
        samples[f"ret_{window}d_excess_{ELIGIBLE_BENCHMARK}"] = base - bench
    return samples, bench_df


def _variant_mask(samples, name):
    s = build_group_columns(samples)
    mask = pd.Series([True] * len(s), index=s.index)
    if name == "baseline":
        return mask
    if name == "no_chase":
        return mask & ~(s["entry_flag_group"].eq("追高风险，周一确认") | s["chasing_high"].fillna(False).astype(bool))
    if name == "no_overheat":
        return mask & ~(s["has_l4_overheat"].fillna(False).astype(bool) | s["overheat_flag"].fillna(False).astype(bool))
    if name == "no_low_base":
        return mask & ~(s["q0_dt_yoy_gt_200"] | s["q1_dt_yoy_gt_200"] | s["esp_raw_gt_200"])
    if name == "tier1_only":
        return mask & s["tier_group"].eq("Tier1")
    if name == "no_tier2_unknown":
        return mask & ~(s["tier_group"].eq("Tier2") & s["l2_unknown"])
    if name == "no_lock":
        return mask & ~s["has_l4_lock"].fillna(False).astype(bool)
    if name == "combined_p0":
        return (mask & s["tier_group"].eq("Tier1")
                & ~(s["entry_flag_group"].eq("追高风险，周一确认") | s["chasing_high"].fillna(False).astype(bool))
                & ~(s["has_l4_overheat"].fillna(False).astype(bool) | s["overheat_flag"].fillna(False).astype(bool))
                & ~(s["q0_dt_yoy_gt_200"] | s["q1_dt_yoy_gt_200"] | s["esp_raw_gt_200"]))
    return mask


STRATEGY_VARIANTS = [
    "baseline",
    "no_chase",
    "no_overheat",
    "no_low_base",
    "tier1_only",
    "no_tier2_unknown",
    "no_lock",
    "combined_p0",
]


def build_strategy_variant_stats(samples, windows, split_date=None, extra_variants=None):
    frames = []
    variant_sources = [(name, samples[_variant_mask(samples, name)].copy()) for name in STRATEGY_VARIANTS]
    for name, df in (extra_variants or {}).items():
        variant_sources.append((name, df.copy()))
    for name, df in variant_sources:
        if df.empty:
            continue
        summary, _factor, _rule6, monthly, shaped = build_stats(df, windows, split_date=split_date)
        summary.insert(0, "strategy_variant", name)
        monthly.insert(0, "strategy_variant", name)
        frames.append((summary, monthly, name, len(shaped)))
    if not frames:
        return pd.DataFrame(), pd.DataFrame(), []
    summary_df = pd.concat([x[0] for x in frames], ignore_index=True)
    monthly_df = pd.concat([x[1] for x in frames], ignore_index=True)
    meta = [{"strategy_variant": name, "sample_count": count} for *_unused, name, count in frames]
    return summary_df, monthly_df, meta


def _max_drawdown_from_returns(returns_pct):
    equity = 1.0
    peak = 1.0
    max_dd = 0.0
    for r in returns_pct:
        equity *= (1.0 + float(r) / 100.0)
        peak = max(peak, equity)
        dd = equity / peak - 1.0
        max_dd = min(max_dd, dd)
    return max_dd * 100.0


def build_portfolio_stats(samples, windows, split_date=None, strategy_variant="baseline"):
    samples = build_group_columns(samples)
    period_masks = _period_split_masks(samples, split_date)
    subset_specs = [("all", samples)]
    tier1 = samples[samples["tier_group"] == "Tier1"]
    if len(tier1):
        subset_specs.append(("tier1_only", tier1))

    period_rows, stat_rows = [], []
    for subset_label, subset_df in subset_specs:
        for split_label, split_mask in period_masks:
            sliced = subset_df[split_mask.reindex(subset_df.index, fill_value=False)]
            if sliced.empty:
                continue
            for window in windows:
                status_col = f"ret_{window}d_status"
                for variant in RET_VARIANTS:
                    col = f"ret_{window}d_{variant}"
                    if col not in sliced.columns:
                        continue
                    series_rows = []
                    for trade_date, dgrp in sliced.groupby("trade_date", dropna=True):
                        ok = pd.to_numeric(dgrp.loc[dgrp[status_col] == "ok", col], errors="coerce").dropna()
                        if not len(ok):
                            continue
                        r = float(ok.mean())
                        period_rows.append({
                            "strategy_variant": strategy_variant,
                            "subset": subset_label,
                            "period_split": split_label,
                            "trade_date": str(trade_date),
                            "window": window,
                            "variant": variant,
                            "holding_count": int(len(ok)),
                            "return_pct": r,
                            "win_rate_pct": float((ok > 0).mean() * 100),
                        })
                        series_rows.append({"trade_date": str(trade_date), "value": r})
                    if not series_rows:
                        continue
                    sub = pd.DataFrame(series_rows)
                    vals = sub["value"]
                    stats = _cluster_stats(sub.rename(columns={"value": "value"}))
                    compounded = float((np.prod(1 + vals / 100.0) - 1.0) * 100.0)
                    stat_rows.append({
                        "strategy_variant": strategy_variant,
                        "subset": subset_label,
                        "period_split": split_label,
                        "window": window,
                        "variant": variant,
                        "period_count": int(len(vals)),
                        "mean_period_return_pct": float(vals.mean()),
                        "median_period_return_pct": float(vals.median()),
                        "compounded_return_pct": compounded,
                        "max_drawdown_pct": _max_drawdown_from_returns(vals.tolist()),
                        "worst_period_return_pct": float(vals.min()),
                        "best_period_return_pct": float(vals.max()),
                        "win_rate_pct": float((vals > 0).mean() * 100),
                        "std_pct": stats["std_pct"],
                        "monthly_t": stats["monthly_t"],
                        "sharpe_monthly": stats["sharpe_monthly"],
                    })
    return pd.DataFrame(period_rows), pd.DataFrame(stat_rows)


# ============================================================
# Dedup / sample shaping
# ============================================================

def apply_dedup(samples, mode):
    """Optionally collapse repeated picks to reduce sample correlation."""
    if mode == "none" or samples.empty:
        return samples
    if mode == "by_ts_code":
        return samples.drop_duplicates(subset=["ts_code"], keep="first").reset_index(drop=True)
    if mode == "by_ts_and_date":
        return samples.drop_duplicates(subset=["ts_code", "trade_date"], keep="first").reset_index(drop=True)
    return samples


def load_last_report():
    report_path = BACKTEST_DIR / "backtest_report.json"
    if not report_path.exists():
        return {}
    try:
        with report_path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def load_last_report_dates():
    report = load_last_report()
    dates = report.get("selected_dates", [])
    if not isinstance(dates, list):
        return []
    return [str(d) for d in dates]


def _read_pool_source_field(selected_dates, generated_root, field, default):
    """Read source.<field> from each analysis_input.json under generated/<date>/.
    Returns dict {date: value}. Missing/invalid files are skipped silently."""
    out = {}
    for d in selected_dates:
        p = generated_root / d / "analysis_input.json"
        if not p.exists():
            continue
        try:
            with p.open("r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        src = (data.get("source") or {}) if isinstance(data, dict) else {}
        out[d] = src.get(field, default)
    return out


def validate_stats_only_pools(selected_dates, generated_root):
    """Validate existing generated pools before stats-only reads them.

    Candidate generation already checks l3/schema/engine before deciding to
    skip. Stats-only has no generation pass, so it must reject stale pools here
    instead of producing a report with mixed or legacy inputs.
    """
    if not selected_dates:
        raise RuntimeError(
            "No generated as-of dates selected for stats-only. "
            "Pass --periods N, --start-date/--end-date, or generate candidates first."
        )

    current_egs_version = _current_egs_version()
    meta = {}
    errors = []
    for d in selected_dates:
        path = generated_root / d / "analysis_input.json"
        data, ok = _safe_load_analysis(path)
        if not ok:
            errors.append(f"{d}: missing or malformed {path.relative_to(ROOT)}")
            continue

        src = (data.get("source") or {}) if isinstance(data, dict) else {}
        schema_version = data.get("schema_version")
        engine_version = src.get("screening_engine_version")
        l3_mode = src.get("l3_mode")
        l3_pit_strict = src.get("l3_pit_strict")

        if schema_version != EXPECTED_ANALYSIS_INPUT_SCHEMA:
            errors.append(
                f"{d}: schema_version {schema_version!r} != "
                f"{EXPECTED_ANALYSIS_INPUT_SCHEMA!r}"
            )
        if current_egs_version and engine_version != current_egs_version:
            errors.append(
                f"{d}: engine_version {engine_version!r} != "
                f"{current_egs_version!r}"
            )
        if l3_mode is None:
            errors.append(f"{d}: source.l3_mode missing")
        if l3_pit_strict is None:
            errors.append(f"{d}: source.l3_pit_strict missing")

        meta[d] = {
            "schema_version": schema_version,
            "engine_version": engine_version,
            "l3_mode": l3_mode,
            "l3_pit_strict": bool(l3_pit_strict),
        }

    if errors:
        raise SystemExit(
            "[FATAL] stats-only refuses stale or incompatible candidate pools:\n  - "
            + "\n  - ".join(errors)
            + "\nRegenerate them first without --stats-only."
        )
    return meta


def select_stats_only_dates(args):
    generated_dates = sorted(p.name for p in GENERATED_DIR.glob("20*") if p.is_dir())
    if args.start_date:
        end_date = args.end_date or "99999999"
        selected = [d for d in generated_dates if args.start_date <= d <= end_date]
        if args.periods > 0:
            selected = selected[-args.periods:]
        return selected, "date-window", {}
    if args.periods > 0:
        return generated_dates[-args.periods:], "last-periods", {}

    last_report = load_last_report()
    last_report_dates = last_report.get("selected_dates", [])
    if last_report_dates:
        existing = set(generated_dates)
        selected = [str(d) for d in last_report_dates if str(d) in existing]
        if selected:
            return selected, "last-report", last_report
    return generated_dates, "all-generated", {}


# ============================================================
# Date selection
# ============================================================

def select_asof_dates(trade_dates, periods, freq, max_window,
                      reference_date, include_immature=False):
    """Return (chosen, immature_included, immature_skipped).

    immature_included = subset of chosen whose future window is incomplete
                        (only populated when include_immature=True).
    immature_skipped  = immature candidates that were NOT selected.
    Their union is the full immature pool considered.
    """
    if not trade_dates:
        return [], [], []

    if freq == "daily":
        candidates = list(trade_dates)
    else:
        grouped = defaultdict(list)
        for date in trade_dates:
            dt = datetime.strptime(date, "%Y%m%d")
            key = dt.strftime("%Y-%W") if freq == "weekly" else dt.strftime("%Y-%m")
            grouped[key].append(date)
        candidates = [max(values) for _, values in sorted(grouped.items())]

    cal_pos = {d: i for i, d in enumerate(trade_dates)}
    ref_pos = cal_pos.get(reference_date, len(trade_dates) - 1)

    mature, immature = [], []
    for d in candidates:
        pos = cal_pos.get(d)
        if pos is None:
            immature.append(d)
            continue
        future_days = ref_pos - pos
        # Need T+1 entry and an exit close on T+max_window.
        if future_days >= max_window:
            mature.append(d)
        else:
            immature.append(d)

    if include_immature:
        chosen = (mature + immature)[-periods:]
    else:
        chosen = mature[-periods:]

    chosen_set = set(chosen)
    immature_included = [d for d in immature if d in chosen_set]
    immature_skipped = [d for d in immature if d not in chosen_set]
    return chosen, immature_included, immature_skipped


def validate_freq_vs_window(freq, max_window):
    """Warn when freq spacing is shorter than the longest holding window."""
    spacing = {"daily": 1, "weekly": 5, "monthly": 20}.get(freq, 1)
    if max_window > spacing:
        print(f"[WARN] freq={freq} produces ~{spacing} trading-day spacing but max_window={max_window}; "
              f"adjacent samples will have overlapping forward windows -> stats variance underestimated. "
              f"Consider --freq monthly for max_window=20.")


# ============================================================
# Candidate generation
# ============================================================

def generate_candidates(dates, python_cmd, output_root, skip_existing=True,
                        reuse_l3_cache=False, l3_mode="today", l3_pit_strict=False):
    output_root.mkdir(parents=True, exist_ok=True)
    rel_output = output_root.relative_to(ROOT).as_posix()
    current_egs_version = _current_egs_version()
    for date in dates:
        target = output_root / date / "analysis_input.json"
        if skip_existing and target.exists():
            data, ok = _safe_load_analysis(target)
            if ok:
                # Verify the pool matches current request on ALL of:
                #   * source.l3_mode
                #   * source.l3_pit_strict (when l3_mode=pit)
                #   * schema_version
                #   * source.screening_engine_version (EGS_VERSION at write time)
                # Legacy files (pre-1.1) lack source.l3_mode; treat as "today".
                src = (data.get("source") or {}) if isinstance(data, dict) else {}
                existing_mode = src.get("l3_mode", "today")
                existing_strict = bool(src.get("l3_pit_strict", False))
                existing_schema = data.get("schema_version")
                existing_engine = src.get("screening_engine_version")
                reasons = []
                if existing_mode != l3_mode:
                    reasons.append(f"l3_mode {existing_mode!r} != {l3_mode!r}")
                if l3_mode == "pit" and existing_strict != l3_pit_strict:
                    reasons.append(f"l3_pit_strict {existing_strict} != {l3_pit_strict}")
                if existing_schema != EXPECTED_ANALYSIS_INPUT_SCHEMA:
                    reasons.append(f"schema_version {existing_schema!r} != {EXPECTED_ANALYSIS_INPUT_SCHEMA!r}")
                if current_egs_version and existing_engine != current_egs_version:
                    reasons.append(f"engine_version {existing_engine!r} != {current_egs_version!r}")
                if reasons:
                    print(f"[REGEN] {date} {' / '.join(reasons)}; regenerating")
                else:
                    print(f"[SKIP] {date} already generated "
                          f"(l3_mode={existing_mode}, schema={existing_schema}, engine={existing_engine}) "
                          f"at {target.relative_to(ROOT)}")
                    continue
            else:
                print(f"[REGEN] {target.relative_to(ROOT)} failed validation; regenerating")
        cmd = [
            python_cmd, str(EGS_SCRIPT),
            "--as-of", date,
            "--backtest-mode",
            "--output-root", rel_output,
            "--l3-mode", l3_mode,
        ]
        if reuse_l3_cache:
            cmd.append("--reuse-l3-cache")
        if l3_pit_strict:
            cmd.append("--l3-pit-strict")
        print(f"[RUN] {' '.join(cmd)}")
        subprocess.run(cmd, cwd=str(ROOT), check=True)


# ============================================================
# Report writer
# ============================================================

def _l3_limitation_line(settings):
    mode = settings.get("l3_mode", "today")
    if mode == "neutralize":
        return ("L3 cat_score neutralized (=50.0) for all candidates; results reflect L1/L2/L4/ESP "
                "factors only. Used when PIT concept snapshots are not yet accumulated for the as_of range.")
    if mode == "pit":
        return ("L3 cat_score read from PIT snapshots under state/l3_snapshots/ (latest snapshot "
                "<= as_of). No look-ahead bias in L3 within the snapshot coverage; gaps > 14 days are warned.")
    return ("L3 concept membership uses today's Tushare snapshot (pro.concept / pro.concept_detail "
            "have no as_of parameter); cat_score may carry look-ahead bias on multi-month windows. "
            "Use --l3-mode=neutralize for unbiased historical backtests, or --l3-mode=pit once snapshots accumulate.")


def _validate_report_or_raise(report, report_path):
    """Validate backtest_report.json against the published schema.

    Treats missing jsonschema or missing schema file as fatal: the project
    convention is "cross-module data is contract-first", and shipping an
    unvalidated report would silently break that promise.
    """
    try:
        import jsonschema
        from jsonschema import Draft7Validator
    except ImportError as e:
        raise RuntimeError(
            "jsonschema is required to validate backtest_report.json. "
            "Install with: pip install jsonschema"
        ) from e

    if not REPORT_SCHEMA.exists():
        raise RuntimeError(
            f"Backtest report schema not found at {REPORT_SCHEMA}. "
            "Phase 2 requires this contract file to exist."
        )

    with REPORT_SCHEMA.open("r", encoding="utf-8") as f:
        schema = json.load(f)
    Draft7Validator.check_schema(schema)
    errors = list(Draft7Validator(schema).iter_errors(report))
    if errors:
        lines = [f"backtest_report.json failed schema validation ({len(errors)} errors):"]
        for e in errors[:10]:
            path = "/" + "/".join(str(p) for p in e.absolute_path) or "/"
            lines.append(f"  {e.validator} at {path}: {e.message[:200]}")
        if len(errors) > 10:
            lines.append(f"  ... ({len(errors) - 10} more)")
        lines.append(f"Report path: {report_path}")
        lines.append(f"Schema path: {REPORT_SCHEMA}")
        raise RuntimeError("\n".join(lines))
    print(f"[OK] backtest_report.json validated against rank_backtest_report v"
          f"{report.get('schema_version')}")


def write_outputs(samples, summary, factor_stats, rule6_stats, monthly_df, windows,
                  source_root, selected_dates, immature_included, immature_skipped,
                  forward_meta, mode, settings, eligible_benchmark=None,
                  strategy_variant_stats=None, strategy_variant_monthly=None,
                  portfolio_period_returns=None, portfolio_stats=None,
                  variant_meta=None):
    BACKTEST_DIR.mkdir(parents=True, exist_ok=True)
    if isinstance(forward_meta, dict) and forward_meta.get("status") is None:
        forward_meta = dict(forward_meta)
        forward_meta.setdefault("limit_rows", 0)
    samples.to_csv(BACKTEST_DIR / "rank_samples.csv", index=False, encoding="utf-8-sig")
    summary.to_csv(BACKTEST_DIR / "summary_by_window.csv", index=False, encoding="utf-8-sig")
    factor_stats.to_csv(BACKTEST_DIR / "factor_group_stats.csv", index=False, encoding="utf-8-sig")
    rule6_stats.to_csv(BACKTEST_DIR / "rule6_stats.csv", index=False, encoding="utf-8-sig")
    monthly_df.to_csv(BACKTEST_DIR / "monthly_stats.csv", index=False, encoding="utf-8-sig")
    if eligible_benchmark is None:
        eligible_benchmark = pd.DataFrame()
    if strategy_variant_stats is None:
        strategy_variant_stats = pd.DataFrame()
    if strategy_variant_monthly is None:
        strategy_variant_monthly = pd.DataFrame()
    if portfolio_period_returns is None:
        portfolio_period_returns = pd.DataFrame()
    if portfolio_stats is None:
        portfolio_stats = pd.DataFrame()
    eligible_benchmark.to_csv(BACKTEST_DIR / "eligible_benchmark.csv", index=False, encoding="utf-8-sig")
    strategy_variant_stats.to_csv(BACKTEST_DIR / "strategy_variant_stats.csv", index=False, encoding="utf-8-sig")
    strategy_variant_monthly.to_csv(BACKTEST_DIR / "strategy_variant_monthly.csv", index=False, encoding="utf-8-sig")
    portfolio_period_returns.to_csv(BACKTEST_DIR / "portfolio_period_returns.csv", index=False, encoding="utf-8-sig")
    portfolio_stats.to_csv(BACKTEST_DIR / "portfolio_stats.csv", index=False, encoding="utf-8-sig")

    report = {
        "schema_name": "rank_backtest_report",
        "schema_version": "1.10.0",
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "preset": "a_short",
        "mode": mode,
        "engineering_smoke": mode == "smoke",
        "settings": settings,
        "windows": windows,
        "sample_count": int(len(samples)),
        "selected_dates": selected_dates,
        "date_warnings": build_date_warnings(samples, selected_dates),
        "immature_included_dates": immature_included,
        "immature_skipped_dates": immature_skipped,
        "trade_dates": sorted(samples["trade_date"].dropna().astype(str).unique().tolist()) if not samples.empty else [],
        "candidate_source_root": str(source_root.relative_to(ROOT)),
        "forward_daily": forward_meta,
        "outputs": {
            "rank_samples": str((BACKTEST_DIR / "rank_samples.csv").relative_to(ROOT)),
            "summary_by_window": str((BACKTEST_DIR / "summary_by_window.csv").relative_to(ROOT)),
            "factor_group_stats": str((BACKTEST_DIR / "factor_group_stats.csv").relative_to(ROOT)),
            "rule6_stats": str((BACKTEST_DIR / "rule6_stats.csv").relative_to(ROOT)),
            "monthly_stats": str((BACKTEST_DIR / "monthly_stats.csv").relative_to(ROOT)),
            "eligible_benchmark": str((BACKTEST_DIR / "eligible_benchmark.csv").relative_to(ROOT)),
            "strategy_variant_stats": str((BACKTEST_DIR / "strategy_variant_stats.csv").relative_to(ROOT)),
            "strategy_variant_monthly": str((BACKTEST_DIR / "strategy_variant_monthly.csv").relative_to(ROOT)),
            "portfolio_period_returns": str((BACKTEST_DIR / "portfolio_period_returns.csv").relative_to(ROOT)),
            "portfolio_stats": str((BACKTEST_DIR / "portfolio_stats.csv").relative_to(ROOT)),
        },
        "strategy_variants": variant_meta or [],
        "return_variants": {
            "close": "qfq close-to-close (no T+1, no cost). Reference only.",
            "t1": "qfq T+1 open entry to close of T+W. Gross of cost.",
            "t1_net": "qfq T+1 open entry minus round-trip cost (default 0.16%).",
            "excess_csi300": "t1 minus CSI300 same-window return (entry_date to exit_date).",
            "excess_csi1000": "t1 minus CSI1000 same-window return.",
            "excess_eligible": "t1 minus same-date eligible universe equal-weight t1 return. Eligible universe is Tier1+Tier2 rows from generated/_intermediate/egs_full_YYYYMMDD.csv.",
        },
        "limitations": [
            "Backtest writes generated candidate pools and intermediate EGS CSV/XLSX artifacts under result/a_short/backtest/generated/ (isolated from official output).",
            "Forward returns are qfq-adjusted via Tushare adj_factor; transaction cost defaults to 0.16% round-trip.",
            "T+1 entry is marked pending_no_entry_limit_up when Tushare stk_limit says entry open is at/near up_limit; falls back to board-specific limit rules only when stk_limit is unavailable.",
            "Eligible benchmark uses the generated full-rank Tier1+Tier2 pool for the same as_of date; it is an internal opportunity-set benchmark, not a tradable market index.",
            "Strategy variants use post-hoc filters except esp_cap_200_rerank, which replays score_l5-style ranking from generated/_intermediate/egs_full_YYYYMMDD.csv; variants are for validation before promotion into official EGS rules.",
            "Benchmark excess returns compare stock T+1 open-to-close returns against benchmark close-to-close returns over the same entry/exit dates; this can introduce a small intraday entry-basis difference.",
            "Backtest mode skips cninfo, web news, and DeepSeek Stage3 checks, so historical candidate pools do not include the same regulatory/policy veto layer as production screening.",
            "Adjacent as-of dates with overlapping forward windows correlate; variance is therefore not iid -- use monthly freq for max_window=20 or apply --dedup-mode.",
            "Stock universe includes delisted stocks per as_of (B2 fixed); industry membership is point-in-time via in_date/out_date (B3a fixed).",
            "Financial data filtered by ann_date<=as_of; Tushare returns the latest revision of each quarter rather than the originally-disclosed version (Tushare API limitation, not fixable here).",
            _l3_limitation_line(settings),
        ],
        "data_lineage": {
            "data_provider": "tushare",
            "api_families": {
                "candidate_generation": _current_egs_api_families(),
                "forward_evaluation": [
                    "daily", "adj_factor", "stk_limit", "index_daily", "trade_cal",
                ],
            },
            "forward_return_adjustment_mode": (
                forward_meta.get("adj", "qfq_via_adj_factor")
                if isinstance(forward_meta, dict) and forward_meta.get("status") != "skipped_no_samples"
                else "qfq_via_adj_factor"
            ),
            "benchmark_sources": {
                "csi300": "tushare:index_daily/000300.SH",
                "csi1000": "tushare:index_daily/000852.SH",
                "eligible": "internal:generated/_intermediate/egs_full_YYYYMMDD.csv Tier1+Tier2 equal-weight",
            },
            "pit_limitations": [
                "Tushare financials are filtered by ann_date<=as_of but returned values reflect latest revisions, not as-originally-disclosed (Tushare API limitation, not fixable here).",
                "L3 concept catalysts have no native as-of parameter; PIT support is via locally accumulated state/l3_snapshots/ snapshots (only effective once coverage is meaningful).",
                "SW industry membership applies in_date/out_date PIT filtering (B3a fix).",
                "Stock universe includes delisted stocks per as_of (B2 fix).",
            ],
        },
    }
    report_path = BACKTEST_DIR / "backtest_report.json"
    with report_path.open("w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    _validate_report_or_raise(report, report_path)


# ============================================================
# Mode enforcement
# ============================================================

def enforce_mode(args):
    """Smoke = lenient; production = strict. Returns the resolved settings dict."""
    mode = args.mode
    if mode == "production":
        violations = []
        if args.reuse_l3_cache:
            violations.append("--reuse-l3-cache is forbidden in production mode")
        if args.include_immature:
            violations.append("--include-immature is forbidden in production mode")
        if args.l3_mode == "pit" and not args.l3_pit_strict:
            violations.append("--l3-mode=pit requires --l3-pit-strict in production mode")
        if violations:
            raise SystemExit("[FATAL] production mode violations:\n  - " + "\n  - ".join(violations))
    return {
        "mode": mode,
        "reuse_l3_cache": bool(args.reuse_l3_cache),
        "include_immature": bool(args.include_immature),
        "cost_pct": float(args.cost_pct),
        "dedup_mode": args.dedup_mode,
        "windows": parse_windows(args.windows),
        "freq": args.freq,
        "periods": int(args.periods),
        "start_date": args.start_date,
        "end_date": args.end_date,
        "l3_mode": args.l3_mode,
        "l3_pit_strict": bool(args.l3_pit_strict),
        "primary_subset": PRIMARY_SUBSET,
        "split_date": args.split_date,
    }


# ============================================================
# Main
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="Phase 2 rank backtest for a_short")
    parser.add_argument("--mode", choices=["smoke", "production"], default="smoke",
                        help="smoke (default): allow L3 reuse and immature dates; "
                             "production: strict, refuses both.")
    parser.add_argument("--periods", type=int, default=0, help="Number of historical periods to generate")
    parser.add_argument("--freq", choices=["daily", "weekly", "monthly"], default="weekly")
    parser.add_argument("--start-date", help="Start date for historical generation, YYYYMMDD")
    parser.add_argument("--end-date", default=datetime.now().strftime("%Y%m%d"),
                        help="End date for historical generation, YYYYMMDD")
    parser.add_argument("--windows", default="5,10,20", help="Forward return windows, comma separated")
    parser.add_argument("--stats-only", action="store_true",
                        help="Skip candidate generation; compute stats from existing backtest outputs.")
    parser.add_argument("--python", default=sys.executable, help="Python executable used to call A-EGS/egs_main.py")
    parser.add_argument("--no-skip-existing", action="store_true",
                        help="Regenerate existing analysis_input.json files in the backtest tree")
    parser.add_argument("--reuse-l3-cache", action="store_true",
                        help="Smoke only: reuse shared L3 concept caches during candidate generation")
    parser.add_argument("--include-immature", action="store_true",
                        help="Smoke only: include as-of dates whose future window is incomplete")
    parser.add_argument("--refresh-forward-daily", action="store_true",
                        help="Force re-download the forward daily cache from Tushare")
    parser.add_argument("--dedup-mode", choices=["none", "by_ts_code", "by_ts_and_date"], default="none",
                        help="Sample dedup applied before stats (reduces correlation from repeated picks).")
    parser.add_argument("--cost-pct", type=float, default=DEFAULT_COST_PCT,
                        help=f"Round-trip transaction cost in pct (default {DEFAULT_COST_PCT}).")
    parser.add_argument("--l3-mode", dest="l3_mode", choices=["pit", "today", "neutralize"],
                        default=None,
                        help="L3 cat_score source passed to egs_main. Default: neutralize when --mode=production, "
                             "today when --mode=smoke. pit reads state/l3_snapshots/*<=as_of.")
    parser.add_argument("--l3-pit-strict", action="store_true",
                        help="With --l3-mode=pit: fail if no snapshot <= as_of (default: warn + cat_score=50).")
    parser.add_argument("--split-date", dest="split_date", default=None,
                        help="YYYYMMDD boundary for in-sample/out-of-sample period_split. "
                             "trade_date < split_date -> 'discovery'; >= -> 'validation'. "
                             "Without this flag, only 'all' rows are emitted. "
                             "Use e.g. --split-date 20250101 to develop rules on 2024 and "
                             "validate on 2025, avoiding data-mining overfit.")
    args = parser.parse_args()
    if args.l3_mode is None:
        args.l3_mode = "neutralize" if args.mode == "production" else "today"
    if args.split_date:
        if not (isinstance(args.split_date, str) and len(args.split_date) == 8 and args.split_date.isdigit()):
            raise SystemExit(f"[FATAL] --split-date must be YYYYMMDD, got {args.split_date!r}")

    settings = enforce_mode(args)
    windows = settings["windows"]
    max_window = max(windows) if windows else 20

    selected_dates = []
    immature_included = []
    immature_skipped = []
    if not args.stats_only and args.periods > 0:
        start_date = args.start_date
        if not start_date:
            days = max(args.periods * 10, 60) if args.freq == "weekly" else max(args.periods * 40, 120)
            start_date = (datetime.strptime(args.end_date, "%Y%m%d") - timedelta(days=days)).strftime("%Y%m%d")
        trade_dates = get_trade_dates_from_tushare(start_date, args.end_date)
        if not trade_dates:
            raise RuntimeError(
                f"No trading dates returned for start={start_date}, end={args.end_date}. "
                "Check TUSHARE_TOKEN and trade_cal availability."
            )
        selected_dates, immature_included, immature_skipped = select_asof_dates(
            trade_dates, args.periods, args.freq, max_window,
            reference_date=trade_dates[-1], include_immature=args.include_immature,
        )
        if not selected_dates:
            raise RuntimeError(
                f"No mature as-of dates found within {start_date}..{args.end_date} "
                f"requiring >= {max_window} future trading days. "
                "Move --end-date back, or pass --include-immature for smoke testing."
            )
        if immature_included:
            print(f"[INFO] including immature as-of dates (future window < {max_window} trading days): "
                  f"{immature_included}")
        if immature_skipped:
            print(f"[INFO] skipped immature as-of dates: {immature_skipped}")
        print(f"[INFO] selected as-of dates: {', '.join(selected_dates)}")
        generate_candidates(
            selected_dates,
            args.python,
            output_root=GENERATED_DIR,
            skip_existing=not args.no_skip_existing,
            reuse_l3_cache=args.reuse_l3_cache,
            l3_mode=args.l3_mode,
            l3_pit_strict=args.l3_pit_strict,
        )
    elif args.stats_only:
        selected_dates, stats_source, last_report = select_stats_only_dates(args)
        if not selected_dates:
            raise SystemExit(
                "[FATAL] No generated as-of dates selected for stats-only. "
                "Pass --periods N, --start-date/--end-date, or generate candidates first."
            )
        if stats_source == "last-report" and isinstance(last_report.get("settings"), dict):
            prior = last_report["settings"]
            settings.update(prior)
            windows = list(settings.get("windows") or windows)
            max_window = max(windows) if windows else max_window
            print("[INFO] stats-only mode: inherited settings from previous backtest_report.json")
        print(f"[INFO] stats-only mode ({stats_source}); selected dates: {selected_dates}")

        # C1: pools' source.l3_mode is the data truth and must override any
        # CLI default or stale prior-report value. Refuses to proceed if pools
        # disagree, since the report cannot honestly describe a mixed set.
        pool_meta = validate_stats_only_pools(selected_dates, GENERATED_DIR)
        pool_modes = {d: m["l3_mode"] for d, m in pool_meta.items()}
        if pool_modes:
            unique_modes = set(pool_modes.values())
            if len(unique_modes) > 1:
                raise SystemExit(
                    "[FATAL] stats-only refuses to proceed: candidate pools have "
                    f"inconsistent source.l3_mode across as_of dates: {pool_modes}. "
                    "Regenerate the pools under a single l3_mode."
                )
            actual_mode = next(iter(unique_modes))
            if settings.get("l3_mode") != actual_mode:
                print(f"[INFO] stats-only: override settings.l3_mode "
                      f"{settings.get('l3_mode')!r} -> {actual_mode!r} "
                      "(read from generated/*/analysis_input.json:source.l3_mode)")
                settings["l3_mode"] = actual_mode
            pool_strict = {d: m["l3_pit_strict"] for d, m in pool_meta.items()}
            if pool_strict and len(set(pool_strict.values())) == 1:
                settings["l3_pit_strict"] = bool(next(iter(set(pool_strict.values()))))
    else:
        raise RuntimeError(
            "No as-of dates selected. Use --periods N to generate candidates, "
            "or use --stats-only to read existing generated pools."
        )

    validate_freq_vs_window(settings.get("freq", args.freq), max_window)

    if not GENERATED_DIR.exists():
        raise RuntimeError(
            f"Backtest source dir missing: {GENERATED_DIR.relative_to(ROOT)}. "
            "Run candidate generation first (drop --stats-only, or pass --periods N)."
        )
    source_root = GENERATED_DIR
    # Use settings (post-enforce_mode and post-stats-only-inheritance) so report
    # values and computed stats stay consistent even when prior settings are inherited.
    effective_mode = settings.get("mode", args.mode)
    effective_cost_pct = float(settings.get("cost_pct", args.cost_pct))
    effective_dedup_mode = settings.get("dedup_mode", args.dedup_mode)

    samples = load_analysis_inputs(source_root, date_filter=selected_dates)
    if selected_dates and samples.empty:
        raise RuntimeError(
            f"No samples loaded for selected_dates={selected_dates}. "
            "Check generated/YYYYMMDD/analysis_input.json files."
        )
    samples = apply_dedup(samples, effective_dedup_mode)

    forward_meta = {"status": "skipped_no_samples"}
    eligible_benchmark = pd.DataFrame()
    extra_variants = {}
    if not samples.empty:
        asof_set = sorted(samples["trade_date"].dropna().astype(str).unique().tolist())
        payload = fetch_forward_daily(asof_set, max_window, refresh=args.refresh_forward_daily)
        forward_meta = payload.get("meta", {})
        samples = attach_forward_returns(samples, windows, payload, cost_pct=effective_cost_pct)
        eligible_samples = load_eligible_universe(source_root, selected_dates)
        if not eligible_samples.empty:
            eligible_samples = attach_forward_returns(eligible_samples, windows, payload, cost_pct=effective_cost_pct)
            samples, eligible_benchmark = attach_eligible_excess(samples, eligible_samples, windows)
        esp_cap_samples = load_esp_cap_rerank_samples(source_root, selected_dates)
        if not esp_cap_samples.empty:
            esp_cap_samples = attach_forward_returns(esp_cap_samples, windows, payload, cost_pct=effective_cost_pct)
            if not eligible_samples.empty:
                esp_cap_samples, _ = attach_eligible_excess(esp_cap_samples, eligible_samples, windows)
            extra_variants["esp_cap_200_rerank"] = esp_cap_samples

    summary, factor_stats, rule6_stats, monthly_df, samples = build_stats(
        samples, windows, split_date=settings.get("split_date"))
    strategy_variant_stats, strategy_variant_monthly, variant_meta = build_strategy_variant_stats(
        samples, windows, split_date=settings.get("split_date"), extra_variants=extra_variants)
    portfolio_period_frames, portfolio_stat_frames = [], []
    variant_for_portfolio = {"baseline": samples}
    for name in STRATEGY_VARIANTS:
        variant_for_portfolio[name] = samples[_variant_mask(samples, name)].copy()
    variant_for_portfolio.update(extra_variants)
    for name, vdf in variant_for_portfolio.items():
        if vdf.empty:
            continue
        p_period, p_stats = build_portfolio_stats(
            vdf, windows, split_date=settings.get("split_date"), strategy_variant=name)
        if not p_period.empty:
            portfolio_period_frames.append(p_period)
        if not p_stats.empty:
            portfolio_stat_frames.append(p_stats)
    portfolio_period_returns = pd.concat(portfolio_period_frames, ignore_index=True) if portfolio_period_frames else pd.DataFrame()
    portfolio_stats_df = pd.concat(portfolio_stat_frames, ignore_index=True) if portfolio_stat_frames else pd.DataFrame()
    write_outputs(samples, summary, factor_stats, rule6_stats, monthly_df, windows,
                  source_root, selected_dates, immature_included, immature_skipped,
                  forward_meta, effective_mode, settings,
                  eligible_benchmark=eligible_benchmark,
                  strategy_variant_stats=strategy_variant_stats,
                  strategy_variant_monthly=strategy_variant_monthly,
                  portfolio_period_returns=portfolio_period_returns,
                  portfolio_stats=portfolio_stats_df,
                  variant_meta=variant_meta)

    print(f"[OK] mode={effective_mode}  samples={len(samples)}  dedup={effective_dedup_mode}  cost={effective_cost_pct}%")
    print(f"[OK] backtest outputs: {BACKTEST_DIR}")
    if not summary.empty:
        print(summary.to_string(index=False))


if __name__ == "__main__":
    main()

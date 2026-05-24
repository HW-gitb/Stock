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
            "benchmarks" -> dict[name -> DataFrame[trade_date, close]]
            "meta"       -> dict with date range / fetched_at / shape
    """
    if not asof_dates:
        return {"stocks": pd.DataFrame(columns=["ts_code", "trade_date", "open", "close", "adj_factor"]),
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
            sig_ok = (meta.get("start_date", "") <= start and meta.get("end_date", "") >= end
                      and meta.get("adj") == cache_signature["adj"]
                      and set(benches.keys()) >= set(BENCHMARKS.keys())
                      and isinstance(stocks, pd.DataFrame) and not stocks.empty)
            if sig_ok:
                print(f"[CACHE] forward_daily reused: {meta.get('start_date')}..{meta.get('end_date')} "
                      f"rows={len(stocks)} benchmarks={list(benches.keys())}")
                return {"stocks": stocks, "benchmarks": benches, "meta": meta}
        except Exception as e:
            print(f"[CACHE] forward_daily ignored ({e}); will refetch.")

    print(f"[FETCH] forward_daily {start}..{end}")
    pro = _tushare_pro()
    trade_dates = _trade_calendar(pro, start, end)
    if not trade_dates:
        raise RuntimeError(f"Tushare trade_cal returned no dates for {start}..{end}")

    stock_frames = []
    adj_frames = []
    for td in trade_dates:
        df = _ts_call(pro.daily, trade_date=td, fields="ts_code,trade_date,open,close")
        if df is not None and not df.empty:
            stock_frames.append(df)
        adj = _ts_call(pro.adj_factor, trade_date=td, fields="ts_code,trade_date,adj_factor")
        if adj is not None and not adj.empty:
            adj_frames.append(adj)

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
            "stock_codes": int(stocks["ts_code"].nunique())}

    with FORWARD_DAILY_CACHE.open("wb") as f:
        pickle.dump({"meta": meta, "stocks": stocks, "benchmarks": benches}, f)
    print(f"[FETCH] forward_daily saved stocks={len(stocks)} codes={meta['stock_codes']} "
          f"benchmarks={list(benches.keys())} -> {FORWARD_DAILY_CACHE.relative_to(ROOT)}")
    return {"stocks": stocks, "benchmarks": benches, "meta": meta}


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


def attach_forward_returns(samples, windows, daily_payload, cost_pct=DEFAULT_COST_PCT):
    samples = samples.copy()
    for window in windows:
        samples[f"ret_{window}d_close"] = pd.NA
        samples[f"ret_{window}d_t1"] = pd.NA
        samples[f"ret_{window}d_t1_net"] = pd.NA
        samples[f"ret_{window}d_status"] = "pending_no_future_price"
        for bname in BENCHMARKS:
            samples[f"ret_{window}d_{bname}"] = pd.NA
            samples[f"ret_{window}d_excess_{bname}"] = pd.NA

    stocks = daily_payload.get("stocks", pd.DataFrame())
    benches = daily_payload.get("benchmarks", {})
    if samples.empty or stocks.empty:
        return samples

    trade_dates = sorted(stocks["trade_date"].dropna().astype(str).unique().tolist())
    date_pos = {date: idx for idx, date in enumerate(trade_dates)}

    cols = ["ts_code", "trade_date", "open", "close", "adj_factor"]
    lookup = {}
    for row in stocks[cols].itertuples(index=False):
        lookup[(row.ts_code, row.trade_date)] = (row.open, row.close, row.adj_factor)

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
        # base close (for close-to-close reference)
        base_row = lookup.get((ts_code, trade_date))
        base_close = base_row[1] if base_row else None
        base_adj = base_row[2] if base_row else None
        if base_close is None or pd.isna(base_close) or float(base_close) == 0:
            base_close = row.get("close")
            base_adj = entry_adj  # fallback

        for window in windows:
            # T+1 open entry, then close on the Nth trading day after as_of.
            # Example: window=5 means buy T+1 open and exit T+5 close.
            exit_idx = base_idx + window
            if exit_idx >= len(trade_dates):
                samples.at[idx, f"ret_{window}d_status"] = "pending_immature_asof"
                continue
            exit_date = trade_dates[exit_idx]
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

RET_VARIANTS = ["close", "t1", "t1_net"] + [f"excess_{b}" for b in BENCHMARKS]


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


def summarize_returns(samples, windows, subset="all"):
    """Aggregate stats per (window, variant). `subset` is a label that goes
    into the output's `subset` column so multiple slices (all / tier1_only)
    can share one CSV without losing identity."""
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


def group_stats(samples, windows, group_col, label, variant="t1_net", subset="all"):
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


def monthly_stats(samples, windows, subset="all"):
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
    return samples


PRIMARY_SUBSET = "tier1_only"  # main reporting view: Tier2 filler dilutes signal


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
        ("overheat_flag", "risk_flag"),
        ("q0_dt_yoy_gt_200", "low_base_growth"),
        ("q1_dt_yoy_gt_200", "low_base_growth"),
        ("esp_raw_gt_200", "low_base_growth"),
    ]


def _build_stats_for_subset(samples, windows, subset_label):
    """Compute summary / factor / rule6 / monthly for ONE subset slice."""
    summary = summarize_returns(samples, windows, subset=subset_label)
    factor_rows = []
    for group_col, label in _factor_group_specs():
        factor_rows.extend(group_stats(samples, windows, group_col, label, subset=subset_label))
    rule6_rows = []
    rule6_status_cols = [c for c in samples.columns if c.startswith("rule6_") and c.endswith("_status")]
    for col in sorted(rule6_status_cols):
        rule6_rows.extend(group_stats(samples, windows, col, "rule6_status", subset=subset_label))
    monthly_df = monthly_stats(samples, windows, subset=subset_label)
    return summary, pd.DataFrame(factor_rows), pd.DataFrame(rule6_rows), monthly_df


def build_stats(samples, windows):
    """Build stats for two subsets and stack them:
      - 'all'         : every sample (Tier1 + Tier2 filler)
      - 'tier1_only'  : Tier == 'Tier1' subset (primary reporting view)

    Reason: 24-period evidence (t=-2.27) shows Tier2 filler is a significant
    negative-alpha pool; mixing it into 'all' aggregate dilutes the real
    Tier1 strategy signal. Tier1-only is now the headline reporting view.
    See findings_cc_24p §9 for the rationale.
    """
    samples = build_group_columns(samples)

    # All-subset stats (legacy headline; kept for transparency / regression compare)
    sum_all, fac_all, rul_all, mon_all = _build_stats_for_subset(samples, windows, "all")

    # Tier1-only subset (new primary view)
    tier1_samples = samples[samples["tier_group"] == "Tier1"].copy()
    if len(tier1_samples):
        sum_t1, fac_t1, rul_t1, mon_t1 = _build_stats_for_subset(tier1_samples, windows, "tier1_only")
    else:
        sum_t1 = fac_t1 = rul_t1 = mon_t1 = pd.DataFrame()

    summary = pd.concat([sum_all, sum_t1], ignore_index=True)
    factor_stats = pd.concat([fac_all, fac_t1], ignore_index=True)
    rule6_stats = pd.concat([rul_all, rul_t1], ignore_index=True)
    monthly_df = pd.concat([mon_all, mon_t1], ignore_index=True)

    return summary, factor_stats, rule6_stats, monthly_df, samples


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
                  forward_meta, mode, settings):
    BACKTEST_DIR.mkdir(parents=True, exist_ok=True)
    samples.to_csv(BACKTEST_DIR / "rank_samples.csv", index=False, encoding="utf-8-sig")
    summary.to_csv(BACKTEST_DIR / "summary_by_window.csv", index=False, encoding="utf-8-sig")
    factor_stats.to_csv(BACKTEST_DIR / "factor_group_stats.csv", index=False, encoding="utf-8-sig")
    rule6_stats.to_csv(BACKTEST_DIR / "rule6_stats.csv", index=False, encoding="utf-8-sig")
    monthly_df.to_csv(BACKTEST_DIR / "monthly_stats.csv", index=False, encoding="utf-8-sig")

    report = {
        "schema_name": "rank_backtest_report",
        "schema_version": "1.6.0",
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "preset": "a_short",
        "mode": mode,
        "engineering_smoke": mode == "smoke",
        "settings": settings,
        "windows": windows,
        "sample_count": int(len(samples)),
        "selected_dates": selected_dates,
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
        },
        "return_variants": {
            "close": "qfq close-to-close (no T+1, no cost). Reference only.",
            "t1": "qfq T+1 open entry to close of T+W. Gross of cost.",
            "t1_net": "qfq T+1 open entry minus round-trip cost (default 0.16%).",
            "excess_csi300": "t1 minus CSI300 same-window return (entry_date to exit_date).",
            "excess_csi1000": "t1 minus CSI1000 same-window return.",
        },
        "limitations": [
            "Backtest writes generated candidate pools and intermediate EGS CSV/XLSX artifacts under result/a_short/backtest/generated/ (isolated from official output).",
            "Forward returns are qfq-adjusted via Tushare adj_factor; transaction cost defaults to 0.16% round-trip.",
            "Benchmark excess returns compare stock T+1 open-to-close returns against benchmark close-to-close returns over the same entry/exit dates; this can introduce a small intraday entry-basis difference.",
            "Backtest mode skips cninfo, web news, and DeepSeek Stage3 checks, so historical candidate pools do not include the same regulatory/policy veto layer as production screening.",
            "Adjacent as-of dates with overlapping forward windows correlate; variance is therefore not iid -- use monthly freq for max_window=20 or apply --dedup-mode.",
            "Stock universe includes delisted stocks per as_of (B2 fixed); industry membership is point-in-time via in_date/out_date (B3a fixed).",
            "Financial data filtered by ann_date<=as_of; Tushare returns the latest revision of each quarter rather than the originally-disclosed version (Tushare API limitation, not fixable here).",
            _l3_limitation_line(settings),
        ],
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
    args = parser.parse_args()
    if args.l3_mode is None:
        args.l3_mode = "neutralize" if args.mode == "production" else "today"

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
    if not samples.empty:
        asof_set = sorted(samples["trade_date"].dropna().astype(str).unique().tolist())
        payload = fetch_forward_daily(asof_set, max_window, refresh=args.refresh_forward_daily)
        forward_meta = payload.get("meta", {})
        samples = attach_forward_returns(samples, windows, payload, cost_pct=effective_cost_pct)

    summary, factor_stats, rule6_stats, monthly_df, samples = build_stats(samples, windows)
    write_outputs(samples, summary, factor_stats, rule6_stats, monthly_df, windows,
                  source_root, selected_dates, immature_included, immature_skipped,
                  forward_meta, effective_mode, settings)

    print(f"[OK] mode={effective_mode}  samples={len(samples)}  dedup={effective_dedup_mode}  cost={effective_cost_pct}%")
    print(f"[OK] backtest outputs: {BACKTEST_DIR}")
    if not summary.empty:
        print(summary.to_string(index=False))


if __name__ == "__main__":
    main()

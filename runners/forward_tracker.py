#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Phase 3.5 live forward tracker.

Captures key fields from each weekly screening run and (later) backfills
forward 5d/10d/20d returns using the same T+1-open / qfq / 0.16%-cost
convention as backtest_rank.py, so live vs backtest comparisons are
apples-to-apples.

Purpose: accumulate live data to settle open questions from Phase 3:
- Does the ESP reverse signal (Phase 3.3, 3.4) persist in live mode, or
  fade once Tushare revision contamination is gone?
- Does score_ge_60 retain risk-mitigation properties (max_dd, win_rate)
  on new as_of dates?
- Do the 4 hard veto rules continue to overlap 100% with EGS Tier1->Tier2
  downgrade in new regimes?

Bypass discipline (same as data_canary.py): this script is monitoring,
not gating. It must not break weekly_screening's exit code, must not
re-run EGS, must not fetch fresh forward data beyond what is needed
for the rows being backfilled.

Two subcommands:
  capture --as-of YYYYMMDD
    Read result/a_short/<as_of>/analysis_input.json, append one row per
    candidate to logs/forward_tracker.csv. Skip rows where (as_of, ts_code)
    already exists. Forward return columns left empty.
  backfill [--windows 5,10,20]
    Find rows whose forward window has matured (as_of + window + buffer
    trading days <= today) and whose status is not 'ok'. Group by as_of,
    reuse backtest_rank.fetch_forward_daily + attach_forward_returns, then
    write the t1_net columns and status back to the CSV.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runners.backtest_rank import (
    BENCHMARKS,
    FORWARD_DAILY_CACHE,
    _benchmark_frame_has_same_anchor_fields,
    attach_forward_returns,
    fetch_forward_daily,
)

TRACKER_CSV = ROOT / "logs" / "forward_tracker.csv"
LIVE_RESULT_ROOT = ROOT / "result" / "a_short"

# Columns kept in the tracker. Order matters: read/write round-trips must
# preserve column order so older CSVs stay diff-friendly.
SCHEMA_COLUMNS = [
    "as_of",
    "captured_at",
    "ts_code",
    "name",
    "tier",
    "final_score",
    "esp_score",
    "cat_score",
    "l4_score",
    "esp_raw",
    "q0_dt_yoy",
    "q1_dt_yoy",
    "chasing_high",
    "overheat_flag",
    "l2_name",
    "base_close",
    "entry_date",
    "entry_unbuyable_reason",
    "ret_5d_t1_net",
    "ret_5d_status",
    "ret_10d_t1_net",
    "ret_10d_status",
    "ret_20d_t1_net",
    "ret_20d_status",
    "backfilled_at",
]

DEFAULT_WINDOWS = [5, 10, 20]
# Calendar-day pad beyond the trading-day window estimate. Lets the cache
# refresh job land Tushare's close before tracker tries to read it.
MATURE_BUFFER_CALENDAR_DAYS = 3


# ============================================================
# Capture
# ============================================================

def _get(d, *keys, default=None):
    """Nested dict get; returns default if any path segment missing/None."""
    cur = d
    for k in keys:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(k)
        if cur is None:
            return default
    return cur


def _candidate_row(as_of: str, captured_at: str, c: dict) -> dict:
    return {
        "as_of": as_of,
        "captured_at": captured_at,
        "ts_code": c.get("ts_code"),
        "name": c.get("name"),
        "tier": _get(c, "selection", "tier"),
        "final_score": _get(c, "scores", "final_score"),
        "esp_score": _get(c, "scores", "esp_score"),
        "cat_score": _get(c, "scores", "cat_score"),
        "l4_score": _get(c, "scores", "l4_score"),
        "esp_raw": _get(c, "fundamental", "expectation", "esp_raw"),
        "q0_dt_yoy": _get(c, "fundamental", "profitability", "q0_dt_yoy"),
        "q1_dt_yoy": _get(c, "fundamental", "profitability", "q1_dt_yoy"),
        "chasing_high": _get(c, "derived_flags", "chasing_high"),
        "overheat_flag": _get(c, "derived_flags", "overheat_flag"),
        "l2_name": _get(c, "industry", "sw_l2_name"),
        "base_close": _get(c, "quote", "close"),
        # backfill-filled columns below
        "entry_date": pd.NA,
        "entry_unbuyable_reason": pd.NA,
        "ret_5d_t1_net": pd.NA,
        "ret_5d_status": "pending_capture",
        "ret_10d_t1_net": pd.NA,
        "ret_10d_status": "pending_capture",
        "ret_20d_t1_net": pd.NA,
        "ret_20d_status": "pending_capture",
        "backfilled_at": pd.NA,
    }


def _load_existing_tracker() -> pd.DataFrame:
    if not TRACKER_CSV.exists():
        return pd.DataFrame(columns=SCHEMA_COLUMNS)
    df = pd.read_csv(TRACKER_CSV, dtype={"as_of": str, "ts_code": str})
    for col in SCHEMA_COLUMNS:
        if col not in df.columns:
            df[col] = pd.NA
    return df[SCHEMA_COLUMNS]


def _write_tracker(df: pd.DataFrame) -> None:
    TRACKER_CSV.parent.mkdir(parents=True, exist_ok=True)
    df = df[SCHEMA_COLUMNS].copy()
    df.sort_values(["as_of", "ts_code"], inplace=True, kind="mergesort")
    df.to_csv(TRACKER_CSV, index=False, encoding="utf-8-sig")


def capture(as_of: str) -> int:
    input_path = LIVE_RESULT_ROOT / as_of / "analysis_input.json"
    if not input_path.exists():
        print(f"[FATAL] analysis_input.json missing: {input_path.relative_to(ROOT)}")
        return 2
    with input_path.open("r", encoding="utf-8") as f:
        payload = json.load(f)
    candidates = payload.get("candidates") or []
    if not candidates:
        print(f"[WARN] {as_of}: zero candidates in analysis_input.json (nothing to capture)")
        return 0

    captured_at = datetime.now().astimezone().isoformat(timespec="seconds")
    new_rows = [_candidate_row(as_of, captured_at, c) for c in candidates]
    new_df = pd.DataFrame(new_rows, columns=SCHEMA_COLUMNS)

    existing = _load_existing_tracker()
    if not existing.empty:
        key = ["as_of", "ts_code"]
        existing[key[0]] = existing[key[0]].astype(str)
        existing[key[1]] = existing[key[1]].astype(str)
        new_df[key[0]] = new_df[key[0]].astype(str)
        new_df[key[1]] = new_df[key[1]].astype(str)
        # Drop new rows that already exist (idempotent re-runs); keep the
        # existing row so we don't lose any backfilled return values.
        mask_dup = new_df.set_index(key).index.isin(existing.set_index(key).index)
        n_dup = int(mask_dup.sum())
        new_df = new_df[~mask_dup]
        if n_dup:
            print(f"[INFO] {as_of}: {n_dup} rows already in tracker, skipping")

    if new_df.empty:
        print(f"[OK] {as_of}: nothing new to append (tracker rows: {len(existing)})")
        return 0

    combined = pd.concat([existing, new_df], ignore_index=True)
    _write_tracker(combined)
    print(f"[OK] {as_of}: appended {len(new_df)} rows (tracker rows now: {len(combined)})")
    return 0


# ============================================================
# Backfill
# ============================================================

def _today_yyyymmdd() -> str:
    return datetime.now().strftime("%Y%m%d")


def _mature_as_ofs(df: pd.DataFrame, today: str, windows: list[int]) -> list[str]:
    """Pick distinct as_of values where at least one pending window is mature.

    Uses the smallest window as the maturity threshold so a 5d row can be
    backfilled even if its 10d/20d siblings are still pending. The per-row
    status from attach_forward_returns will honestly report which
    sub-windows are still pending_immature_asof.

    Calendar-day approximation: 1 trading day ~ 1.4 calendar days; the
    +MATURE_BUFFER_CALENDAR_DAYS pad accounts for weekends/holidays.
    """
    min_window = min(windows)
    today_dt = pd.to_datetime(today, format="%Y%m%d")
    # 5 trading days span ~7 calendar days; add a calendar-day buffer so we
    # don't poke the cache before today's close is published.
    threshold_calendar_days = int(min_window * 1.4) + MATURE_BUFFER_CALENDAR_DAYS
    pending_rows = []
    for w in windows:
        status_col = f"ret_{w}d_status"
        if status_col not in df.columns:
            continue
        pending_mask = df[status_col].astype(str).ne("ok") & df[status_col].astype(str).ne("pending_no_entry_limit_up")
        pending_rows.append(df.loc[pending_mask, "as_of"].astype(str))
    if not pending_rows:
        return []
    pending_as_of = pd.concat(pending_rows).unique().tolist()
    out = []
    for as_of in sorted(pending_as_of):
        as_of_dt = pd.to_datetime(str(as_of), format="%Y%m%d")
        gap_days = (today_dt - as_of_dt).days
        if gap_days >= threshold_calendar_days:
            out.append(str(as_of))
    return out


def backfill(windows: list[int]) -> int:
    df = _load_existing_tracker()
    if df.empty:
        print("[OK] tracker is empty, nothing to backfill")
        return 0

    today = _today_yyyymmdd()
    mature_as_ofs = _mature_as_ofs(df, today, windows)
    if not mature_as_ofs:
        print(f"[OK] no mature as_of with pending rows (today={today})")
        return 0
    print(f"[INFO] mature as_of with pending rows: {mature_as_ofs}")

    max_window = max(windows)
    # Cache coverage gate: tracker is a sidebar; it must not trigger a
    # universe-wide Tushare refetch on its own. The backtest forward_daily
    # cache is the shared source. If the cache does not cover the tracker
    # as_of range or lacks same-anchor benchmark open, bail with clear
    # instructions and let the user trigger the narrowest safe refresh.
    coverage_ok, msg = _check_cache_coverage(mature_as_ofs, max_window)
    if not coverage_ok:
        print(f"[SKIP] {msg}")
        for line in _cache_refresh_hint(msg):
            print(line)
        return 0

    payload = fetch_forward_daily(mature_as_ofs, max_window, refresh=False)

    # attach_forward_returns expects samples with trade_date column;
    # rename our as_of -> trade_date in a slim view.
    work = df[df["as_of"].astype(str).isin(mature_as_ofs)].copy()
    if work.empty:
        return 0
    work["trade_date"] = work["as_of"].astype(str)
    # name, board not in tracker schema; attach_forward_returns reads them
    # only for limit-up sourcing. board can be derived from ts_code.
    work["board"] = work["ts_code"].apply(_board_from_code)
    work["close"] = work["base_close"]  # fallback used inside attach_forward_returns
    work = attach_forward_returns(work, windows, payload)

    # Write the resulting returns back into df by (as_of, ts_code).
    work_idx = work.set_index(["as_of", "ts_code"])
    df_idx = df.set_index(["as_of", "ts_code"])

    updated_keys = []
    backfilled_at = datetime.now().astimezone().isoformat(timespec="seconds")
    for key, row in work_idx.iterrows():
        if key not in df_idx.index:
            continue
        cur_status = {w: df_idx.at[key, f"ret_{w}d_status"] for w in windows}
        if all(str(s) == "ok" for s in cur_status.values()):
            continue
        df_idx.at[key, "entry_date"] = row.get("entry_date") if pd.notna(row.get("entry_date")) else df_idx.at[key, "entry_date"]
        df_idx.at[key, "entry_unbuyable_reason"] = row.get("entry_unbuyable_reason") if pd.notna(row.get("entry_unbuyable_reason")) else df_idx.at[key, "entry_unbuyable_reason"]
        for w in windows:
            new_status = row.get(f"ret_{w}d_status")
            new_val = row.get(f"ret_{w}d_t1_net")
            # Only overwrite if attach produced a useful update — keep prior
            # 'ok' entries (shouldn't happen since we filtered) and avoid
            # clobbering a real value with NaN.
            if pd.notna(new_status):
                df_idx.at[key, f"ret_{w}d_status"] = new_status
            if pd.notna(new_val):
                df_idx.at[key, f"ret_{w}d_t1_net"] = new_val
        df_idx.at[key, "backfilled_at"] = backfilled_at
        updated_keys.append(key)

    df_out = df_idx.reset_index()[SCHEMA_COLUMNS]
    _write_tracker(df_out)
    print(f"[OK] backfilled {len(updated_keys)} rows across {len(mature_as_ofs)} as_of dates")
    return 0


def _cache_refresh_hint(message: str) -> list[str]:
    if "benchmark input is not same-anchor ready" in message or "benchmark frames" in message:
        return [
            "[HINT] Patch benchmark open/close in the shared forward_daily cache before backfilling. Example:",
            "       python runners\\refresh_forward_daily_benchmark_open_tushare.py",
            "       (this fetches only CSI300/CSI1000 index_daily trade_date/open/close)",
        ]
    return [
        "[HINT] Refresh the shared forward_daily cache before backfilling. Example:",
        "       python runners\\backtest_rank.py --mode production --stats-only \\",
        "           --refresh-forward-daily --windows 5,10,20",
        "       (this refetches forward daily for the backtest+tracker shared cache)",
    ]


def _check_cache_coverage(as_ofs: list[str], max_window: int) -> tuple[bool, str]:
    """Verify the shared backtest forward_daily cache covers tracker as_ofs.

    Returns (ok, message). Reads the pickle cache only, no fetch.
    """
    if not FORWARD_DAILY_CACHE.exists():
        return False, f"forward_daily cache not found at {FORWARD_DAILY_CACHE.relative_to(ROOT)}"
    try:
        import pickle
        with FORWARD_DAILY_CACHE.open("rb") as f:
            cached = pickle.load(f)
    except Exception as e:
        return False, f"forward_daily cache unreadable: {e}"
    meta = cached.get("meta", {})
    cache_start = str(meta.get("start_date", ""))
    cache_end = str(meta.get("end_date", ""))
    benches = cached.get("benchmarks")
    if not isinstance(benches, dict):
        return False, "forward_daily cache missing benchmark frames with trade_date/open/close fields"
    missing_benches = sorted(set(BENCHMARKS) - set(benches))
    close_only_benches = sorted(
        name
        for name in BENCHMARKS
        if name in benches and not _benchmark_frame_has_same_anchor_fields(benches.get(name))
    )
    if missing_benches or close_only_benches:
        problems = []
        if missing_benches:
            problems.append(f"missing benchmarks: {', '.join(missing_benches)}")
        if close_only_benches:
            problems.append(f"missing same-anchor trade_date/open/close fields: {', '.join(close_only_benches)}")
        return False, "forward_daily cache benchmark input is not same-anchor ready (" + "; ".join(problems) + ")"
    asof_min = min(as_ofs)
    # We need cache to extend to at least asof_max + max_window calendar days.
    asof_max = max(as_ofs)
    required_end = _shift_yyyymmdd_safe(asof_max, max_window + 5)
    if cache_start > asof_min or cache_end < required_end:
        return False, (f"cache range {cache_start}..{cache_end} does not cover "
                       f"tracker as_of {asof_min}..{asof_max} +{max_window}d window "
                       f"(need end >= {required_end})")
    return True, "ok"


def _shift_yyyymmdd_safe(d: str, days: int) -> str:
    """Calendar-day shift; tracker uses this for the cache coverage check only."""
    return (pd.to_datetime(d, format="%Y%m%d") + pd.Timedelta(days=days)).strftime("%Y%m%d")


def _board_from_code(ts_code):
    """Match backtest_rank._board_from_code so limit-up checks line up."""
    symbol = str(ts_code).split(".")[0]
    if symbol.startswith(("300", "301")):
        return "chinext"
    if symbol.startswith(("688", "689")):
        return "star"
    if symbol.startswith(("8", "4", "920")):
        return "bj"
    return "main"


# ============================================================
# CLI
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="Phase 3.5 live forward tracker (capture + backfill).")
    sub = parser.add_subparsers(dest="cmd", required=True)
    cap = sub.add_parser("capture", help="Append one row per candidate from result/a_short/<as_of>/analysis_input.json.")
    cap.add_argument("--as-of", required=True, help="YYYYMMDD trading day.")
    bf = sub.add_parser("backfill", help="Fill forward returns for matured pending rows.")
    bf.add_argument("--windows", default="5,10,20")
    args = parser.parse_args()

    if args.cmd == "capture":
        return capture(args.as_of)
    if args.cmd == "backfill":
        windows = [int(w) for w in args.windows.split(",") if w.strip()]
        return backfill(windows)
    return 1


if __name__ == "__main__":
    sys.exit(main())

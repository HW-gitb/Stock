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
import os
import sys
import tempfile
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
from engine.data.analysis_input_contract import validate_analysis_input_contract
from engine.a_share_market_clock import a_share_market_date

TRACKER_CSV = ROOT / "logs" / "forward_tracker.csv"
LIVE_RESULT_ROOT = ROOT / "result" / "a_short"

# Columns kept in the tracker. Order matters: read/write round-trips must
# preserve column order so older CSVs stay diff-friendly.
SCHEMA_COLUMNS = [
    "as_of",
    "captured_at",
    "run_id",
    "candidate_digest",
    "decision_as_of",
    "run_date",
    "price_data_through",
    "stage3_candidate_count",
    "runtime_configuration_fingerprint",
    "ts_code",
    "name",
    "analysis_role",
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
    "industry_heat_score",
    "industry_trend",
    "industry_trend_source_as_of",
    "industry_trend_classifier_version",
    "industry_trend_source_id",
    "industry_trend_headwind_max",
    "industry_trend_tailwind_min",
    "industry_trend_configuration_fingerprint",
    "industry_trend_validation_status",
    "raw_concept_ids",
    "canonical_themes_json",
    "canonical_theme_ids",
    "primary_canonical_theme_id",
    "canonical_theme_roles",
    "canonical_theme_role_confidence",
    "theme_taxonomy_configuration_fingerprint",
    "theme_taxonomy_source_as_of",
    "theme_taxonomy_l3_provider",
    "theme_taxonomy_l3_snapshot_date",
    "theme_taxonomy_l3_coverage_digest",
    "theme_taxonomy_l3_coverage_complete",
    "theme_taxonomy_l3_scoring_universe",
    "theme_taxonomy_l3_validation_status",
    "theme_heat_score",
    "theme_breadth_pass",
    "theme_persistence_mult",
    "theme_fit_score",
    "theme_fit_pass",
    "forward_live",
    "historical_replay",
    "base_close",
    "entry_date",
    "entry_unbuyable_reason",
    "ret_5d_t1_net",
    "ret_5d_excess_csi300",
    "ret_5d_excess_csi1000",
    "ret_5d_status",
    "ret_10d_t1_net",
    "ret_10d_t1_net_unit",
    "ret_10d_exit_date",
    "ret_10d_excess_csi300",
    "ret_10d_excess_csi1000",
    "ret_10d_status",
    "ret_20d_t1_net",
    "ret_20d_excess_csi300",
    "ret_20d_excess_csi1000",
    "ret_20d_status",
    "backfilled_at",
]
TRACKER_STRING_COLUMNS = {
    "as_of": str, "decision_as_of": str, "run_date": str,
    "price_data_through": str, "industry_trend_source_as_of": str,
    "theme_taxonomy_source_as_of": str, "theme_taxonomy_l3_snapshot_date": str,
    "entry_date": str, "ret_10d_exit_date": str, "ts_code": str,
}

DEFAULT_WINDOWS = [5, 10, 20]
# Calendar-day pad beyond the trading-day window estimate. Lets the cache
# refresh job land Tushare's close before tracker tries to read it.
MATURE_BUFFER_CALENDAR_DAYS = 3
TERMINAL_FORWARD_STATUSES = {
    "ok",
    "pending_no_entry_limit_up",
    "pending_missing_future_close",
    "pending_return_conversion_failed",
}
DECISION_TIME_COLUMNS = tuple(
    column for column in SCHEMA_COLUMNS[:SCHEMA_COLUMNS.index("entry_date")]
    if column != "captured_at"
)


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


def _candidate_row(as_of: str, captured_at: str, run_id: str, candidate_digest: str, c: dict,
                   l3_mode: str | None = None, *, decision_as_of: str | None = None,
                   run_date: str | None = None, price_data_through: str | None = None,
                   stage3_candidate_count: int | None = None,
                   runtime_configuration_fingerprint: str | None = None) -> dict:
    industry = _get(c, "industry", default={}) or {}
    signal = industry.get("industry_trend_signal") if isinstance(industry, dict) else {}
    signal = signal if isinstance(signal, dict) else {}
    thresholds = signal.get("thresholds") if isinstance(signal.get("thresholds"), dict) else {}
    taxonomy = _get(c, "catalyst", "theme_taxonomy", default={}) or {}
    themes = taxonomy.get("canonical_themes") if isinstance(taxonomy, dict) else []
    themes = themes if isinstance(themes, list) else []
    raw_concepts = taxonomy.get("raw_concepts") if isinstance(taxonomy, dict) else []
    raw_concepts = raw_concepts if isinstance(raw_concepts, list) else []
    metrics = taxonomy.get("comparison_metrics") if isinstance(taxonomy, dict) else {}
    metrics = metrics if isinstance(metrics, dict) else {}
    l3_provenance = taxonomy.get("l3_provenance") if isinstance(taxonomy, dict) else {}
    l3_provenance = l3_provenance if isinstance(l3_provenance, dict) else {}
    theme_ids = [str(t.get("theme_id")) for t in themes if isinstance(t, dict) and t.get("theme_id")]
    theme_roles = {str(t.get("theme_id")): str(t.get("role", "unknown"))
                   for t in themes if isinstance(t, dict) and t.get("theme_id")}
    role_confidence = {str(t.get("theme_id")): str(t.get("role_confidence", "unknown"))
                       for t in themes if isinstance(t, dict) and t.get("theme_id")}
    forward_live = str(l3_mode or "") == "today"
    return {
        "as_of": as_of,
        "captured_at": captured_at,
        "run_id": run_id,
        "candidate_digest": candidate_digest,
        "decision_as_of": decision_as_of,
        "run_date": run_date,
        "price_data_through": price_data_through,
        "stage3_candidate_count": stage3_candidate_count,
        "runtime_configuration_fingerprint": runtime_configuration_fingerprint,
        "ts_code": c.get("ts_code"),
        "name": c.get("name"),
        "analysis_role": c.get("analysis_role"),
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
        "industry_heat_score": signal.get("industry_heat_score"),
        "industry_trend": signal.get("classification"),
        "industry_trend_source_as_of": signal.get("source_as_of"),
        "industry_trend_classifier_version": signal.get("classifier_version"),
        "industry_trend_source_id": signal.get("source_id"),
        "industry_trend_headwind_max": thresholds.get("headwind_max"),
        "industry_trend_tailwind_min": thresholds.get("tailwind_min"),
        "industry_trend_configuration_fingerprint": signal.get("configuration_fingerprint"),
        "industry_trend_validation_status": signal.get("validation_status"),
        "raw_concept_ids": json.dumps([str(item.get("concept_id")) for item in raw_concepts
                                        if isinstance(item, dict) and item.get("concept_id")], ensure_ascii=False),
        "canonical_themes_json": json.dumps(themes, ensure_ascii=False, sort_keys=True),
        "canonical_theme_ids": json.dumps(theme_ids, ensure_ascii=False),
        "primary_canonical_theme_id": taxonomy.get("primary_canonical_theme_id") if isinstance(taxonomy, dict) else None,
        "canonical_theme_roles": json.dumps(theme_roles, ensure_ascii=False, sort_keys=True),
        "canonical_theme_role_confidence": json.dumps(role_confidence, ensure_ascii=False, sort_keys=True),
        "theme_taxonomy_configuration_fingerprint": taxonomy.get("taxonomy_configuration_fingerprint") if isinstance(taxonomy, dict) else None,
        "theme_taxonomy_source_as_of": taxonomy.get("source_as_of") if isinstance(taxonomy, dict) else None,
        "theme_taxonomy_l3_provider": l3_provenance.get("provider"),
        "theme_taxonomy_l3_snapshot_date": l3_provenance.get("snapshot_date"),
        "theme_taxonomy_l3_coverage_digest": l3_provenance.get("coverage_digest"),
        "theme_taxonomy_l3_coverage_complete": l3_provenance.get("coverage_complete"),
        "theme_taxonomy_l3_scoring_universe": l3_provenance.get("scoring_universe"),
        "theme_taxonomy_l3_validation_status": l3_provenance.get("validation_status"),
        "theme_heat_score": metrics.get("theme_heat_score"),
        "theme_breadth_pass": metrics.get("breadth_pass"),
        "theme_persistence_mult": metrics.get("persistence_mult"),
        "theme_fit_score": metrics.get("fit_score"),
        "theme_fit_pass": metrics.get("fit_pass"),
        "forward_live": forward_live,
        "historical_replay": not forward_live,
        "base_close": _get(c, "quote", "close"),
        # backfill-filled columns below
        "entry_date": pd.NA,
        "entry_unbuyable_reason": pd.NA,
        "ret_5d_t1_net": pd.NA,
        "ret_5d_excess_csi300": pd.NA,
        "ret_5d_excess_csi1000": pd.NA,
        "ret_5d_status": "pending_capture",
        "ret_10d_t1_net": pd.NA,
        "ret_10d_t1_net_unit": "percentage_points",
        "ret_10d_exit_date": pd.NA,
        "ret_10d_excess_csi300": pd.NA,
        "ret_10d_excess_csi1000": pd.NA,
        "ret_10d_status": "pending_capture",
        "ret_20d_t1_net": pd.NA,
        "ret_20d_excess_csi300": pd.NA,
        "ret_20d_excess_csi1000": pd.NA,
        "ret_20d_status": "pending_capture",
        "backfilled_at": pd.NA,
    }


def _load_existing_tracker() -> pd.DataFrame:
    if not TRACKER_CSV.exists():
        return pd.DataFrame(columns=SCHEMA_COLUMNS)
    df = pd.read_csv(TRACKER_CSV, dtype=TRACKER_STRING_COLUMNS)
    for col in SCHEMA_COLUMNS:
        if col not in df.columns:
            df[col] = pd.NA
    return df[SCHEMA_COLUMNS]


def _write_tracker(df: pd.DataFrame) -> None:
    TRACKER_CSV.parent.mkdir(parents=True, exist_ok=True)
    df = df[SCHEMA_COLUMNS].copy()
    df.sort_values(["as_of", "ts_code"], inplace=True, kind="mergesort")
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{TRACKER_CSV.name}.",
        suffix=".tmp",
        dir=str(TRACKER_CSV.parent),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8-sig", newline="") as handle:
            df.to_csv(handle, index=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, TRACKER_CSV)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def _decision_cohort_matches(existing: pd.DataFrame, incoming: pd.DataFrame) -> bool:
    """Compare every decision-time field while ignoring later settlement and capture timestamp."""
    if len(existing) != len(incoming):
        return False

    def canonical(value):
        if value is None or (not isinstance(value, (list, dict)) and pd.isna(value)):
            return ("missing",)
        if isinstance(value, (bool, np.bool_)):
            return ("bool", bool(value))
        if isinstance(value, (int, float, np.integer, np.floating)) and not isinstance(value, bool):
            number = float(value)
            return ("number", number) if np.isfinite(number) else ("missing",)
        return ("text", str(value))

    def canonical_rows(frame: pd.DataFrame):
        rows = []
        for row in frame.reindex(columns=DECISION_TIME_COLUMNS).to_dict(orient="records"):
            rows.append(tuple(canonical(row.get(column)) for column in DECISION_TIME_COLUMNS))
        code_index = DECISION_TIME_COLUMNS.index("ts_code")
        return sorted(rows, key=lambda row: row[code_index])

    return canonical_rows(existing) == canonical_rows(incoming)


def capture(as_of: str) -> int:
    input_path = LIVE_RESULT_ROOT / as_of / "analysis_input.json"
    if not input_path.exists():
        print(f"[FATAL] analysis_input.json missing: {input_path.relative_to(ROOT)}")
        return 2
    with input_path.open("r", encoding="utf-8") as f:
        payload = json.load(f)
    try:
        validate_analysis_input_contract(payload, label=f"forward capture {as_of}")
    except Exception as exc:
        print(f"[FATAL] invalid analysis_input: {exc}")
        return 2
    if str(payload.get("trade_date")) != str(as_of):
        print(f"[FATAL] analysis_input trade_date {payload.get('trade_date')} != --as-of {as_of}")
        return 2
    identity = ((payload.get("source") or {}).get("run_identity") or {})
    run_id = identity.get("run_id")
    digest = identity.get("candidate_digest")
    if not run_id or not digest:
        print("[FATAL] analysis_input missing run identity; refusing ambiguous same-day cohort")
        return 2
    candidates = payload.get("candidates") or []
    decision_as_of = str(payload.get("decision_as_of") or payload.get("trade_date") or "")
    run_date = str(payload.get("run_date") or ((payload.get("source") or {}).get("clocks") or {}).get("run_date") or "")
    price_data_through = str(
        payload.get("price_data_through")
        or ((payload.get("source") or {}).get("clocks") or {}).get("price_data_through")
        or ""
    )
    runtime_configuration_fingerprint = str(
        (((payload.get("source") or {}).get("runtime_configuration") or {}).get(
            "configuration_fingerprint"
        ) or "")
    )

    captured_at = datetime.now().astimezone().isoformat(timespec="seconds")
    l3_mode = (payload.get("source") or {}).get("l3_mode")
    new_rows = [_candidate_row(
        as_of, captured_at, run_id, digest, c, l3_mode=l3_mode,
        decision_as_of=decision_as_of,
        run_date=run_date,
        price_data_through=price_data_through,
        stage3_candidate_count=len(candidates),
        runtime_configuration_fingerprint=runtime_configuration_fingerprint,
    )
                for c in candidates]
    new_df = pd.DataFrame(new_rows, columns=SCHEMA_COLUMNS)

    existing = _load_existing_tracker()
    same_day = existing[existing["as_of"].astype(str) == str(as_of)] if not existing.empty else existing
    expected_codes = sorted(str(row["ts_code"]) for row in new_rows)
    captured_codes = sorted(same_day["ts_code"].dropna().astype(str).tolist()) if not same_day.empty else []
    if not same_day.empty and set(same_day["run_id"].dropna().astype(str)) == {run_id} and \
            set(same_day["candidate_digest"].dropna().astype(str)) == {digest} and \
            captured_codes == expected_codes and _decision_cohort_matches(same_day, new_df):
        print(f"[OK] {as_of}: identical run already captured; preserving backfill")
        return 0

    # A same-day rerun is an authoritative cohort replacement.  Never union
    # candidates across run identities (A/B then B/C must end as B/C only).
    prior_other_days = existing[existing["as_of"].astype(str) != str(as_of)] if not existing.empty else existing
    combined = pd.concat([prior_other_days, new_df], ignore_index=True)
    _write_tracker(combined)
    print(f"[OK] {as_of}: replaced cohort with run {run_id} ({len(new_df)} rows; tracker rows now {len(combined)})")
    return 0


# ============================================================
# Backfill
# ============================================================

def _today_yyyymmdd() -> str:
    return a_share_market_date()


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
    pending_mask = _pending_backfill_mask(df, windows)
    if not pending_mask.any():
        return []
    pending_as_of = df.loc[pending_mask, "as_of"].astype(str).unique().tolist()
    out = []
    for as_of in sorted(pending_as_of):
        as_of_dt = pd.to_datetime(str(as_of), format="%Y%m%d")
        gap_days = (today_dt - as_of_dt).days
        if gap_days >= threshold_calendar_days:
            out.append(str(as_of))
    return out


def _pending_backfill_mask(df: pd.DataFrame, windows: list[int]) -> pd.Series:
    pending_mask = pd.Series(False, index=df.index)
    for w in windows:
        status_col = f"ret_{w}d_status"
        if status_col not in df.columns:
            continue
        pending_mask |= ~df[status_col].astype(str).isin(TERMINAL_FORWARD_STATUSES)
    return pending_mask


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
    # Per-cohort coverage. The tracker is a sidebar: it must not trigger a
    # universe-wide Tushare refetch on its own (refresh is the explicit,
    # separate `refresh` subcommand). Here we only READ the shared cache and
    # settle the cohorts it already covers. A single not-yet-matured cohort
    # must not block older, fully matured cohorts from settling -- that
    # all-or-nothing stall left the candidate-effect ledger frozen.
    ready, needs_refresh, immature, cached, block_msg = _partition_asof_coverage(mature_as_ofs, max_window)
    if block_msg is not None:
        print(f"[SKIP] {block_msg}")
        for line in _cache_refresh_hint(block_msg):
            print(line)
        _print_cache_stale_banner(mature_as_ofs, block_msg)
        return 0
    if immature:
        print(f"[INFO] {len(immature)} cohort(s) captured but not yet +{max_window} trading days old; "
              f"will settle in a later week: {immature}")
    if needs_refresh:
        _print_cache_stale_banner(needs_refresh, "shared cache does not reach these matured cohorts")
    if not ready:
        print(f"[OK] no cohort has +{max_window} trading-day cache coverage yet; nothing to settle this run")
        return 0

    # Strictly cache-only: settle from the already-read cache payload; never
    # fetch here. attach_forward_returns expects samples with a trade_date
    # column; rename our as_of -> trade_date in a slim view.
    payload = cached
    work_mask = df["as_of"].astype(str).isin(ready) & _pending_backfill_mask(df, windows)
    work = df[work_mask].copy()
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

    # These columns are all-NA (float64) on a fresh tracker but the write-back
    # below assigns strings/timestamps into them; pandas 2.x rejects a
    # string-into-float64 cell set. Coerce to object first. (This loop was dead
    # code until the coverage gate was fixed to settle per cohort, so the
    # dtype mismatch never surfaced in production.)
    for _col in ("entry_date", "entry_unbuyable_reason", "ret_10d_exit_date", "backfilled_at"):
        df_idx[_col] = df_idx[_col].astype(object)

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
            exit_col = f"ret_{w}d_exit_date"
            if exit_col in df_idx.columns and pd.notna(row.get(exit_col)):
                df_idx.at[key, exit_col] = str(row.get(exit_col))
            for benchmark in BENCHMARKS:
                excess_col = f"ret_{w}d_excess_{benchmark}"
                excess_val = row.get(excess_col)
                if pd.notna(excess_val):
                    df_idx.at[key, excess_col] = excess_val
        df_idx.at[key, "backfilled_at"] = backfilled_at
        updated_keys.append(key)

    df_out = df_idx.reset_index()[SCHEMA_COLUMNS]
    _write_tracker(df_out)
    deferred = len(needs_refresh) + len(immature)
    print(f"[OK] backfilled {len(updated_keys)} rows across {len(ready)} as_of date(s)"
          + (f"; deferred {deferred} cohort(s)" if deferred else ""))
    return 0


def refresh(windows: list[int]) -> int:
    """Explicit, user-triggered forward_daily cache refresh for the live tracker.

    The weekly backfill stays strictly cache-only (a sidebar must not
    self-fetch); this subcommand is the deliberate, narrowest-safe refresh the
    backfill hint points to. It fetches forward daily for exactly the tracker's
    matured-but-pending cohorts and rewrites the shared cache, so the next
    weekly backfill can settle them.
    """
    df = _load_existing_tracker()
    if df.empty:
        print("[OK] tracker is empty, nothing to refresh")
        return 0
    today = _today_yyyymmdd()
    mature_as_ofs = _mature_as_ofs(df, today, windows)
    if not mature_as_ofs:
        print(f"[OK] no matured pending cohort (today={today}); cache refresh not needed")
        return 0
    max_window = max(windows)
    print(f"[REFRESH] fetching forward_daily for {len(mature_as_ofs)} matured cohort(s): {mature_as_ofs}")
    try:
        payload = fetch_forward_daily(mature_as_ofs, max_window, refresh=True)
    except Exception as exc:
        print(f"[FATAL] forward_daily refresh failed: {exc}")
        print("[INFO] the previous cache is left intact (the cache write is atomic); "
              "check TUSHARE_TOKEN / network and rerun.")
        return 2
    meta = payload.get("meta", {}) if isinstance(payload, dict) else {}
    print(f"[OK] forward_daily cache refreshed: {meta.get('start_date')}..{meta.get('end_date')} "
          f"stock_rows={meta.get('stock_rows')} codes={meta.get('stock_codes')}")
    ready, needs_refresh, immature, _cached, block = _partition_asof_coverage(mature_as_ofs, max_window)
    if block:
        print(f"[WARN] post-refresh coverage check: {block}")
    if ready:
        print(f"[OK] {len(ready)} cohort(s) now covered; run the weekly (or `backfill`) to settle: {ready}")
    if immature:
        print(f"[INFO] {len(immature)} cohort(s) not yet +{max_window} trading days old; settle later: {immature}")
    if needs_refresh:
        print(f"[WARN] {len(needs_refresh)} cohort(s) still not in cache after refresh (unexpected): {needs_refresh}")
    return 0


def _cache_refresh_hint(message: str) -> list[str]:
    if "benchmark input is not same-anchor ready" in message or "benchmark frames" in message:
        return [
            "[HINT] Patch benchmark open/close in the shared forward_daily cache before backfilling. Example:",
            "       python runners\\refresh_forward_daily_benchmark_open_tushare.py",
            "       (this fetches only CSI300/CSI1000 index_daily trade_date/open/close)",
        ]
    return [
        "[HINT] Refresh the shared forward_daily cache for the tracker's live cohorts,",
        "       then re-run the weekly (or `backfill`). Example:",
        "       python runners\\forward_tracker.py refresh --windows 5,10,20",
        "       (fetches forward daily only for the tracker's matured pending cohorts)",
    ]


def _load_cache_for_coverage() -> tuple[dict | None, str]:
    """Read the shared forward_daily cache and validate global readiness.

    Global readiness = cache exists, is readable, and every benchmark frame
    carries same-anchor trade_date/open/close. Returns (cached, "ok") on
    success, else (None, reason). Reads the pickle only, never fetches.
    """
    if not FORWARD_DAILY_CACHE.exists():
        return None, f"forward_daily cache not found at {FORWARD_DAILY_CACHE.relative_to(ROOT)}"
    try:
        import pickle
        with FORWARD_DAILY_CACHE.open("rb") as f:
            cached = pickle.load(f)
    except Exception as e:
        return None, f"forward_daily cache unreadable: {e}"
    benches = cached.get("benchmarks") if isinstance(cached, dict) else None
    if not isinstance(benches, dict):
        return None, "forward_daily cache missing benchmark frames with trade_date/open/close fields"
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
        return None, "forward_daily cache benchmark input is not same-anchor ready (" + "; ".join(problems) + ")"
    return cached, "ok"


def _check_cache_coverage(as_ofs: list[str], max_window: int) -> tuple[bool, str]:
    """Strict predicate: does the shared cache fully cover ALL given as_ofs?

    Returns (ok, message). Reads the pickle cache only, no fetch. backfill no
    longer gates on this (it settles the covered subset via
    _partition_asof_coverage); kept for callers/tests that need the
    all-covered answer.
    """
    cached, msg = _load_cache_for_coverage()
    if cached is None:
        return False, msg

    requested_asofs = sorted({str(as_of) for as_of in as_ofs if str(as_of).strip()})
    if not requested_asofs:
        return False, "forward_daily cache coverage check has no as_of dates"

    trade_dates = _cached_stock_trade_dates(cached)
    if not trade_dates:
        return False, "forward_daily cache missing stock trade_date coverage"

    date_pos = {date: pos for pos, date in enumerate(trade_dates)}
    missing_asofs = [as_of for as_of in requested_asofs if as_of not in date_pos]
    if missing_asofs:
        return False, (
            f"forward_daily cache missing as_of trading dates: {', '.join(missing_asofs)} "
            f"(cache stock trade_date range {trade_dates[0]}..{trade_dates[-1]})"
        )

    insufficient = []
    for as_of in requested_asofs:
        required_idx = date_pos[as_of] + max_window
        if required_idx >= len(trade_dates):
            insufficient.append(
                f"{as_of} needs +{max_window} trading days but cache ends at {trade_dates[-1]}"
            )
    if insufficient:
        meta = cached.get("meta", {})
        cache_start = str(meta.get("start_date", ""))
        cache_end = str(meta.get("end_date", ""))
        return False, (
            "forward_daily cache trading-date coverage insufficient ("
            + "; ".join(insufficient)
            + f"; meta range {cache_start}..{cache_end})"
        )
    return True, "ok"


def _cached_stock_trade_dates(cached: dict) -> list[str]:
    stocks = cached.get("stocks")
    if not isinstance(stocks, pd.DataFrame) or stocks.empty or "trade_date" not in stocks.columns:
        return []
    dates = stocks["trade_date"].dropna().astype(str)
    dates = dates[dates.str.fullmatch(r"\d{8}")]
    return sorted(dates.unique().tolist())


def _partition_asof_coverage(as_ofs: list[str], max_window: int):
    """Split matured pending as_ofs by shared-cache coverage (reads cache only).

    Returns (ready, needs_refresh, immature, cached, block_msg):
      ready         -> present with +max_window trading-day room; settle now.
      needs_refresh -> not in the cache at all (cache is stale for it); a refresh
                       would add it, so the caller nudges the operator.
      immature      -> present but +max_window trading days are not yet in the
                       cache; the cohort simply has not matured, settle later.
      cached        -> loaded cache payload (usable directly as an
                       attach_forward_returns payload) when block_msg is None.
      block_msg     -> non-None when a global problem (missing/unreadable cache,
                       benchmark not same-anchor) blocks every cohort.

    Rationale: backfill must never let one not-yet-matured cohort block older,
    fully matured cohorts from settling. The old all-or-nothing gate did exactly
    that, freezing the candidate-effect ledger.
    """
    cached, msg = _load_cache_for_coverage()
    if cached is None:
        return [], [], [], None, msg
    trade_dates = _cached_stock_trade_dates(cached)
    if not trade_dates:
        return [], [], [], None, "forward_daily cache missing stock trade_date coverage"
    date_pos = {date: pos for pos, date in enumerate(trade_dates)}
    ready, needs_refresh, immature = [], [], []
    for as_of in sorted({str(a) for a in as_ofs if str(a).strip()}):
        if as_of not in date_pos:
            needs_refresh.append(as_of)
        elif date_pos[as_of] + max_window >= len(trade_dates):
            immature.append(as_of)
        else:
            ready.append(as_of)
    return ready, needs_refresh, immature, cached, None


def _print_cache_stale_banner(cohorts: list[str], reason: str) -> None:
    """Loud, unmissable staleness banner so the operator refreshes the shared
    forward_daily cache. The plain [SKIP] line stayed buried in the weekly log
    for ~5 months; this box is meant to survive a long console scroll."""
    bar = "!" * 74
    shown = ", ".join(cohorts[:12]) + (" ..." if len(cohorts) > 12 else "")
    print("")
    print(bar)
    print("!!  FORWARD-TRACKER CACHE STALE -- candidate-effect ledger is NOT advancing.")
    print(f"!!  {len(cohorts)} matured cohort(s) cannot settle ({reason}).")
    print(f"!!  cohorts: {shown}")
    print("!!  ACTION: refresh the shared forward_daily cache, then re-run the weekly:")
    print("!!      python runners\\forward_tracker.py refresh --windows 5,10,20")
    print(bar)
    print("")


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
    parser = argparse.ArgumentParser(description="Phase 3.5 live forward tracker (capture + backfill + refresh).")
    sub = parser.add_subparsers(dest="cmd", required=True)
    cap = sub.add_parser("capture", help="Append one row per candidate from result/a_short/<as_of>/analysis_input.json.")
    cap.add_argument("--as-of", required=True, help="YYYYMMDD trading day.")
    bf = sub.add_parser("backfill", help="Fill forward returns for matured pending rows (cache-only).")
    bf.add_argument("--windows", default="5,10,20")
    rf = sub.add_parser("refresh", help="Explicit narrowest-safe forward_daily cache refresh for matured pending cohorts.")
    rf.add_argument("--windows", default="5,10,20")
    args = parser.parse_args()

    if args.cmd == "capture":
        return capture(args.as_of)
    if args.cmd == "backfill":
        windows = [int(w) for w in args.windows.split(",") if w.strip()]
        return backfill(windows)
    if args.cmd == "refresh":
        windows = [int(w) for w in args.windows.split(",") if w.strip()]
        return refresh(windows)
    return 1


if __name__ == "__main__":
    sys.exit(main())

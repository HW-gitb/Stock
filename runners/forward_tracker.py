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
from datetime import datetime, timedelta
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
from engine.a_short_run_revision import (
    RevisionError,
    official_analysis_input_path,
    public_revision_root,
    resolve_official_revision,
    validate_run_revision_id,
)

TRACKER_CSV = ROOT / "logs" / "forward_tracker.csv"
LIVE_RESULT_ROOT = ROOT / "result" / "a_short"
SIDECAR_OUTCOME_PREFIX = "[a-short-sidecar-outcome] "

# Columns kept in the tracker. Order matters: read/write round-trips must
# preserve column order so older CSVs stay diff-friendly.
SCHEMA_COLUMNS = [
    "as_of",
    "captured_at",
    "run_id",
    "candidate_digest",
    "run_revision_id",
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
    "run_revision_id": str,
    "price_data_through": str, "industry_trend_source_as_of": str,
    "theme_taxonomy_source_as_of": str, "theme_taxonomy_l3_snapshot_date": str,
    "entry_date": str, "ret_10d_exit_date": str, "ts_code": str,
}

DEFAULT_WINDOWS = [5, 10, 20]
# `backfill` succeeded as a process but the shared cache kept at least one MATURED
# cohort from settling, so the candidate-effect ledger did not advance.  The console
# banner alone disappears with the terminal and the recorded sidecar outcome used to
# read `succeeded`; this distinct code lets the launcher record `stalled` instead of
# claiming progress that did not happen.  Not used for immature cohorts: those have
# simply not aged yet and will settle on their own.
EXIT_LEDGER_STALLED = 3
# Calendar-day pad beyond the trading-day window estimate. Lets the cache
# refresh job land Tushare's close before tracker tries to read it.
MATURE_BUFFER_CALENDAR_DAYS = 3
TERMINAL_FORWARD_STATUSES = {
    "ok",
    "pending_no_entry_limit_up",
    "pending_missing_future_close",
    "pending_return_conversion_failed",
}
# These statuses mean the shared cache did not provide the next real trading
# row.  They are only a stale-cache signal once the corresponding calendar-age
# window is mature; other pending statuses (for example a missing symbol row)
# remain an honest data-quality outcome and are not relabelled here.
STALE_CACHE_PENDING_STATUSES = frozenset({
    "pending_immature_asof",
    "pending_no_t_plus_one",
    "pending_asof_not_in_future_cache",
})
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
                   runtime_configuration_fingerprint: str | None = None,
                   run_revision_id: str | None = None) -> dict:
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
        "run_revision_id": run_revision_id,
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


def _emit_sidecar_outcome(*, as_of: str, run_revision_id: str | None,
                          progress_status: str) -> None:
    print(SIDECAR_OUTCOME_PREFIX + json.dumps({
        "name": "forward_tracker_capture",
        "as_of": str(as_of),
        "run_revision_id": run_revision_id,
        "execution_status": "succeeded",
        "progress_status": progress_status,
    }, sort_keys=True, separators=(",", ":")))


def capture(as_of: str, run_revision_id: str | None = None) -> int:
    if run_revision_id is not None:
        try:
            run_revision_id = validate_run_revision_id(run_revision_id)
        except ValueError as exc:
            print(f"[FATAL] invalid run_revision_id: {exc}")
            return 2
        input_path = public_revision_root(ROOT, as_of, run_revision_id) / "analysis_input.json"
    else:
        input_path = official_analysis_input_path(ROOT, as_of)
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
    identity_revision = identity.get("run_revision_id")
    if identity_revision not in (None, ""):
        try:
            identity_revision = validate_run_revision_id(str(identity_revision))
        except ValueError as exc:
            print(f"[FATAL] analysis_input has invalid run_revision_id: {exc}")
            return 2
    if run_revision_id is not None and identity_revision != run_revision_id:
        print("[FATAL] requested run_revision_id does not match analysis_input identity")
        return 2
    run_revision_id = run_revision_id or identity_revision
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
        run_revision_id=run_revision_id,
    )
                for c in candidates]
    new_df = pd.DataFrame(new_rows, columns=SCHEMA_COLUMNS)

    existing = _load_existing_tracker()
    if not existing.empty:
        same_day = existing[existing["as_of"].astype(str) == str(as_of)]
        same_day = same_day[same_day["run_revision_id"].fillna("").astype(str) == str(run_revision_id or "")]
    else:
        same_day = existing
    expected_codes = sorted(str(row["ts_code"]) for row in new_rows)
    captured_codes = sorted(same_day["ts_code"].dropna().astype(str).tolist()) if not same_day.empty else []
    if not same_day.empty and set(same_day["run_id"].dropna().astype(str)) == {run_id} and \
            set(same_day["candidate_digest"].dropna().astype(str)) == {digest} and \
            captured_codes == expected_codes and _decision_cohort_matches(same_day, new_df):
        print(f"[OK] {as_of}: identical run already captured; preserving backfill")
        _emit_sidecar_outcome(as_of=as_of, run_revision_id=run_revision_id,
                              progress_status="already_current")
        return 0

    # Legacy date-only captures retain their historical replacement behavior.  A
    # V5 revision is a separate immutable cohort: a new revision is appended and
    # never deletes the earlier same-day cohort.
    if run_revision_id is None:
        prior_other_days = existing[existing["as_of"].astype(str) != str(as_of)] if not existing.empty else existing
    else:
        prior_other_days = existing
    combined = pd.concat([prior_other_days, new_df], ignore_index=True)
    _write_tracker(combined)
    action = "appended revision cohort" if run_revision_id is not None else "replaced cohort"
    print(f"[OK] {as_of}: {action} with run {run_id} ({len(new_df)} rows; tracker rows now {len(combined)})")
    _emit_sidecar_outcome(as_of=as_of, run_revision_id=run_revision_id,
                          progress_status="advanced")
    return 0


# ============================================================
# Backfill
# ============================================================

def _today_yyyymmdd() -> str:
    return a_share_market_date()


def _calendar_age_mature(as_of: str, today: str, window: int) -> bool:
    """Return whether ``window`` calendar age has elapsed for an as_of.

    This is deliberately the same existing approximation used by the tracker
    (trading days * 1.4 plus the close-publication buffer).  It is only a
    stale-cache classification guard; actual settlement still requires real
    stock rows from the shared cache.
    """
    as_of_dt = pd.to_datetime(str(as_of), format="%Y%m%d")
    today_dt = pd.to_datetime(str(today), format="%Y%m%d")
    threshold_calendar_days = int(window * 1.4) + MATURE_BUFFER_CALENDAR_DAYS
    return (today_dt - as_of_dt).days >= threshold_calendar_days


def _mature_as_ofs(df: pd.DataFrame, today: str, windows: list[int]) -> list[str]:
    """Pick distinct as_of values where at least one pending window is mature.

    A cohort is selected when at least one of its pending windows has reached
    the calendar-age threshold, so a 5d row can be backfilled even if its
    10d/20d siblings are still pending. Each window is then classified again
    after attach_forward_returns against the same threshold.

    Calendar-day approximation: 1 trading day ~ 1.4 calendar days; the
    +MATURE_BUFFER_CALENDAR_DAYS pad accounts for weekends/holidays.
    """
    pending_mask = _pending_backfill_mask(df, windows)
    if not pending_mask.any():
        return []
    pending_as_of = df.loc[pending_mask, "as_of"].astype(str).unique().tolist()
    out = []
    for as_of in sorted(pending_as_of):
        cohort = df.loc[df["as_of"].astype(str) == str(as_of)]
        if any(
            f"ret_{window}d_status" in cohort.columns
            and (~cohort[f"ret_{window}d_status"].astype(str).isin(TERMINAL_FORWARD_STATUSES)).any()
            and _calendar_age_mature(as_of, today, window)
            for window in windows
        ):
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


def _filter_official_revision(
    frame: pd.DataFrame,
    project_root: str | Path,
    requested_revision: str,
) -> pd.DataFrame:
    """Keep only the resolver-selected cohort for each decision date.

    The tracker remains an append-only audit ledger.  Non-official and
    validation-only rows are left untouched in the CSV but are excluded from
    formal backfill counting when an official root is supplied.
    """
    if frame.empty:
        return frame.copy()
    selected_revisions: dict[str, str] = {}
    for as_of in sorted(frame["as_of"].astype(str).unique()):
        try:
            selected = resolve_official_revision(
                project_root, as_of,
                require=True,
            )
        except RevisionError:
            continue
        if selected is not None:
            selected_revisions[as_of] = selected["selected_revision_id"]
    if not selected_revisions:
        return frame.iloc[0:0].copy()
    # ``requested_revision`` identifies the current invocation only.  Historical
    # cohorts must use the resolver-selected revision for their own decision date;
    # filtering everything to the current id makes every mature cohort disappear.
    selected = frame["as_of"].astype(str).map(selected_revisions)
    return frame[
        selected.notna()
        & frame["run_revision_id"].fillna("").astype(str).eq(selected.astype(str))
    ].copy()


def backfill(
    windows: list[int],
    run_revision_id: str | None = None,
    official_project_root: str | Path | None = None,
) -> int:
    if run_revision_id is not None:
        try:
            run_revision_id = validate_run_revision_id(run_revision_id)
        except ValueError as exc:
            print(f"[FATAL] invalid run_revision_id: {exc}")
            return 2
    if official_project_root is not None and run_revision_id is None:
        print("[FATAL] official backfill requires run_revision_id")
        return 2
    all_df = _load_existing_tracker()
    df = all_df.copy()
    if run_revision_id is not None and official_project_root is not None and not df.empty:
        df = _filter_official_revision(df, official_project_root, run_revision_id)
    elif run_revision_id is not None and not df.empty:
        # Cache settlement is scoped to the requested official cohort.  Other
        # same-day revisions remain audit history and are not mutated here.
        df = df[df["run_revision_id"].fillna("").astype(str) == run_revision_id].copy()
    if df.empty:
        if official_project_root is not None and not all_df.empty:
            revision_series = all_df.get("run_revision_id")
            legacy_rows = int(
                revision_series.fillna("").astype(str).eq("").sum()
                if revision_series is not None else len(all_df)
            )
            print(
                "[OK] no official tracker rows; "
                f"excluded {legacy_rows} legacy audit row(s), formal backfill count=0"
            )
            return 0
        print("[OK] tracker is empty, nothing to backfill")
        return 0

    today = _today_yyyymmdd()
    mature_as_ofs = _mature_as_ofs(df, today, windows)
    if not mature_as_ofs:
        print(f"[OK] no calendar-age eligible as_of with pending rows (today={today})")
        return 0
    print(f"[INFO] calendar-age eligible as_of with pending rows: {mature_as_ofs}")

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
        return EXIT_LEDGER_STALLED
    if not ready:
        print("[INFO] no calendar-age eligible cohort has an as_of row in the shared cache; "
              "nothing to settle this run")
        if needs_refresh:
            _print_cache_stale_banner(
                needs_refresh,
                "matured as_of is absent from stock rows; " + _cache_coverage_description(cached),
            )
        return EXIT_LEDGER_STALLED if needs_refresh else 0

    # Strictly cache-only: settle from the already-read cache payload; never
    # fetch here. attach_forward_returns expects samples with a trade_date
    # column; rename our as_of -> trade_date in a slim view.
    payload = cached
    settled_date = _latest_settled_market_date(df, today)
    cache_is_behind_market_date = _cache_is_behind_market_date(payload, settled_date)
    work_mask = df["as_of"].astype(str).isin(ready) & _pending_backfill_mask(df, windows)
    work = df[work_mask].copy()
    if work.empty:
        return EXIT_LEDGER_STALLED if needs_refresh else 0
    pending_before_attach = {
        (str(row.as_of), str(getattr(row, "run_revision_id", "") or ""), str(row.ts_code), window): str(getattr(row, f"ret_{window}d_status"))
        for row in work.itertuples(index=False)
        for window in windows
    }
    work["trade_date"] = work["as_of"].astype(str)
    # name, board not in tracker schema; attach_forward_returns reads them
    # only for limit-up sourcing. board can be derived from ts_code.
    work["board"] = work["ts_code"].apply(_board_from_code)
    work["close"] = work["base_close"]  # fallback used inside attach_forward_returns
    work = attach_forward_returns(work, windows, payload)

    stale_windows = []
    for (as_of, revision), cohort in work.groupby(
            [work["as_of"].astype(str), work["run_revision_id"].fillna("").astype(str)],
            sort=True, dropna=False):
        for window in windows:
            status_column = f"ret_{window}d_status"
            if status_column not in cohort.columns:
                continue
            if not _calendar_age_mature(as_of, today, window):
                continue
            # A long holiday can satisfy the calendar approximation before N
            # exchange sessions have elapsed.  Do not call that stale when
            # the actual stock cache already reaches the latest settled session.
            if not cache_is_behind_market_date:
                continue
            if any(
                pending_before_attach.get((str(row.as_of), str(getattr(row, "run_revision_id", "") or ""),
                                           str(row.ts_code), window))
                not in TERMINAL_FORWARD_STATUSES
                and str(getattr(row, status_column)) in STALE_CACHE_PENDING_STATUSES
                for row in cohort.itertuples(index=False)
            ):
                stale_windows.append(f"{as_of}/{revision or 'legacy_revision_0'}:+{window}d")

    # Write the resulting returns back into df by (as_of, ts_code).
    work_idx = work.set_index(["as_of", "run_revision_id", "ts_code"])
    df_idx = df.set_index(["as_of", "run_revision_id", "ts_code"])

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
            if str(cur_status[w]) not in TERMINAL_FORWARD_STATUSES and pd.notna(new_status):
                df_idx.at[key, f"ret_{w}d_status"] = new_status
            if str(cur_status[w]) not in TERMINAL_FORWARD_STATUSES and pd.notna(new_val):
                df_idx.at[key, f"ret_{w}d_t1_net"] = new_val
            exit_col = f"ret_{w}d_exit_date"
            if (str(cur_status[w]) not in TERMINAL_FORWARD_STATUSES
                    and exit_col in df_idx.columns and pd.notna(row.get(exit_col))):
                df_idx.at[key, exit_col] = str(row.get(exit_col))
            for benchmark in BENCHMARKS:
                excess_col = f"ret_{w}d_excess_{benchmark}"
                excess_val = row.get(excess_col)
                if pd.notna(excess_val):
                    df_idx.at[key, excess_col] = excess_val
        df_idx.at[key, "backfilled_at"] = backfilled_at
        updated_keys.append(key)

    selected_out = df_idx.reset_index()[SCHEMA_COLUMNS]
    if run_revision_id is not None:
        other = all_df[all_df["run_revision_id"].fillna("").astype(str) != run_revision_id]
        df_out = pd.concat([other, selected_out], ignore_index=True)[SCHEMA_COLUMNS]
    else:
        df_out = selected_out
    _write_tracker(df_out)
    stale_cohorts = sorted(set(needs_refresh + [item.split(":", 1)[0] for item in stale_windows]))
    if stale_cohorts:
        details = []
        if needs_refresh:
            details.append("missing as_of=" + ",".join(needs_refresh))
        if stale_windows:
            details.append("matured pending windows=" + ",".join(stale_windows))
        _print_cache_stale_banner(stale_cohorts, "; ".join(details + [_cache_coverage_description(cached)]))
    deferred = len(stale_cohorts)
    print(f"[OK] backfilled {len(updated_keys)} rows across {len(ready)} as_of date(s)"
          + (f"; deferred {deferred} cohort(s)" if deferred else ""))
    # Some cohorts settled, but a matured one still could not: the ledger is only
    # partly advanced, so report stalled rather than a clean success.
    return EXIT_LEDGER_STALLED if stale_cohorts else 0


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
    print(f"[OK] forward_daily cache refreshed: {_cache_coverage_description(payload)} "
          f"stock_rows={meta.get('stock_rows')} codes={meta.get('stock_codes')}")
    ready, needs_refresh, immature, _cached, block = _partition_asof_coverage(mature_as_ofs, max_window)
    if block:
        print(f"[WARN] post-refresh coverage check: {block}")
    if ready:
        print(f"[OK] {len(ready)} cohort(s) now present in cache; run the weekly (or `backfill`) to settle: {ready}")
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
            f"({_cache_coverage_description(cached)})"
        )

    insufficient = []
    for as_of in requested_asofs:
        required_idx = date_pos[as_of] + max_window
        if required_idx >= len(trade_dates):
            insufficient.append(
                f"{as_of} needs +{max_window} trading days but cache ends at {trade_dates[-1]}"
            )
    if insufficient:
        return False, (
            "forward_daily cache trading-date coverage insufficient ("
            + "; ".join(insufficient)
            + f"; {_cache_coverage_description(cached)})"
        )
    return True, "ok"


def _cached_stock_trade_dates(cached: dict) -> list[str]:
    stocks = cached.get("stocks")
    if not isinstance(stocks, pd.DataFrame) or stocks.empty or "trade_date" not in stocks.columns:
        return []
    dates = stocks["trade_date"].dropna().astype(str)
    dates = dates[dates.str.fullmatch(r"\d{8}")]
    return sorted(dates.unique().tolist())


def _latest_settled_market_date(df: pd.DataFrame, today: str) -> str | None:
    """Resolve the latest settled session without a provider call.

    A current capture already records the accepted prior-settled price clock;
    use that source-bound date when its run is for this wall date.  Offline or
    legacy tracker rows fall back to the latest weekday on or before ``today``
    so a weekend run is compared with Friday rather than the Sunday wall date.
    """
    today_text = str(today)
    if len(today_text) != 8 or not today_text.isdigit():
        return None
    try:
        today_dt = datetime.strptime(today_text, "%Y%m%d")
    except ValueError:
        return None

    if isinstance(df, pd.DataFrame) and not df.empty and {
        "run_date", "price_data_through"
    }.issubset(df.columns):
        run_dates = df["run_date"].astype(str)
        eligible = df[
            run_dates.str.fullmatch(r"\d{8}")
            & (run_dates <= today_text)
        ]
        settled = [
            str(value)
            for value in eligible["price_data_through"].dropna().astype(str)
            if len(str(value)) == 8 and str(value).isdigit() and str(value) <= today_text
        ]
        if settled:
            return max(settled)

    while today_dt.weekday() >= 5:
        today_dt -= timedelta(days=1)
    return today_dt.strftime("%Y%m%d")


def _cache_is_behind_market_date(cached: dict, settled_date: str | None) -> bool:
    """Return whether actual stock rows lag the latest settled session.

    The caller supplies a settled-date hint rather than a Shanghai wall date.
    Missing/malformed hints or cache coverage remain fail-closed and are
    treated as lagging.
    """
    if not isinstance(cached, dict):
        return True
    settled_text = str(settled_date or "")
    if len(settled_text) != 8 or not settled_text.isdigit():
        return True
    trade_dates = _cached_stock_trade_dates(cached)
    return not trade_dates or trade_dates[-1] < settled_text


def _cache_coverage_description(cached: dict) -> str:
    """Describe actual stock coverage separately from the metadata request range."""
    trade_dates = _cached_stock_trade_dates(cached)
    if trade_dates:
        stock_range = f"stock trade_date range {trade_dates[0]}..{trade_dates[-1]}"
    else:
        stock_range = "stock trade_date range unavailable"
    meta = cached.get("meta") if isinstance(cached, dict) else {}
    meta = meta if isinstance(meta, dict) else {}
    meta_start = str(meta.get("start_date") or "unknown")
    meta_end = str(meta.get("end_date") or "unknown")
    return f"{stock_range}; meta request range {meta_start}..{meta_end}"


def _partition_asof_coverage(as_ofs: list[str], max_window: int):
    """Split matured pending as_ofs by shared-cache coverage (reads cache only).

    Returns (ready, needs_refresh, immature, cached, block_msg):
      ready         -> as_of exists in stock rows; settle each pending window now.
      needs_refresh -> not in the cache at all (cache is stale for it); a refresh
                       would add it, so the caller nudges the operator.
      immature      -> retained as an empty compatibility slot; per-window
                       maturity is classified after attach_forward_returns.
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
    ready, needs_refresh = [], []
    for as_of in sorted({str(a) for a in as_ofs if str(a).strip()}):
        if as_of not in date_pos:
            needs_refresh.append(as_of)
        else:
            ready.append(as_of)
    return ready, needs_refresh, [], cached, None


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
    cap.add_argument("--run-revision-id", default=None)
    bf = sub.add_parser("backfill", help="Fill forward returns for matured pending rows (cache-only).")
    bf.add_argument("--windows", default="5,10,20")
    bf.add_argument("--run-revision-id", default=None)
    bf.add_argument("--official-project-root", default=None,
                    help="optional project root whose official pointer gates formal backfill")
    rf = sub.add_parser("refresh", help="Explicit narrowest-safe forward_daily cache refresh for matured pending cohorts.")
    rf.add_argument("--windows", default="5,10,20")
    args = parser.parse_args()

    if args.cmd == "capture":
        return capture(args.as_of, run_revision_id=args.run_revision_id)
    if args.cmd == "backfill":
        windows = [int(w) for w in args.windows.split(",") if w.strip()]
        return backfill(
            windows,
            run_revision_id=args.run_revision_id,
            official_project_root=args.official_project_root,
        )
    if args.cmd == "refresh":
        windows = [int(w) for w in args.windows.split(",") if w.strip()]
        return refresh(windows)
    return 1


if __name__ == "__main__":
    sys.exit(main())

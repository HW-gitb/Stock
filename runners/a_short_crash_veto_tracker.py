#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A-short 闪崩否决前瞻追踪（comparison-only）。

每次周跑后冻结当次 ``l2_crash_veto`` 名单，并在后续周跑补算 T+1 开盘买入、
T+5/T+10 收盘卖出的前复权净收益（双边成本 0.16%）。每只被拦股票匹配三只
同行业、规模/动量/流动性相近的已排名股票；追踪结果只进周报，不改 EGS 选股。

``bootstrap`` 专用于 20260714 口径切换：保留旧 4 日官方 245 只，并单独冻结
第 5 日新增、且旧官方运行原本会进入排名的 55 只。两组永不混算。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import pickle
import sys
import tempfile
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.a_short_observability import safe_exception_summary

STATE_PATH = ROOT / "logs" / "a_short_crash_veto_tracker.json"
SUMMARY_PATH = ROOT / "logs" / "a_short_crash_veto_summary.json"
PRICE_CACHE_PATH = ROOT / "logs" / "a_short_crash_veto_prices.pkl"
STATE_SCHEMA_VERSION = "1.0.0"
SUMMARY_SCHEMA_VERSION = "1.0.0"
HORIZONS = (5, 10)
CONTROL_COUNT = 3
ROUND_TRIP_COST_PCT = 0.16
DECISION_MIN_PAIRS = 20
DECISION_EXCESS_PCT = 1.0
DECISION_OUTPERFORM_RATE = 0.60
DECISION_MAE_TOLERANCE_PCT = 1.0
DECISION_LOSS_RATE_GAP = 0.10


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _atomic_pickle(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as handle:
            pickle.dump(payload, handle, protocol=pickle.HIGHEST_PROTOCOL)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _load_state(path: Path = STATE_PATH) -> dict:
    if not path.exists():
        return {"schema_name": "a_short_crash_veto_tracker_state",
                "schema_version": STATE_SCHEMA_VERSION, "cohorts": []}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_name") != "a_short_crash_veto_tracker_state" or \
            payload.get("schema_version") != STATE_SCHEMA_VERSION or not isinstance(payload.get("cohorts"), list):
        raise ValueError(f"invalid crash-veto tracker state: {path}")
    return payload


def _official_inputs(as_of: str) -> tuple[dict, pd.DataFrame, pd.DataFrame]:
    result_dir = ROOT / "result" / "a_short" / as_of
    marker_path = result_dir / "official_publish.json"
    recon_path = result_dir / "rank_universe_reconciliation.csv"
    full_path = ROOT / "A-EGS" / "Result" / f"egs_full_{as_of}.csv"
    if not marker_path.exists() or not recon_path.exists() or not full_path.exists():
        raise FileNotFoundError(f"{as_of} official EGS publish/reconciliation/full-rank artifact missing")
    marker = json.loads(marker_path.read_text(encoding="utf-8"))
    if marker.get("stage_status") != "complete" or str(marker.get("trade_date")) != as_of:
        raise ValueError(f"{as_of} official publish marker is not complete/matching")
    refs = marker.get("files") or {}
    recon_ref = refs.get("rank_universe_reconciliation") or {}
    full_ref = refs.get("full_rank") or {}
    if recon_ref.get("path") != recon_path.name or recon_ref.get("sha256") != _sha256(recon_path):
        raise ValueError("official publish marker does not bind rank_universe_reconciliation.csv")
    if full_ref.get("path") != full_path.name or full_ref.get("sha256") != _sha256(full_path):
        raise ValueError("official publish marker does not bind egs_full CSV")
    recon = pd.read_csv(recon_path, dtype=str)
    full = pd.read_csv(full_path, dtype={"ts_code": str})
    required = {"ts_code", "outcome", "terminal_stage", "reason"}
    if not required.issubset(recon.columns) or recon["ts_code"].duplicated().any():
        raise ValueError("invalid rank-universe reconciliation shape")
    ranked = set(recon.loc[recon["outcome"] == "ranked", "ts_code"].astype(str))
    if ranked != set(full["ts_code"].astype(str)):
        raise ValueError("reconciliation ranked codes do not equal egs_full codes")
    return marker, recon, full


def _find_cache(pattern: str) -> Path:
    matches = sorted((ROOT / "A-EGS" / "Result" / "egs_cache").glob(pattern))
    if not matches:
        raise FileNotFoundError(f"EGS cache missing: {pattern}")
    return matches[-1]


def _load_capture_frames(as_of: str, full: pd.DataFrame,
                         reconciliation: pd.DataFrame | None = None) -> pd.DataFrame:
    # The reconciliation carries the pre-L2 feature surface for veto members;
    # the ranked artifact carries the matching control pool.  Combine both so
    # an uncached runtest does not depend on transient egs_cache pickles.
    required_full_columns = {
        "ts_code", "name", "l1_name", "l2_name", "total_mv", "pct_20d", "avg_amount_20d",
    }
    if required_full_columns.issubset(full.columns):
        fresh_frames = [full[list(required_full_columns)].copy()]
        if reconciliation is not None and required_full_columns.issubset(reconciliation.columns):
            fresh_frames.insert(0, reconciliation[list(required_full_columns)].copy())
        fresh = pd.concat(fresh_frames, ignore_index=True)
        fresh["ts_code"] = fresh["ts_code"].astype(str)
        if not fresh["ts_code"].duplicated().any():
            return fresh.set_index("ts_code", drop=False)
        if reconciliation is not None and required_full_columns.issubset(reconciliation.columns):
            fresh = fresh.drop_duplicates("ts_code", keep="first")
            return fresh.set_index("ts_code", drop=False)

    cache_dir = ROOT / "A-EGS" / "Result" / "egs_cache"
    daily = pd.read_pickle(cache_dir / f"daily_all_{as_of}_60d.pkl")
    stocks = pd.read_pickle(_find_cache(f"stock_list_{as_of}*.pkl"))
    industry = pd.read_pickle(_find_cache(f"sw_industry_map*_{as_of}.pkl"))
    analysis = json.loads((ROOT / "result" / "a_short" / as_of / "analysis_input.json").read_text(encoding="utf-8"))
    source_date = str(((analysis.get("candidates") or [{}])[0].get("quote") or {}).get("source_trade_date") or "")
    basic_pattern = f"daily_basic_{source_date}*.pkl" if source_date else f"daily_basic_{as_of}*.pkl"
    basic = pd.read_pickle(_find_cache(basic_pattern))

    rows = []
    daily = daily.sort_values(["ts_code", "trade_date"], ascending=[True, False])
    for code, grp in daily.groupby("ts_code", sort=False):
        closes = pd.to_numeric(grp["close"], errors="coerce").dropna()
        pct20 = ((float(closes.iloc[0]) / float(closes.iloc[min(19, len(closes) - 1)]) - 1) * 100
                 if len(closes) >= 2 else np.nan)
        rows.append({"ts_code": str(code), "pct_20d": pct20,
                     "avg_amount_20d": pd.to_numeric(grp.head(20)["amount"], errors="coerce").mean() * 1000})
    stats = pd.DataFrame(rows)
    names = stocks[["ts_code", "name"]].copy()
    inds = pd.DataFrame([{"ts_code": str(code), **(value or {})} for code, value in industry.items()])
    base = names.merge(basic[["ts_code", "total_mv"]], on="ts_code", how="left")
    base = base.merge(inds[["ts_code", "l1_name", "l2_name"]], on="ts_code", how="left")
    base = base.merge(stats, on="ts_code", how="left")
    full_features = full[[c for c in ("ts_code", "name", "l1_name", "l2_name", "total_mv",
                                      "pct_20d", "avg_amount_20d") if c in full.columns]].copy()
    if reconciliation is not None:
        recon_features = reconciliation[[c for c in ("ts_code", "name", "l1_name", "l2_name", "total_mv",
                                                      "pct_20d", "avg_amount_20d") if c in reconciliation.columns]].copy()
        full_features = pd.concat([recon_features, full_features], ignore_index=True)
    combined = pd.concat([full_features, base], ignore_index=True)
    combined["ts_code"] = combined["ts_code"].astype(str)
    return combined.drop_duplicates("ts_code", keep="first").set_index("ts_code", drop=False)


def detect_crash_codes(daily: pd.DataFrame, codes: set[str], confirmed_days: int) -> set[str]:
    """Mirror egs_main's price-structure veto for an explicit confirmed-day window."""
    hits: set[str] = set()
    work = daily[daily["ts_code"].astype(str).isin(codes)].copy()
    for code, grp in work.groupby("ts_code"):
        grp = grp.sort_values("trade_date", ascending=False).reset_index(drop=True)
        for i in range(1, min(confirmed_days + 1, len(grp))):
            row = grp.iloc[i]
            day_chg = row.get("pct_chg", np.nan)
            if pd.isna(day_chg) or float(day_chg) >= -5:
                continue
            high, low, close = row.get("high", 0), row.get("low", 0), row.get("close", 0)
            if pd.isna(high) or pd.isna(low) or pd.isna(close) or high <= low:
                continue
            if (close - low) / (high - low) <= 0.2:
                recover = (row.get("pre_close", 1) + close) / 2.0
                if grp.iloc[i - 1].get("close", 0) < recover:
                    hits.add(str(code))
                    break
    return hits


def _has_real_industry_value(value) -> bool:
    if value is None or pd.isna(value):
        return False
    return str(value).strip().lower() not in {"", "未知", "nan", "none", "null", "na"}


def _normalize_industry_value(value):
    if not _has_real_industry_value(value):
        return pd.NA
    return str(value).strip()


def match_controls(member_codes: list[str], control_codes: list[str], features: pd.DataFrame,
                   count: int = CONTROL_COUNT) -> dict[str, list[str]]:
    """Deterministic nearest controls: L2 first, then L1, then the full ranked pool."""
    frame = features.copy()
    for col in ("l1_name", "l2_name"):
        if col not in frame.columns:
            frame[col] = pd.NA
        else:
            frame[col] = frame[col].map(_normalize_industry_value)
    for col in ("total_mv", "pct_20d", "avg_amount_20d"):
        frame[col] = pd.to_numeric(frame.get(col), errors="coerce")
    transformed = pd.DataFrame(index=frame.index)
    transformed["size"] = np.log1p(frame["total_mv"].clip(lower=0))
    transformed["momentum"] = frame["pct_20d"]
    transformed["liquidity"] = np.log1p(frame["avg_amount_20d"].clip(lower=0))
    for col in transformed.columns:
        median = transformed[col].median()
        transformed[col] = transformed[col].fillna(0.0 if pd.isna(median) else median)
        scale = transformed[col].std(ddof=0)
        transformed[col] = (transformed[col] - transformed[col].mean()) / (scale if scale and not pd.isna(scale) else 1.0)

    controls = [c for c in sorted(set(control_codes)) if c in frame.index and c not in set(member_codes)]
    result: dict[str, list[str]] = {}
    for code in sorted(set(member_codes)):
        if code not in frame.index:
            result[code] = controls[:count]
            continue
        l2, l1 = frame.at[code, "l2_name"], frame.at[code, "l1_name"]
        l2_pool = [
            c for c in controls
            if _has_real_industry_value(l2)
            and _has_real_industry_value(frame.at[c, "l2_name"])
            and frame.at[c, "l2_name"] == l2
        ]
        l1_pool = [
            c for c in controls
            if _has_real_industry_value(l1)
            and _has_real_industry_value(frame.at[c, "l1_name"])
            and frame.at[c, "l1_name"] == l1
        ]
        valid_controls = [
            c for c in controls
            if _has_real_industry_value(frame.at[c, "l1_name"])
            or _has_real_industry_value(frame.at[c, "l2_name"])
        ]
        pool = l2_pool if len(l2_pool) >= count else (
            l1_pool if len(l1_pool) >= count else (
                valid_controls if len(valid_controls) >= count else controls
            )
        )
        target = transformed.loc[code].to_numpy(dtype=float)
        ranked = sorted(((float(np.linalg.norm(transformed.loc[c].to_numpy(dtype=float) - target)), c)
                         for c in pool), key=lambda item: (item[0], item[1]))
        result[code] = [c for _, c in ranked[:count]]
    return result


def _cohort_id(as_of: str, run_id: str, scope: str, days: int) -> str:
    raw = f"{as_of}|{run_id}|{scope}|{days}".encode("utf-8")
    return "crash-veto-" + hashlib.sha256(raw).hexdigest()[:20]


def _make_cohort(as_of: str, marker: dict, scope: str, days: int, member_codes: list[str],
                 control_codes: list[str], features: pd.DataFrame, source: str,
                 locked: bool = False, notes: dict | None = None) -> dict:
    matches = match_controls(member_codes, control_codes, features)
    members = []
    for code in sorted(set(member_codes)):
        row = features.loc[code] if code in features.index else {}
        members.append({"ts_code": code, "name": str(row.get("name") or ""),
                        "l1_name": str(row.get("l1_name") or ""), "l2_name": str(row.get("l2_name") or ""),
                        "controls": matches.get(code, [])})
    return {
        "cohort_id": _cohort_id(as_of, str(marker["run_id"]), scope, days),
        "as_of": as_of, "run_id": marker["run_id"], "captured_at": _now(),
        "rule_confirmed_days": days, "scope": scope, "source": source, "locked": bool(locked),
        "member_count": len(members), "members": members, "notes": notes or {}, "results": {},
    }


def _upsert_cohort(state: dict, cohort: dict) -> bool:
    for existing in state["cohorts"]:
        if existing["cohort_id"] == cohort["cohort_id"]:
            if existing["member_count"] != cohort["member_count"] or \
                    [m["ts_code"] for m in existing["members"]] != [m["ts_code"] for m in cohort["members"]]:
                raise ValueError(f"cohort identity collision/drift: {cohort['cohort_id']}")
            return False
    state["cohorts"].append(cohort)
    state["cohorts"].sort(key=lambda c: (c["as_of"], c["scope"], c["cohort_id"]))
    return True


def capture_official(state: dict, as_of: str, rule_days: int) -> int:
    marker, recon, full = _official_inputs(as_of)
    members = sorted(recon.loc[recon["reason"] == "l2_crash_veto", "ts_code"].astype(str).unique())
    controls = sorted(recon.loc[recon["outcome"] == "ranked", "ts_code"].astype(str).unique())
    features = _load_capture_frames(as_of, full, recon)
    if not set(members).issubset(features.index):
        missing = sorted(set(members) - set(features.index))
        raise ValueError(f"crash-veto capture feature source missing members: {missing}")
    cohort = _make_cohort(as_of, marker, "official_all_crash_veto", rule_days, members, controls, features,
                          source="official_publish_hashed_reconciliation")
    _upsert_cohort(state, cohort)
    return len(members)


def bootstrap_legacy(state: dict, as_of: str, official_days: int, active_days: int) -> tuple[int, int, int]:
    marker, recon, full = _official_inputs(as_of)
    old_members = sorted(recon.loc[recon["reason"] == "l2_crash_veto", "ts_code"].astype(str).unique())
    ranked = set(recon.loc[recon["outcome"] == "ranked", "ts_code"].astype(str))
    l1_survivors = set(recon.loc[recon["terminal_stage"] != "l1_industry_leader", "ts_code"].astype(str))
    daily = pd.read_pickle(ROOT / "A-EGS" / "Result" / "egs_cache" / f"daily_all_{as_of}_60d.pkl")
    old_shadow = detect_crash_codes(daily, l1_survivors, official_days)
    active_shadow = detect_crash_codes(daily, l1_survivors, active_days)
    if old_shadow != set(old_members):
        raise ValueError(f"legacy replay mismatch: official={len(old_members)} replay={len(old_shadow)}")
    added_all = active_shadow - old_shadow
    added_rank_impact = sorted(added_all & ranked)
    features = _load_capture_frames(as_of, full, recon)
    if not set(old_members).issubset(features.index):
        missing = sorted(set(old_members) - set(features.index))
        raise ValueError(f"legacy crash-veto feature source missing members: {missing}")
    old = _make_cohort(as_of, marker, "legacy_official_4d", official_days, old_members, sorted(ranked), features,
                       source="official_publish_hashed_reconciliation", locked=True,
                       notes={"purpose": "freeze_original_245_without_future_rule_drift"})
    incremental = _make_cohort(
        as_of, marker, "active_5d_incremental_rank_impact", active_days, added_rank_impact,
        sorted(ranked - set(added_rank_impact)), features, source="same_run_daily_cache_shadow_replay", locked=True,
        notes={"active_all_crash_count": len(active_shadow), "incremental_all_count": len(added_all),
               "incremental_already_other_l2_count": len(added_all - ranked),
               "purpose": "measure_only_the_extra_sensitivity_added_by_fifth_confirmed_day"},
    )
    _upsert_cohort(state, old)
    _upsert_cohort(state, incremental)
    return len(old_members), len(added_rank_impact), len(added_all - ranked)


def _load_price_cache(path: Path = PRICE_CACHE_PATH) -> dict:
    if not path.exists():
        return {"trade_dates": [], "stocks": pd.DataFrame(), "coverage": {}}
    with path.open("rb") as handle:
        cache = pickle.load(handle)
    if not isinstance(cache, dict):
        raise ValueError("invalid crash-veto price cache")
    cache.setdefault("trade_dates", [])
    cache.setdefault("stocks", pd.DataFrame())
    cache.setdefault("coverage", {})
    return cache


def _calendar_gap_days(as_of: str) -> int:
    return (datetime.now().date() - datetime.strptime(as_of, "%Y%m%d").date()).days


def latest_settled_trade_date(daily: pd.DataFrame) -> str:
    if daily.empty or "trade_date" not in daily.columns:
        raise ValueError("daily frame has no settled trade dates")
    dates = daily["trade_date"].dropna().astype(str)
    dates = dates[dates.str.fullmatch(r"[0-9]{8}")]
    if dates.empty:
        raise ValueError("daily frame has no canonical settled trade dates")
    return str(dates.max())


def latest_settled_trade_date_from_analysis_input(analysis_path: Path, expected_as_of: str) -> str:
    """Read the settled EOD boundary already published by the current EGS run.

    A canonical Monday pre-open run may legitimately have ``trade_date`` set to
    Monday while every candidate quote is sourced from the preceding settled
    Friday. This published provenance remains available when EGS request
    caching is disabled, unlike the transient daily pickle.
    """
    try:
        payload = json.loads(analysis_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError("official analysis_input unavailable for settled-price boundary") from exc
    if str(payload.get("trade_date") or "") != str(expected_as_of):
        raise RuntimeError("official analysis_input trade_date does not match crash-veto run")
    candidates = payload.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        raise RuntimeError("official analysis_input has no candidate quote provenance")
    source_dates = {
        str((candidate.get("quote") or {}).get("source_trade_date") or "")
        for candidate in candidates if isinstance(candidate, dict)
    }
    if len(source_dates) != 1:
        raise RuntimeError("official analysis_input has inconsistent candidate quote source dates")
    settled = next(iter(source_dates))
    if not settled.isdigit() or len(settled) != 8 or settled > str(expected_as_of):
        raise RuntimeError("official analysis_input has invalid settled quote source date")
    return settled


def refresh_prices_for_mature_cohorts(state: dict, price_path: Path = PRICE_CACHE_PATH,
                                      current_run_as_of: str | None = None,
                                      settled_through: str | None = None) -> dict:
    eligible = [c for c in state["cohorts"] if _calendar_gap_days(c["as_of"]) >= 7]
    cache = _load_price_cache(price_path)
    if not eligible:
        return cache
    from runners.a_short_iv_feed_probe import init_tushare_pro

    token = os.environ.get("TUSHARE_TOKEN")
    if not token:
        raise RuntimeError("TUSHARE_TOKEN missing; crash-veto tracker cannot refresh matured prices")
    pro = init_tushare_pro(token)
    start = min(c["as_of"] for c in eligible)
    # 周跑常发生在周一盘前；trade_cal 会把尚未收盘的今天列为交易日，但其 EOD 价格还不存在。
    # 以本次 EGS daily cache 的 max(trade_date) 作为“最新已结算日”，避免把盘中日误判为到期。
    if not current_run_as_of:
        raise RuntimeError("current_run_as_of required for settled-price boundary")
    if settled_through:
        end = settled_through
    else:
        current_daily_path = ROOT / "A-EGS" / "Result" / "egs_cache" / f"daily_all_{current_run_as_of}_60d.pkl"
        if not current_daily_path.exists():
            raise RuntimeError("current EGS daily cache missing; cannot determine latest settled trade date")
        current_daily = pd.read_pickle(current_daily_path)
        try:
            end = latest_settled_trade_date(current_daily)
        except ValueError as exc:
            raise RuntimeError("current EGS daily cache has no settled trade dates") from exc
    cal = pro.trade_cal(exchange="", start_date=start, end_date=end, is_open=1, fields="cal_date,is_open")
    if cal is None or cal.empty or "cal_date" not in cal.columns:
        raise RuntimeError("Tushare trade_cal returned no open dates for crash-veto tracker")
    trade_dates = sorted(cal["cal_date"].astype(str).unique())
    date_pos = {d: i for i, d in enumerate(trade_dates)}
    needed_by_date: dict[str, set[str]] = {}
    for cohort in eligible:
        if cohort["as_of"] not in date_pos:
            continue
        pos = date_pos[cohort["as_of"]]
        codes = {m["ts_code"] for m in cohort["members"]}
        codes |= {ctrl for m in cohort["members"] for ctrl in m.get("controls", [])}
        mature_h = [h for h in HORIZONS if pos + h < len(trade_dates)]
        if not mature_h:
            continue
        for day in trade_dates[pos + 1: pos + max(mature_h) + 1]:
            needed_by_date.setdefault(day, set()).update(codes)

    frames = [cache["stocks"]] if isinstance(cache.get("stocks"), pd.DataFrame) and not cache["stocks"].empty else []
    coverage = {str(day): set(codes) for day, codes in (cache.get("coverage") or {}).items()}
    for day in sorted(needed_by_date):
        missing = needed_by_date[day] - coverage.get(day, set())
        if not missing:
            continue
        daily = pro.daily(trade_date=day, fields="ts_code,trade_date,open,high,low,close")
        adj = pro.adj_factor(trade_date=day, fields="ts_code,trade_date,adj_factor")
        limits = pro.stk_limit(trade_date=day, fields="ts_code,trade_date,up_limit")
        if daily is None or daily.empty or adj is None or adj.empty:
            raise RuntimeError(f"Tushare daily/adj_factor unavailable for {day}")
        merged = daily.merge(adj, on=["ts_code", "trade_date"], how="left")
        if limits is not None and not limits.empty:
            merged = merged.merge(limits, on=["ts_code", "trade_date"], how="left")
        else:
            merged["up_limit"] = np.nan
        merged["ts_code"] = merged["ts_code"].astype(str)
        frames.append(merged[merged["ts_code"].isin(missing)].copy())
        coverage.setdefault(day, set()).update(missing)
    stocks = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    if not stocks.empty:
        stocks["trade_date"] = stocks["trade_date"].astype(str)
        stocks = stocks.sort_values(["ts_code", "trade_date"]).drop_duplicates(
            ["ts_code", "trade_date"], keep="last").reset_index(drop=True)
    cache = {"trade_dates": trade_dates, "stocks": stocks,
             "coverage": {day: sorted(codes) for day, codes in coverage.items()}, "refreshed_at": _now()}
    _atomic_pickle(price_path, cache)
    return cache


def _asset_outcome(code: str, as_of: str, horizon: int, trade_dates: list[str], lookup: dict) -> dict:
    if as_of not in trade_dates:
        return {"status": "missing_as_of_calendar"}
    pos = trade_dates.index(as_of)
    if pos + horizon >= len(trade_dates):
        return {"status": "pending_immature"}
    entry_date, exit_date = trade_dates[pos + 1], trade_dates[pos + horizon]
    entry, exit_row = lookup.get((code, entry_date)), lookup.get((code, exit_date))
    if entry is None or pd.isna(entry.get("open")) or pd.isna(entry.get("adj_factor")):
        return {"status": "missing_or_suspended_entry", "entry_date": entry_date, "exit_date": exit_date}
    if pd.notna(entry.get("up_limit")) and float(entry["open"]) >= float(entry["up_limit"]) * 0.999:
        return {"status": "unbuyable_limit_up", "entry_date": entry_date, "exit_date": exit_date}
    if exit_row is None or pd.isna(exit_row.get("close")) or pd.isna(exit_row.get("adj_factor")):
        return {"status": "missing_or_suspended_exit", "entry_date": entry_date, "exit_date": exit_date}
    entry_qfq = float(entry["open"]) * float(entry["adj_factor"])
    exit_qfq = float(exit_row["close"]) * float(exit_row["adj_factor"])
    if entry_qfq <= 0 or exit_qfq <= 0:
        return {"status": "invalid_price", "entry_date": entry_date, "exit_date": exit_date}
    ret = (exit_qfq / entry_qfq - 1.0) * 100.0 - ROUND_TRIP_COST_PCT
    lows, highs = [], []
    for day in trade_dates[pos + 1: pos + horizon + 1]:
        row = lookup.get((code, day))
        if row is None or pd.isna(row.get("adj_factor")):
            continue
        if pd.notna(row.get("low")):
            lows.append(float(row["low"]) * float(row["adj_factor"]) / entry_qfq - 1.0)
        if pd.notna(row.get("high")):
            highs.append(float(row["high"]) * float(row["adj_factor"]) / entry_qfq - 1.0)
    return {"status": "ok", "entry_date": entry_date, "exit_date": exit_date,
            "return_pct": ret, "mae_pct": min(lows) * 100 if lows else None,
            "mfe_pct": max(highs) * 100 if highs else None}


def evaluate_cohort(cohort: dict, cache: dict, horizon: int) -> dict:
    trade_dates = sorted(str(d) for d in cache.get("trade_dates", []))
    stocks = cache.get("stocks")
    lookup = {}
    if isinstance(stocks, pd.DataFrame) and not stocks.empty:
        for row in stocks.to_dict("records"):
            lookup[(str(row["ts_code"]), str(row["trade_date"]))] = row
    pairs, statuses = [], {}
    for member in cohort["members"]:
        target = _asset_outcome(member["ts_code"], cohort["as_of"], horizon, trade_dates, lookup)
        statuses[target["status"]] = statuses.get(target["status"], 0) + 1
        controls = [_asset_outcome(c, cohort["as_of"], horizon, trade_dates, lookup)
                    for c in member.get("controls", [])]
        controls = [c for c in controls if c.get("status") == "ok"]
        if target.get("status") != "ok" or not controls:
            continue
        control_ret = float(np.mean([c["return_pct"] for c in controls]))
        control_mae = [c["mae_pct"] for c in controls if c.get("mae_pct") is not None]
        pairs.append({"target_return": target["return_pct"], "control_return": control_ret,
                      "excess": target["return_pct"] - control_ret,
                      "target_mae": target.get("mae_pct"),
                      "control_mae": float(np.mean(control_mae)) if control_mae else None})
    n = len(pairs)
    result = {"status": "ready" if n else "pending", "horizon_trading_days": horizon,
              "member_count": cohort["member_count"], "paired_count": n, "status_counts": statuses}
    if not pairs:
        return result
    target = np.array([p["target_return"] for p in pairs], dtype=float)
    control = np.array([p["control_return"] for p in pairs], dtype=float)
    excess = target - control
    tmae = [p["target_mae"] for p in pairs if p["target_mae"] is not None]
    cmae = [p["control_mae"] for p in pairs if p["control_mae"] is not None]
    result.update({
        "coverage_rate": round(n / cohort["member_count"], 6) if cohort["member_count"] else 0.0,
        "blocked_mean_return_pct": round(float(target.mean()), 6),
        "blocked_median_return_pct": round(float(np.median(target)), 6),
        "control_mean_return_pct": round(float(control.mean()), 6),
        "mean_paired_excess_pct": round(float(excess.mean()), 6),
        "median_paired_excess_pct": round(float(np.median(excess)), 6),
        "outperform_rate": round(float((excess > 0).mean()), 6),
        "blocked_loss_gt_5_rate": round(float((target < -5).mean()), 6),
        "blocked_loss_gt_10_rate": round(float((target < -10).mean()), 6),
        "control_loss_gt_5_rate": round(float((control < -5).mean()), 6),
        "blocked_mean_mae_pct": round(float(np.mean(tmae)), 6) if tmae else None,
        "control_mean_mae_pct": round(float(np.mean(cmae)), 6) if cmae else None,
    })
    return result


def decide_design(five: dict, ten: dict) -> tuple[str, str]:
    if five.get("status") != "ready" or ten.get("status") != "ready" or \
            five.get("paired_count", 0) < DECISION_MIN_PAIRS or ten.get("paired_count", 0) < DECISION_MIN_PAIRS:
        return "insufficient_keep", "证据还没走完或可比样本不足，暂时不改设计，继续按周积累。"
    good = all(m["mean_paired_excess_pct"] >= DECISION_EXCESS_PCT
               and m["outperform_rate"] >= DECISION_OUTPERFORM_RATE
               and (m.get("blocked_mean_mae_pct") is None or m.get("control_mean_mae_pct") is None
                    or m["blocked_mean_mae_pct"] >= m["control_mean_mae_pct"] - DECISION_MAE_TOLERANCE_PCT)
               for m in (five, ten))
    bad = all(m["mean_paired_excess_pct"] <= -DECISION_EXCESS_PCT for m in (five, ten)) or all(
        m["blocked_loss_gt_5_rate"] >= m["control_loss_gt_5_rate"] + DECISION_LOSS_RATE_GAP
        for m in (five, ten))
    if good:
        return "change_candidate", "被拦股票一周和两周都明显跑赢相似未拦股票，且下行风险没有更差：规则有误杀嫌疑。结论：设计需要调整；先复审并做阈值对照，系统不会自动改规则。"
    if bad:
        return "keep", "被拦股票一周和两周整体更差，或大跌比例明显更高：闪崩否决目前有效，设计无需修改。"
    return "mixed_keep", "一周和两周结果不一致或优势不够稳定：暂时不改设计，继续观察后续独立批次。"


def _plain_metric(metric: dict, label: str) -> str:
    if metric.get("status") != "ready":
        counts = metric.get("status_counts") or {}
        pending = counts.get("pending_immature", metric.get("member_count", 0))
        return f"{label}还没走完（待到期 {pending} 只），现在下结论太早。"
    return (f"{label}：{metric['paired_count']}/{metric['member_count']} 只可比较；被拦组平均"
            f"{metric['blocked_mean_return_pct']:+.2f}%，相似未拦组平均{metric['control_mean_return_pct']:+.2f}%，"
            f"被拦组相对{metric['mean_paired_excess_pct']:+.2f}个百分点，"
            f"{metric['outperform_rate'] * 100:.1f}% 跑赢对照。")


def build_summary(state: dict, cache: dict, as_of: str) -> dict:
    variants = []
    for cohort in state["cohorts"]:
        five = evaluate_cohort(cohort, cache, 5)
        ten = evaluate_cohort(cohort, cache, 10)
        cohort["results"] = {"5d": five, "10d": ten}
        decision, conclusion = decide_design(five, ten)
        variants.append({"cohort_id": cohort["cohort_id"], "as_of": cohort["as_of"],
                         "scope": cohort["scope"], "rule_confirmed_days": cohort["rule_confirmed_days"],
                         "member_count": cohort["member_count"], "one_week": five, "two_week": ten,
                         "one_week_plain": _plain_metric(five, "一周"),
                         "two_week_plain": _plain_metric(ten, "两周"),
                         "decision": decision, "conclusion_plain": conclusion})
    scope_order = {"legacy_official_4d": 0, "active_5d_incremental_rank_impact": 1,
                   "official_all_crash_veto": 2}
    variants.sort(key=lambda v: (scope_order.get(v["scope"], 9), v["as_of"], v["cohort_id"]))
    # 用户要看的主样本是旧官方 245 只；新增第 5 日的排名影响组单独作为敏感度复核，绝不混算收益。
    legacy = [v for v in variants if v["scope"] == "legacy_official_4d"]
    incremental = [v for v in variants if v["scope"] == "active_5d_incremental_rank_impact"]
    headline = legacy[-1] if legacy else (variants[-1] if variants else None)
    decision_set = ([legacy[-1]] if legacy else []) + ([incremental[-1]] if incremental else [])
    if not decision_set and headline:
        decision_set = [headline]
    if headline:
        one_plain, two_plain = headline["one_week_plain"], headline["two_week_plain"]
        basis = [v["cohort_id"] for v in decision_set]
        decisions = [v["decision"] for v in decision_set]
        if "insufficient_keep" in decisions:
            final_status = "insufficient_keep"
            final_plain = "旧245只或新增第5日影响组尚未完成一周/两周对比，暂时不改设计，继续按周积累。"
        elif "change_candidate" in decisions:
            final_status = "change_candidate"
            final_plain = "旧245只或新增第5日影响组出现持续跑赢且下行风险未更差，规则有误杀嫌疑。结论：设计需要调整；先复审阈值，系统不会自动改规则。"
        elif decisions and all(d == "keep" for d in decisions):
            final_status = "keep"
            final_plain = "旧245只和新增第5日影响组都没有显示误杀，闪崩否决目前有效，设计无需修改。"
        else:
            final_status = "mixed_keep"
            final_plain = "旧245只与新增第5日影响组的结果不够一致，暂时不改设计，继续观察后续独立批次。"
    else:
        final_status, final_plain = "insufficient_keep", "还没有冻结到闪崩否决批次，暂时不改设计。"
        one_plain = two_plain = "暂无批次。"
        basis = []
    return {"schema_name": "a_short_crash_veto_tracking_summary",
            "schema_version": SUMMARY_SCHEMA_VERSION, "generated_at": _now(), "as_of": as_of,
            "comparison_only": True, "affects_selection": False, "production_rule_changed": False,
            "one_week_plain": one_plain, "two_week_plain": two_plain,
            "final_decision": {"status": final_status, "basis_cohort_ids": basis, "plain_text": final_plain},
            "variants": variants}


def run_update(as_of: str, rule_days: int, state_path: Path, summary_path: Path,
               price_path: Path, fetch_authorized: bool, bootstrap: bool = False,
               official_days: int = 4, active_days: int = 5) -> int:
    state = _load_state(state_path)
    if bootstrap:
        old_n, added_n, other_n = bootstrap_legacy(state, as_of, official_days, active_days)
        print(f"[crash-veto] frozen legacy={old_n}, fifth-day rank-impact={added_n}, already-other-L2={other_n}")
    else:
        n = capture_official(state, as_of, rule_days)
        print(f"[crash-veto] frozen official cohort {as_of}: {n} stocks (confirmed_days={rule_days})")
    # 先冻结名单再联网补行情。即使 provider 本周失败，该批次也不会丢；下周会继续补算。
    state["updated_at"] = _now()
    _atomic_json(state_path, state)
    if fetch_authorized:
        analysis_path = ROOT / "result" / "a_short" / as_of / "analysis_input.json"
        settled_through = latest_settled_trade_date_from_analysis_input(analysis_path, as_of)
        cache = refresh_prices_for_mature_cohorts(
            state, price_path, current_run_as_of=as_of, settled_through=settled_through
        )
    else:
        cache = _load_price_cache(price_path)
    summary = build_summary(state, cache, as_of)
    state["updated_at"] = summary["generated_at"]
    _atomic_json(state_path, state)
    _atomic_json(summary_path, summary)
    print(f"[crash-veto] {summary['one_week_plain']}")
    print(f"[crash-veto] {summary['two_week_plain']}")
    print(f"[crash-veto] 最终结论：{summary['final_decision']['plain_text']}")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="A-short 闪崩否决 5/10 交易日 comparison-only 追踪")
    sub = parser.add_subparsers(dest="cmd", required=True)
    update = sub.add_parser("update", help="冻结本周官方批次并补算已到期结果")
    update.add_argument("--as-of", required=True)
    update.add_argument("--rule-confirmed-days", type=int, default=5)
    update.add_argument("--confirm-fetch-authorized", action="store_true")
    boot = sub.add_parser("bootstrap", help="冻结旧 4 日 245 只及第 5 日新增排名影响组")
    boot.add_argument("--as-of", required=True)
    boot.add_argument("--official-rule-days", type=int, default=4)
    boot.add_argument("--active-rule-days", type=int, default=5)
    boot.add_argument("--confirm-fetch-authorized", action="store_true")
    for p in (update, boot):
        p.add_argument("--state", default=str(STATE_PATH))
        p.add_argument("--summary", default=str(SUMMARY_PATH))
        p.add_argument("--price-cache", default=str(PRICE_CACHE_PATH))
    args = parser.parse_args(argv)
    try:
        if args.cmd == "bootstrap":
            return run_update(args.as_of, args.active_rule_days, Path(args.state), Path(args.summary),
                              Path(args.price_cache), args.confirm_fetch_authorized, bootstrap=True,
                              official_days=args.official_rule_days, active_days=args.active_rule_days)
        return run_update(args.as_of, args.rule_confirmed_days, Path(args.state), Path(args.summary),
                          Path(args.price_cache), args.confirm_fetch_authorized)
    except Exception as exc:
        print("[WARN] crash-veto tracker failed safely "
              f"({safe_exception_summary(exc)}); formal selection unchanged.")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

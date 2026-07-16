"""A-short V14.3 regime comparison runner (slice 2b-impl ②b-2) — standalone, comparison-only.

The I/O + execution layer for the V14.3 regime comparison track. Deliberately a STANDALONE runner,
NOT an egs_main side-output: egs_main is production-frozen-adjacent, and the persisted daily-feature
ledger already amortizes the 252-day cost (one-time bootstrap `执行`, then ~5 new trading days per
weekly run), so a standalone runner stays fully isolated from the production run while still feeding
the comparison track. The panel is written as its own lane artifact (the frozen weekly M6.7 report is
not touched).

Layering:
- PURE / unit-tested core (no Tushare, no real disk required): `iv_series_to_map`,
  `make_feature_provider`, the lane-path + production-path guard, the ledger/records/panel
  persistence, and `run_regime_step` (orchestration with all data frames INJECTED — composes
  `engine.a_short_regime_pipeline.weekly_regime_step` + persistence).
- THIN real-fetch + CLI (`main`): Tushare `stk_limit` / `index_daily` / `daily` / `trade_cal` +
  IV-feed read, gated behind `--confirm-fetch-authorized`; the BOOTSTRAP 252-day backfill is the first
  real-Tushare `执行` in the V14.3 track and needs explicit user authorization + TUSHARE_TOKEN.

Boundary (hard): comparison-only, non-production. Writes ONLY under the guard-safe research lane
(`research/results/a_short/...`), NEVER `result/a_short/<date>`; drives nothing (no Phase 5 / veto /
sizing / overlay / M6.7 action). V14.2 stays the frozen production baseline.
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in os.sys.path:
    os.sys.path.insert(0, str(ROOT))

from engine.a_short_regime_features import compute_regime_daily_features
from engine.a_short_regime_pipeline import weekly_regime_step
from engine.a_short_regime_ledger import (
    build_ledger, validate_ledger, is_canonical_date, BACKFILL_MIN_TRADING_DAYS,
    LEDGER_LANE_ROOT, LEDGER_FILENAME,
)
from engine.a_short_regime_classifier import validate_comparison_record
from engine.a_short_regime_action_comparison import (
    build_action_record, m67_provenance, merge_action_records, refresh_action_records,
    summarize_action_records, validate_action_record,
)
from engine.data.a_share_board_scope import is_a_share_main_board

RECORDS_FILENAME = "regime_comparison_records.json"
PANEL_FILENAME = "regime_comparison_panel.md"
ACTION_RECORDS_FILENAME = "regime_action_comparison_records.json"
ACTION_SUMMARY_FILENAME = "regime_action_comparison_summary.json"
IV_FEED_SCHEMA_PATH = ROOT / "schemas" / "a_short_iv_feed.schema.json"


# ---- pure helpers -----------------------------------------------------------------------------

def _current_run_date() -> str:
    """Single controlled clock for D2 forward-evidence eligibility."""
    return datetime.now().strftime("%Y%m%d")

def validate_iv_feed(iv_feed: dict) -> None:
    """Validate an a_short_iv_feed artifact before consumption: schema + the feed's own consistency
    gate (`validate_feed_summary_consistency` — strictly-ascending/no-dup/no-future trade_date,
    iv_value>0, percentile 0-100). Raises on a wrong-schema / duplicate / future / malformed feed so a
    bad IV artifact can't silently flip the V14.3 IV-defense rule."""
    import jsonschema
    from runners.a_short_iv_feed_build import validate_feed_summary_consistency
    schema = json.loads(Path(IV_FEED_SCHEMA_PATH).read_text(encoding="utf-8"))
    jsonschema.validate(iv_feed, schema)
    validate_feed_summary_consistency(iv_feed)


def iv_series_to_map(iv_feed: dict | None) -> dict:
    """{trade_date: iv_percentile_252d} from a VALIDATED a_short_iv_feed artifact (empty if None)."""
    if not iv_feed:
        return {}
    validate_iv_feed(iv_feed)   # schema + consistency before mapping (no silent dup-overwrite)
    return {str(row.get("trade_date")): row.get("iv_percentile_252d")
            for row in iv_feed.get("series", []) or []}


def main_board_only(df: pd.DataFrame) -> pd.DataFrame:
    """Restrict a stock panel (daily / stk_limit) to A-share MAIN-BOARD ts_codes only.

    The user operates A-shares main-board only; the breadth universe is exactly the governance
    main-board prefixes (SSE 600/601/603/605 + SZSE 000/001/002/003) via the shared INCLUSION-based
    `is_a_share_main_board` — which (unlike the exclusion-based `is_main_board_ts_code`) also rejects
    B-shares (900*.SH / 200*.SZ) and unknown/malformed codes, not just ChiNext/STAR/BSE. Index panels
    (no ts_code) pass through unchanged."""
    if df is None or df.empty or "ts_code" not in df.columns:
        return df
    return df[df["ts_code"].map(is_a_share_main_board)].reset_index(drop=True)


def make_feature_provider(daily: pd.DataFrame, stk_limit: pd.DataFrame,
                          csi300: pd.DataFrame, csi1000: pd.DataFrame, iv_map: dict):
    """Return ``provider(date)`` → one daily-feature row via ``compute_regime_daily_features``.

    The full panels are passed every call; ``compute_regime_daily_features`` itself PIT-filters to
    rows ``<= date`` and fails closed on missing/unusable as_of data, so a bad day raises (the caller
    must re-fetch) rather than silently producing a fabricated row."""
    def provider(date: str) -> dict:
        return compute_regime_daily_features(date, daily, stk_limit, csi300, csi1000,
                                             iv_percentile_252d=iv_map.get(str(date)))
    return provider


def lane_paths(project_root: str | Path | None = None) -> dict:
    base = Path(project_root) if project_root is not None else ROOT
    lane = base / LEDGER_LANE_ROOT
    return {
        "ledger": str(lane / LEDGER_FILENAME),
        "records": str(lane / RECORDS_FILENAME),
        "panel": str(lane / PANEL_FILENAME),
        "action_records": str(lane / ACTION_RECORDS_FILENAME),
        "action_summary": str(lane / ACTION_SUMMARY_FILENAME),
    }


def _reject_production_path(path: str) -> None:
    """Comparison artifacts go under the guard-safe research lane; NEVER production result/a_short."""
    norm = os.path.normpath(os.path.abspath(path)).replace("\\", "/").lower()
    if "/result/a_short/" in norm:
        raise ValueError(f"refusing to write comparison artifact to production path {path} "
                         f"(result/a_short/...); V14.3 comparison track is non-production")


def load_ledger(path: str) -> dict:
    """Load the daily-feature ledger, or an empty pre-bootstrap ledger if the file is absent."""
    if not os.path.exists(path):
        return build_ledger([])
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_comparison_records(path: str) -> list:
    if not os.path.exists(path):
        return []
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _write_json(obj, path: str) -> None:
    _reject_production_path(path)
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    Path(path).write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def save_ledger(ledger: dict, path: str, *, as_of: str, trade_calendar) -> None:
    """Re-validate through the sanctioned gate (defense-in-depth) before writing to the lane."""
    validate_ledger(ledger, as_of=as_of, trade_calendar=trade_calendar)
    _write_json(ledger, path)


def save_comparison_records(records: list, path: str) -> None:
    """Validate each record + reject duplicate as_of before persisting (defense-in-depth: the public
    helper must not write a malformed/duplicated evidence history even if called directly)."""
    seen = set()
    for r in records:
        validate_comparison_record(r)
        a = str(r.get("as_of"))
        if a in seen:
            raise ValueError(f"save_comparison_records: duplicate as_of {a}")
        seen.add(a)
    _write_json(records, path)


def save_action_records(records: list, path: str, *, current_action: dict,
                        regime_records: list[dict]) -> None:
    """Persist append-only D2 evidence, admitting only the runner's current observation.

    Older observations must equal the sanctioned return-backfill refresh of the already persisted
    history. On an empty history this prevents a helper/API caller from seeding arbitrary historical
    rows as forward evidence. The one current row is checked against the runner-owned clock.
    """
    validate_action_record(current_action)
    current_as_of = str(current_action["as_of"])
    origin = current_action["forward_origin"]
    actual_run_date = _current_run_date()
    if origin["run_date"] != actual_run_date:
        raise ValueError("save_action_records: current action run date is not the controlled runner date")
    if abs((datetime.strptime(str(origin["decision_as_of"]), "%Y%m%d") -
            datetime.strptime(current_as_of, "%Y%m%d")).days) > 7:
        raise ValueError("save_action_records: current action decision date is stale versus settled regime date")
    prior = load_comparison_records(path)
    prior_by_date = {}
    for row in prior:
        validate_action_record(row)
        as_of = str(row["as_of"])
        if as_of in prior_by_date:
            raise ValueError(f"save_action_records: existing duplicate as_of {as_of}")
        prior_by_date[as_of] = row
    refreshed_prior = refresh_action_records(prior, regime_records)
    refreshed_by_date = {str(row["as_of"]): row for row in refreshed_prior}
    seen = set()
    for row in records:
        validate_action_record(row)
        as_of = str(row["as_of"])
        if as_of in seen:
            raise ValueError(f"save_action_records: duplicate as_of {as_of}")
        seen.add(as_of)
        if as_of == current_as_of:
            if row != current_action:
                raise ValueError("save_action_records: current action does not match runner observation")
        elif refreshed_by_date.get(as_of) != row:
            raise ValueError("save_action_records: non-current action must match sanctioned history refresh")
    if seen != set(refreshed_by_date) | {current_as_of}:
        raise ValueError("save_action_records: action history cannot drop or add non-current rows")
    _write_json(records, path)


def save_panel(markdown: str, path: str) -> None:
    _reject_production_path(path)
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    Path(path).write_text(markdown, encoding="utf-8")


def run_regime_step(*, as_of: str, trade_calendar, v14_2_regime: str,
                    daily: pd.DataFrame, stk_limit: pd.DataFrame,
                    csi300: pd.DataFrame, csi1000: pd.DataFrame, iv_feed: dict | None,
                    ledger_path: str, records_path: str, panel_path: str,
                    bootstrap: bool = False, feature_provider=None,
                    raw_v14_2_regime: str | None = None, m67_report_path: str | None = None,
                    action_records_path: str | None = None, action_summary_path: str | None = None,
                    action_decision_as_of: str | None = None) -> dict:
    """One comparison run (orchestration; all data frames injected, so unit-testable without Tushare).

    Loads the ledger + comparison-record history, builds the real feature provider, runs the audited
    weekly step, then persists ledger + records + panel under the guard-safe lane.

    Initial ledger creation is **explicit-bootstrap-only**: an absent/empty ledger with
    ``bootstrap=False`` raises (a weekly run must not silently create a ledger), and a bootstrap that
    yields fewer than ``BACKFILL_MIN_TRADING_DAYS`` rows raises (do not start the evidence clock from an
    insufficient window). Returns the step output."""
    action_requested = any(v is not None for v in
                           (raw_v14_2_regime, m67_report_path, action_records_path, action_summary_path,
                            action_decision_as_of))
    if action_requested and not all(v is not None for v in
                                    (raw_v14_2_regime, m67_report_path, action_records_path, action_summary_path,
                                     action_decision_as_of)):
        raise ValueError("D2 action comparison requires raw V14.2 regime, M6.7 source, paths and decision date")
    if action_requested:
        decision_as_of = str(action_decision_as_of)
        if not is_canonical_date(decision_as_of) or not is_canonical_date(str(as_of)):
            raise ValueError("D2 action comparison requires real decision and settled regime dates")
        # The decision may use Friday's settled regime during a Monday run, but a historical
        # replay cannot pretend to be today's decision by supplying an unrelated date.
        if abs((datetime.strptime(decision_as_of, "%Y%m%d") -
                datetime.strptime(str(as_of), "%Y%m%d")).days) > 7:
            raise ValueError("D2 decision date is more than seven calendar days from settled regime date")
        action_run_date = _current_run_date()
        if not is_canonical_date(action_run_date):
            raise ValueError("D2 controlled runner clock returned an invalid date")
    cal = list(trade_calendar)
    ledger = load_ledger(ledger_path)
    was_empty = not (ledger.get("rows") or [])
    if was_empty and not bootstrap:
        raise ValueError("run_regime_step: no existing ledger — initial creation requires explicit "
                         "bootstrap=True (a weekly run must not silently bootstrap)")
    records = load_comparison_records(records_path)
    # scope the breadth universe to A-share MAIN BOARD only (user directive; excludes ChiNext/STAR/BSE)
    daily = main_board_only(daily)
    stk_limit = main_board_only(stk_limit)
    # default provider = real fetch→compute over the injected frames; an explicit feature_provider may
    # be supplied (DI for tests / alternative sources), mirroring engine.a_short_regime_pipeline.
    provider = feature_provider or make_feature_provider(
        daily, stk_limit, csi300, csi1000, iv_series_to_map(iv_feed))
    out = weekly_regime_step(ledger, as_of, cal, v14_2_regime, csi1000, provider,
                             prior_comparison_records=records)
    if was_empty and len(out["ledger"]["rows"]) < BACKFILL_MIN_TRADING_DAYS:
        raise ValueError(f"run_regime_step: insufficient bootstrap — only {len(out['ledger']['rows'])} "
                         f"< {BACKFILL_MIN_TRADING_DAYS} eligible trading days; refusing to start the "
                         f"comparison evidence clock from an insufficient window")
    save_ledger(out["ledger"], ledger_path, as_of=as_of, trade_calendar=cal)
    save_comparison_records(out["comparison_records"], records_path)
    save_panel(out["panel_markdown"], panel_path)
    if action_requested:
        old_actions = load_comparison_records(str(action_records_path))
        refreshed = refresh_action_records(old_actions, out["comparison_records"])
        current_action = build_action_record(
            regime_record=out["comparison_record"], raw_v14_2_regime=str(raw_v14_2_regime),
            effective_v14_2_regime=v14_2_regime,
            m67_source=m67_provenance(str(m67_report_path), as_of=as_of),
            forward_origin={"decision_as_of": str(action_decision_as_of),
                            "run_date": str(action_run_date)},
        )
        actions = merge_action_records(refreshed, current_action)
        summary = summarize_action_records(actions)
        save_action_records(actions, str(action_records_path), current_action=current_action,
                            regime_records=out["comparison_records"])
        _write_json(summary, str(action_summary_path))
        out["action_comparison"] = {"records": actions, "summary": summary}
    return out


# ---- thin real-fetch + CLI (NOT unit-tested; first real-Tushare 执行 = bootstrap) ---------------

def _init_pro():
    # Use the repo's sanctioned init (pins the base URL, no set_token) — plain ts.set_token+pro_api
    # hits Tushare's silent-empty-DataFrame failure mode (trade_cal/daily return 0 rows), which would
    # let a bootstrap silently fetch nothing. (Found by the pre-bootstrap fetch probe, 2026-06-12.)
    from runners.a_short_iv_feed_probe import init_tushare_pro
    token = os.environ.get("TUSHARE_TOKEN")
    if not token:
        raise SystemExit("TUSHARE_TOKEN not set; the V14.3 regime fetch needs it")
    return init_tushare_pro(token)


def _fetch_trade_calendar(pro, start: str, end: str) -> list:
    df = pro.trade_cal(exchange="SSE", start_date=start, end_date=end, is_open="1", fields="cal_date")
    return sorted(str(d) for d in df["cal_date"]) if df is not None and len(df) else []


def _fetch_daily(pro, dates: list) -> pd.DataFrame:
    frames = [pro.daily(trade_date=d, fields="ts_code,trade_date,high,close") for d in dates]
    frames = [f for f in frames if f is not None and len(f)]
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(
        columns=["ts_code", "trade_date", "high", "close"])


def _fetch_stk_limit(pro, dates: list) -> pd.DataFrame:
    frames = [pro.stk_limit(trade_date=d, fields="ts_code,trade_date,up_limit,down_limit") for d in dates]
    frames = [f for f in frames if f is not None and len(f)]
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(
        columns=["ts_code", "trade_date", "up_limit", "down_limit"])


def _fetch_index(pro, ts_code: str, start: str, end: str) -> pd.DataFrame:
    df = pro.index_daily(ts_code=ts_code, start_date=start, end_date=end, fields="trade_date,close")
    return df if df is not None and len(df) else pd.DataFrame(columns=["trade_date", "close"])


def _latest_settled_as_of(daily: pd.DataFrame, requested_as_of: str) -> str:
    """The latest ``trade_date`` in the fetched ``daily`` panel that is ``<= requested_as_of``.

    When the weekly runs intraday before ``requested_as_of``'s own EOD is published, that day's daily
    bars don't exist yet, so the regime ledger must advance only through the latest SETTLED trade date
    instead of fail-closing on a not-yet-settled day. For a settled ``requested_as_of`` this is a no-op
    (panel max == requested). Empty panel → requested (caller guards empty separately)."""
    if daily is None or daily.empty or "trade_date" not in daily.columns:
        return str(requested_as_of)
    dates = [str(d) for d in daily["trade_date"] if str(d) <= str(requested_as_of)]
    return max(dates) if dates else str(requested_as_of)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="A-short V14.3 regime comparison runner (non-production)")
    ap.add_argument("--as-of", required=True, help="run date YYYYMMDD")
    ap.add_argument("--v14_2-regime", default="unknown", help="production V14.2 M1 regime label")
    ap.add_argument("--v14_2-raw-regime", default=None,
                    help="raw analysis_input V14.2 label; required with --m67-report for D2")
    ap.add_argument("--m67-report", default=None,
                    help="same-week M6.7 report; only SHA-256 + candidate build count are persisted")
    ap.add_argument("--bootstrap", action="store_true",
                    help="one-time 252-day backfill (heavy Tushare 执行)")
    ap.add_argument("--iv-feed", default=None, help="path to the a_short_iv_feed.json artifact")
    ap.add_argument("--confirm-fetch-authorized", action="store_true",
                    help="required to perform any real Tushare fetch")
    args = ap.parse_args(argv)
    as_of = args.as_of
    if not is_canonical_date(as_of):
        raise SystemExit(f"--as-of must be a real canonical YYYYMMDD date, got {as_of!r}")
    if not args.confirm_fetch_authorized:
        raise SystemExit("real Tushare fetch is user-authorized only: pass --confirm-fetch-authorized "
                         "(the bootstrap 252-day backfill is the first real-Tushare 执行 in V14.3)")
    paths = lane_paths()
    ledger0 = load_ledger(paths["ledger"])
    has_ledger = bool(ledger0.get("rows"))
    if not has_ledger and not args.bootstrap:
        raise SystemExit("no existing regime ledger — first run must be --bootstrap (252-day backfill)")
    pro = _init_pro()
    # CALENDAR must span the full existing ledger (the gate requires every ledger date on the calendar);
    # for bootstrap, reach back far enough for >= 252 trading days. DAILY/stk_limit are only needed for
    # the days actually computed (the new dates + their MA20 lookback), so fetch a recent window only.
    if has_ledger and not args.bootstrap:
        cal_start = str(ledger0["coverage"]["start"])
        daily_start = (datetime.strptime(as_of, "%Y%m%d") - timedelta(days=60)).strftime("%Y%m%d")
    else:
        cal_start = (datetime.strptime(as_of, "%Y%m%d") - timedelta(days=400)).strftime("%Y%m%d")
        daily_start = cal_start
    cal = _fetch_trade_calendar(pro, cal_start, as_of)
    daily_dates = [d for d in cal if d >= daily_start]
    daily = _fetch_daily(pro, daily_dates)
    stk_limit = _fetch_stk_limit(pro, daily_dates)
    csi300 = _fetch_index(pro, "000300.SH", cal_start, as_of)
    csi1000 = _fetch_index(pro, "000852.SH", cal_start, as_of)
    if daily.empty:
        raise SystemExit(f"--as-of {as_of}: 抓不到任何 <= as_of 的 daily 行情(休市 / 当日 EOD 未结算?);无法推进 regime ledger")
    # 把 as_of 收敛到最新已结算交易日:实盘盘中(周一 as_of 当日 EOD 未结算)→ 推进到上周五,不为未结算日伪造 row。
    effective_as_of = _latest_settled_as_of(daily, as_of)
    if effective_as_of != as_of:
        print(f"[regime] as_of {as_of} 当日 EOD 尚未结算;regime ledger 推进到最新已结算交易日 {effective_as_of}")
    iv_feed = json.loads(Path(args.iv_feed).read_text(encoding="utf-8")) if args.iv_feed else None
    if bool(args.v14_2_raw_regime) != bool(args.m67_report):
        raise SystemExit("D2 action comparison requires both --v14_2-raw-regime and --m67-report, or neither")
    action_paths = ({"action_records_path": paths["action_records"], "action_summary_path": paths["action_summary"],
                     "action_decision_as_of": as_of}
                    if args.v14_2_raw_regime else {})
    out = run_regime_step(as_of=effective_as_of, trade_calendar=cal, v14_2_regime=args.v14_2_regime,
                          daily=daily, stk_limit=stk_limit, csi300=csi300, csi1000=csi1000,
                          iv_feed=iv_feed, ledger_path=paths["ledger"],
                          records_path=paths["records"], panel_path=paths["panel"],
                          bootstrap=args.bootstrap, raw_v14_2_regime=args.v14_2_raw_regime,
                          m67_report_path=args.m67_report,
                          **action_paths)
    print(f"V14.3 regime comparison written (non-production): ledger n={out['ledger']['coverage']['n']}, "
          f"evidence={out['evidence']}, panel={paths['panel']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

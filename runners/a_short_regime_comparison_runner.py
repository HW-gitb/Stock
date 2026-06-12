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

RECORDS_FILENAME = "regime_comparison_records.json"
PANEL_FILENAME = "regime_comparison_panel.md"
IV_FEED_SCHEMA_PATH = ROOT / "schemas" / "a_short_iv_feed.schema.json"


# ---- pure helpers -----------------------------------------------------------------------------

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


def save_panel(markdown: str, path: str) -> None:
    _reject_production_path(path)
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    Path(path).write_text(markdown, encoding="utf-8")


def run_regime_step(*, as_of: str, trade_calendar, v14_2_regime: str,
                    daily: pd.DataFrame, stk_limit: pd.DataFrame,
                    csi300: pd.DataFrame, csi1000: pd.DataFrame, iv_feed: dict | None,
                    ledger_path: str, records_path: str, panel_path: str,
                    bootstrap: bool = False, feature_provider=None) -> dict:
    """One comparison run (orchestration; all data frames injected, so unit-testable without Tushare).

    Loads the ledger + comparison-record history, builds the real feature provider, runs the audited
    weekly step, then persists ledger + records + panel under the guard-safe lane.

    Initial ledger creation is **explicit-bootstrap-only**: an absent/empty ledger with
    ``bootstrap=False`` raises (a weekly run must not silently create a ledger), and a bootstrap that
    yields fewer than ``BACKFILL_MIN_TRADING_DAYS`` rows raises (do not start the evidence clock from an
    insufficient window). Returns the step output."""
    cal = list(trade_calendar)
    ledger = load_ledger(ledger_path)
    was_empty = not (ledger.get("rows") or [])
    if was_empty and not bootstrap:
        raise ValueError("run_regime_step: no existing ledger — initial creation requires explicit "
                         "bootstrap=True (a weekly run must not silently bootstrap)")
    records = load_comparison_records(records_path)
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
    return out


# ---- thin real-fetch + CLI (NOT unit-tested; first real-Tushare 执行 = bootstrap) ---------------

def _init_pro():
    import tushare as ts
    token = os.environ.get("TUSHARE_TOKEN")
    if not token:
        raise SystemExit("TUSHARE_TOKEN not set; the V14.3 regime fetch needs it")
    ts.set_token(token)
    return ts.pro_api()


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


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="A-short V14.3 regime comparison runner (non-production)")
    ap.add_argument("--as-of", required=True, help="run date YYYYMMDD")
    ap.add_argument("--v14_2-regime", default="unknown", help="production V14.2 M1 regime label")
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
    from datetime import datetime, timedelta
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
    iv_feed = json.loads(Path(args.iv_feed).read_text(encoding="utf-8")) if args.iv_feed else None
    out = run_regime_step(as_of=as_of, trade_calendar=cal, v14_2_regime=args.v14_2_regime,
                          daily=daily, stk_limit=stk_limit, csi300=csi300, csi1000=csi1000,
                          iv_feed=iv_feed, ledger_path=paths["ledger"],
                          records_path=paths["records"], panel_path=paths["panel"],
                          bootstrap=args.bootstrap)
    print(f"V14.3 regime comparison written (non-production): ledger n={out['ledger']['coverage']['n']}, "
          f"evidence={out['evidence']}, panel={paths['panel']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

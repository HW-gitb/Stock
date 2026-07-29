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
sizing / overlay / M6.7 action). V14.2 stays the frozen production baseline. When the D2 action
summary reaches a review status, this runner prints and persists a reminder to begin evidence review;
the reminder is not a production switch and never changes the production regime.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import jsonschema
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
from engine.a_short_regime_classifier import (
    classify_raw_regime, classify_stateful_regime, validate_comparison_record,
)
from engine.a_short_regime_action_comparison import (
    build_action_record, m67_provenance, merge_action_records, refresh_action_records,
    summarize_action_records, validate_action_record, build_candidate_effect_record,
    candidate_effect_policy, candidate_effect_policy_fingerprint,
    summarize_candidate_effect_records, validate_candidate_effect_summary,
)
from engine.data.a_share_board_scope import is_a_share_main_board
from engine.a_short_experiment_admission_registry import admission_snapshot
from engine import a_short_evidence_epoch_mode as _epoch_mode

RECORDS_FILENAME = "regime_comparison_records.json"
PANEL_FILENAME = "regime_comparison_panel.md"
ACTION_RECORDS_FILENAME = "regime_action_comparison_records.json"
ACTION_SUMMARY_FILENAME = "regime_action_comparison_summary.json"
P1_CANDIDATE_EFFECT_LEDGER_FILENAME = "a_short_regime_candidate_effect.json"
P1_CANDIDATE_EFFECT_SUMMARY_FILENAME = "regime_candidate_effect_summary.json"
P1_CANDIDATE_EFFECT_MARKDOWN_FILENAME = "regime_candidate_effect_summary.md"
P1_CANDIDATE_EFFECT_OUTCOME_FILENAME = "candidate_effect_outcome.json"
IV_FEED_SCHEMA_PATH = ROOT / "schemas" / "a_short_iv_feed.schema.json"
CANDIDATE_EFFECT_OUTCOME_SCHEMA_PATH = ROOT / "schemas" / "a_short_regime_candidate_effect_outcome.schema.json"


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
        # Per-stock evidence is deliberately local-only: it contains tickers and must never be
        # committed.  The paired research-lane summary is aggregate-only and contains no stocks.
        "candidate_effect_ledger": str(base / "logs" / P1_CANDIDATE_EFFECT_LEDGER_FILENAME),
        "candidate_effect_summary": str(lane / P1_CANDIDATE_EFFECT_SUMMARY_FILENAME),
        "candidate_effect_markdown": str(lane / P1_CANDIDATE_EFFECT_MARKDOWN_FILENAME),
        "candidate_effect_outcome": str(lane / P1_CANDIDATE_EFFECT_OUTCOME_FILENAME),
        "forward_tracker": str(base / "logs" / "forward_tracker.csv"),
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
    _atomic_write_text(json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False) + "\n", path)


def write_candidate_effect_outcome(*, as_of: str, result: dict, summary_path: str,
                                   outcome_path: str) -> dict:
    """Publish one de-identified current-run receipt even when candidate evidence is not updated."""
    if result.get("status") == "updated":
        prior_summary = result.get("summary") or {}
    else:
        try:
            prior_summary = json.loads(Path(summary_path).read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            prior_summary = {}
    try:
        validate_candidate_effect_summary(prior_summary)
    except (ValueError, TypeError):
        observed_as_of = None
    else:
        observed_as_of = prior_summary.get("latest_evidence_as_of")
    outcome = {
        "schema_name": "a_short_regime_candidate_effect_outcome",
        "schema_version": "1.0.0",
        "as_of": str(as_of),
        "status": str(result.get("status")),
        "reason_code": str(result.get("reason_code") or "updated"),
        "observed_as_of": observed_as_of,
    }
    schema = json.loads(CANDIDATE_EFFECT_OUTCOME_SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.validate(outcome, schema)
    _write_json(outcome, outcome_path)
    return outcome


def _atomic_write_text(text: str, path: str) -> None:
    """Write one sidecar artifact atomically; a failed rerun cannot truncate its last valid version."""
    _reject_production_path(path)
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=str(target.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, target)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


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
    _atomic_write_text(markdown, path)


def render_action_review_reminder(summary: dict) -> str | None:
    """Return the durable, non-production review reminder for a settled D2 action summary.

    The D2 summary is the sole machine-owned input: it already enforces the 12 forward-week / 8
    settled-H10 gate before it can return a review status. The remaining PIT-backtest, missed-opportunity,
    data-quality, and state-machine checks are deliberately human/review-owned, so this function asks
    for that review rather than claiming V14.3 is production-ready. Unknown summary states fail closed
    instead of silently suppressing a possible reminder.
    """
    if summary.get("automatic_production_switch") is not False:
        raise ValueError("V14.3 action reminder requires automatic_production_switch=false")
    status = str(summary.get("status"))
    if status == "accumulating":
        return None
    forward = summary.get("total_forward_weeks")
    h10 = summary.get("settled_divergence_h10")
    header = "## V14.3 regime review reminder"
    evidence = f"- 已计入 forward 周数：`{forward}`；已结算 H10 动作分歧：`{h10}`。"
    boundary = "- 仍为 `comparison-only`；`automatic_production_switch=false`，不会自动切生产。"
    if status == "review_candidate_preferred":
        return "\n".join((
            header,
            f"- 状态：`{status}`。",
            evidence,
            "- 自动提醒：V14.3 forward evidence 已达复核触发门，请启动 V14.3 晋级证据复核"
            "（含 ≥2 年 PIT 回测、漏失机会、数据污染、状态机与动作矩阵重放）。",
            boundary,
        ))
    if status == "review_baseline_preferred":
        reason = "V14.2 baseline 目前更优"
    elif status == "review_inconclusive":
        reason = "现有证据仍无结论"
    else:
        raise ValueError(f"unknown V14.3 action summary status {status!r}")
    return "\n".join((
        header,
        f"- 状态：`{status}`（{reason}）。",
        evidence,
        "- 自动提醒：请审查退役或继续收集；不得把当前对比结果接入生产。",
        boundary,
    ))


def append_action_review_reminder(panel_markdown: str, reminder: str | None) -> str:
    """Append a current D2 reminder to the existing comparison panel without a second artifact."""
    if reminder is None:
        return panel_markdown
    return f"{panel_markdown.rstrip()}\n\n---\n\n{reminder}\n"


# ---- P1 Cut2 per-stock candidate-effect sidecar ------------------------------------------------

def _sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _real_candidate_effect_selector_contract() -> str:
    contract = _epoch_mode.semantic_function_contract(
        sys.modules[__name__], ("_m67_build_candidates", "_tracker_rows_for_week"),
    )
    return hashlib.sha256(
        json.dumps(contract, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _candidate_effect_selector_contract() -> str:
    return _epoch_mode.fingerprint_or_pre_freeze(
        "p1_regime_candidate_effect",
        _real_candidate_effect_selector_contract,
    )


def _candidate_effect_policy_key() -> str:
    # The candidate universe is defined by the actual M6.7 projection and
    # tracker-cohort readers, not by row_source/action labels alone.
    return hashlib.sha256(
        json.dumps({"policy": candidate_effect_policy_fingerprint(),
                    "selector_contract": _candidate_effect_selector_contract()},
                   sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _empty_candidate_effect_ledger() -> dict:
    return {
        "schema_name": "a_short_regime_candidate_effect_ledger",
        "schema_version": "1.0.0",
        "policy_groups": {},
        "boundary": {"comparison_only": True, "automatic_production_switch": False},
    }


def _load_candidate_effect_ledger(path: str) -> dict:
    if not os.path.exists(path):
        return _empty_candidate_effect_ledger()
    ledger = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(ledger, dict) or ledger.get("schema_name") != "a_short_regime_candidate_effect_ledger" \
            or ledger.get("schema_version") != "1.0.0":
        raise ValueError("candidate-effect private ledger has an invalid identity")
    if ledger.get("boundary") != {"comparison_only": True, "automatic_production_switch": False}:
        raise ValueError("candidate-effect private ledger is not comparison-only")
    if not isinstance(ledger.get("policy_groups"), dict):
        raise ValueError("candidate-effect private ledger is missing policy_groups")
    return ledger


def _new_candidate_effect_group() -> dict:
    policy = candidate_effect_policy()
    fingerprint = _candidate_effect_policy_key()
    return {
        "policy": {
            "policy_id": policy["policy_id"],
            "policy_epoch": policy["policy_epoch"],
            "policy_fingerprint": fingerprint,
            "selector_contract_sha256": _candidate_effect_selector_contract(),
        },
        "admission_binding": admission_snapshot("p1_regime_action_proxy"),
        "weeks": {},
        "records": [],
    }


def _finite_or_none(value) -> float | None:
    if value is None or str(value).strip() == "":
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _tracker_return_map(row: dict) -> dict:
    stock, benchmark = {}, {}
    for days, horizon in ((5, "h5"), (10, "h10"), (20, "h20")):
        # A non-ok tracker status is intentionally not converted to a zero return.  The pure
        # summary will report it as immature/missing rather than fabricating a cash outcome.
        stock[horizon] = (
            _finite_or_none(row.get(f"ret_{days}d_t1_net"))
            if str(row.get(f"ret_{days}d_status") or "") == "ok" else None
        )
        benchmark[horizon] = _finite_or_none(row.get(f"ret_{days}d_excess_csi1000"))
        if stock[horizon] is not None and benchmark[horizon] is not None:
            # Tracker stores stock-minus-benchmark excess; recover the benchmark return without
            # reading any raw price data or writing it to a public artifact.
            benchmark[horizon] = stock[horizon] - benchmark[horizon]
        else:
            benchmark[horizon] = None
    return {"stock_net_returns": stock, "csi1000_returns": benchmark}


def _load_tracker_rows(path: str) -> list[dict]:
    """Read tracker rows once; callers decide whether they need cohort or frozen-record validation."""
    tracker_path = Path(path)
    if not tracker_path.exists():
        raise ValueError(f"forward tracker is missing: {tracker_path}")
    with tracker_path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = [dict(row) for row in csv.DictReader(handle)]
    return rows


def _tracker_rows_for_week(path: str, as_of: str, *, all_rows: list[dict] | None = None) -> tuple[dict[str, dict], dict]:
    """Read the existing tracker as the sole current authority for a candidate cohort and returns."""
    rows = [row for row in (all_rows if all_rows is not None else _load_tracker_rows(path))
            if str(row.get("as_of")) == str(as_of)]
    if not rows:
        raise ValueError(f"forward tracker has no {as_of} cohort")
    by_code = {}
    digests, run_ids, modes = set(), set(), set()
    for row in rows:
        code = str(row.get("ts_code") or "")
        if not code or code in by_code:
            raise ValueError("forward tracker cohort has a blank or duplicate ts_code")
        digest = str(row.get("candidate_digest") or "")
        run_id = str(row.get("run_id") or "")
        if not digest or not run_id:
            raise ValueError("forward tracker cohort has no run identity")
        by_code[code] = row
        digests.add(digest)
        run_ids.add(run_id)
        modes.add(str(row.get("forward_live") or "").lower())
    if len(digests) != 1 or len(run_ids) != 1 or len(modes) != 1:
        raise ValueError("forward tracker cohort has mixed run identities or capture modes")
    return by_code, {
        "candidate_digest": next(iter(digests)),
        "run_id": next(iter(run_ids)),
        "forward_live": next(iter(modes)) == "true",
    }


def _tracker_rows_by_frozen_key(rows: list[dict]) -> dict[tuple[str, str], dict]:
    out = {}
    for row in rows:
        key = (str(row.get("as_of") or ""), str(row.get("ts_code") or ""))
        if not all(key):
            continue
        if key in out:
            raise ValueError("forward tracker has duplicate frozen evidence keys")
        out[key] = row
    return out


def _m67_build_candidates(path: str, *, as_of: str) -> tuple[list[dict], dict]:
    """Return a deliberately minimal public candidate projection from a weekly M6.7 artifact.

    The full weekly artifact may be private when it contains an account.  This function reads it
    only to decide whether a row is an ordinary EGS new-build candidate, then retains no name,
    position, cash, price, or report body in the P1 artifacts.
    """
    raw = Path(path).read_bytes()
    doc = json.loads(raw.decode("utf-8"))
    if not isinstance(doc, dict) or doc.get("schema_name") != "a_short_weekly_report":
        raise ValueError("M6.7 source is not an a_short_weekly_report")
    if str(doc.get("as_of")) != str(as_of):
        raise ValueError("M6.7 source as_of does not match the candidate decision date")
    lineage = doc.get("run_lineage") or {}
    candidate_digest = str(lineage.get("candidate_digest") or "")
    run_id = str(lineage.get("run_id") or "")
    if not candidate_digest or len(candidate_digest) != 64 or not run_id:
        raise ValueError("M6.7 source has no valid run identity")
    reports = doc.get("reports")
    if not isinstance(reports, list):
        raise ValueError("M6.7 source is missing reports")

    candidates = []
    seen = set()
    for report in reports:
        if not isinstance(report, dict) or str(report.get("row_source")) != "egs_candidate":
            continue
        table = ((report.get("m67") or {}).get("table") or {})
        if str(table.get("操作")) != "建仓":
            continue
        code = str(report.get("ts_code") or "")
        if not code or code in seen:
            raise ValueError("M6.7 build candidates contain a blank or duplicate ts_code")
        machine = report.get("machine") or {}
        stateful_risk = machine.get("stateful_risk") or {}
        rule6 = machine.get("rule6_gate") or {}
        layer = machine.get("layer") or {}
        hard_veto = bool((layer.get("hard_veto") or []))
        candidates.append({
            "as_of": str(as_of),
            "ts_code": code,
            "row_source": "egs_candidate",
            "m67_action": "建仓",
            "is_holding": str(stateful_risk.get("position_state") or "flat") == "held",
            "is_watch": False,
            "is_vetoed": hard_veto,
            "manual_review": str(rule6.get("disposition") or "") == "manual_review",
        })
        seen.add(code)
    candidate_set_digest = hashlib.sha256(
        json.dumps(sorted(c["ts_code"] for c in candidates), separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return candidates, {
        "m67_sha256": _sha256_bytes(raw),
        "candidate_digest": candidate_digest,
        "run_id": run_id,
        "candidate_set_digest": candidate_set_digest,
    }


def _stateful_regime_for_decision(ledger: dict, *, decision_as_of: str) -> tuple[dict, str]:
    """Rebuild the Cut1 state trace from the existing daily ledger without data fetches."""
    rows = list(ledger.get("rows") or [])
    if not rows:
        raise ValueError("candidate-effect requires an existing non-empty regime daily ledger")
    raw_history = [classify_raw_regime(rows, as_of=str(row["as_of"])) for row in rows]
    settled = str(raw_history[-1]["as_of"])
    if settled > str(decision_as_of):
        raise ValueError("stateful regime source date is after the candidate decision date")
    if (datetime.strptime(str(decision_as_of), "%Y%m%d") -
            datetime.strptime(settled, "%Y%m%d")).days > 7:
        raise ValueError("stateful regime source is more than seven calendar days stale")
    state = classify_stateful_regime(raw_history, as_of=settled)
    # The state is sourced from the most recently settled daily row (Friday for a Monday canonical
    # run), while the P1 record itself remains bound to the decision/candidate date.
    return {"as_of": str(decision_as_of), "stateful_regime": state["stateful_regime"],
            "state_evaluable": state["state_evaluable"]}, settled


def _record_has_mature_return(record: dict) -> bool:
    return any(value is not None for value in (record.get("baseline_net_returns") or {}).values())


def _frozen_record_refresh(record: dict, tracker_row: dict) -> dict:
    candidate = {"as_of": record["as_of"], "ts_code": record["ts_code"],
                 "row_source": record["row_source"], "m67_action": record["m67_action"]}
    state = {"as_of": record["as_of"], "stateful_regime": record["stateful_regime"],
             "state_evaluable": record["state_evaluable"]}
    rebuilt = build_candidate_effect_record(
        candidate=candidate, stateful_regime=state, forward_returns=_tracker_return_map(tracker_row),
        evidence_origin=record["evidence_origin"],
    )
    if rebuilt is None:
        raise ValueError("frozen candidate record became ineligible")
    return rebuilt


def _render_candidate_effect_summary(summary: dict) -> str:
    """Render only aggregate evidence.  The machine-readable JSON mirror makes equivalence auditable."""
    progress = summary["evidence_progress"]
    operation = summary["operation_effect"]
    selection = summary["selection_accuracy"]
    verdict_labels = {
        "candidate_better": "V14.3 candidate proxy is better on the current evidence.",
        "baseline_better": "The frozen V14.2 baseline is better on the current evidence.",
        "no_material_difference": "No material operation difference is established.",
        "insufficient_data": "Evidence is still insufficient; no preference is established.",
    }
    selection_note = {
        "supportive": "Forbidden stocks more often underperformed CSI1000; selection accuracy is supportive.",
        "not_supportive": "Forbidden stocks did not underperform CSI1000; selection accuracy is not proven.",
        "mixed": "Forbidden-stock CSI1000 excess is mixed; selection accuracy is not proven.",
        "not_evaluable": "No mature forbidden-stock CSI1000 comparison exists; selection accuracy is not evaluable.",
    }[selection["status"]]
    def fmt(value):
        return "N/A" if value is None else f"{float(value):.4f}"
    mirror = json.dumps(summary, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return "\n".join((
        "# V14.3 per-stock candidate-effect summary",
        "",
        f"**Conclusion:** {verdict_labels[summary['verdict']]}",
        "**Operation boundary:** comparison-only; V14.3 never changes EGS, M6.7, account state, new-entry authorization, or the formal weekly report.",
        f"**Selection accuracy:** {selection_note}",
        "",
        "## Evidence progress",
        f"- Forward-live weeks: {progress['forward_live_weeks']}",
        f"- Mature divergent weeks / stocks: {progress['valid_divergence_weeks']} / {progress['valid_divergence_stocks']}",
        f"- H20 mature / pending divergent weeks: {progress['h20_mature_weeks']} / {progress['h20_pending_weeks']}",
        f"- Historical not counted: {progress['historical_not_counted']}; immature or missing not counted: {progress['immature_or_missing_not_counted']}",
        f"- Ready for verdict: {str(progress['ready_for_verdict']).lower()}",
        "",
        "## Equal-weighted operation effect",
        f"- H10 weekly mean / median improvement (pp): {fmt(operation['weekly_mean_improvement_pp'])} / {fmt(operation['weekly_median_improvement_pp'])}",
        f"- Favorable-week ratio: {fmt(operation['favorable_week_ratio'])}",
        f"- H20 auxiliary mean improvement (pp): {fmt(operation['auxiliary_h20_mean_improvement_pp'])}",
        "",
        "## Guardrail",
        "- Baseline = current production build without regime-driven candidate action.",
        "- Defense/contraction cash 0% is a simplified comparison proxy, not a final production defense policy; no automatic switch exists.",
        "",
        f"<!-- candidate-effect-summary-json:{mirror} -->",
        "",
    ))


def run_candidate_effect_sidecar(*, decision_as_of: str, regime_ledger: dict, m67_report_path: str,
                                 tracker_path: str, ledger_path: str, summary_path: str,
                                 markdown_path: str) -> dict:
    """Freeze/refresh P1 Cut2 evidence from existing M6.7 and forward-tracker artifacts only.

    This never fetches market data and never writes production or private-account artifacts.  A
    same-date tracker replacement is accepted only before any return matures; otherwise immutable
    evidence wins.  A source digest mismatch returns a non-counting warning without overwriting the
    last valid private ledger or public summary.
    """
    if not is_canonical_date(str(decision_as_of)):
        raise ValueError("candidate-effect decision_as_of must be a canonical date")
    all_tracker_rows = _load_tracker_rows(tracker_path)
    tracker_by_code, tracker_meta = _tracker_rows_for_week(
        tracker_path, str(decision_as_of), all_rows=all_tracker_rows)
    candidates, m67_meta = _m67_build_candidates(m67_report_path, as_of=str(decision_as_of))
    if (m67_meta["candidate_digest"] != tracker_meta["candidate_digest"]
            or m67_meta["run_id"] != tracker_meta["run_id"]):
        return {"status": "skipped_source_mismatch", "counted": False,
                "reason_code": "run_identity_mismatch",
                "reason": "M6.7 and forward-tracker run identity differ"}
    missing_tracker_rows = sorted(c["ts_code"] for c in candidates if c["ts_code"] not in tracker_by_code)
    if missing_tracker_rows:
        return {"status": "skipped_source_mismatch", "counted": False,
                "reason_code": "tracker_rows_missing",
                "reason": "M6.7 build candidates are absent from forward_tracker"}

    run_date = _current_run_date()
    capture_mode = "live" if tracker_meta["forward_live"] and str(decision_as_of) >= run_date else "historical_replay"
    state, state_source_as_of = _stateful_regime_for_decision(regime_ledger, decision_as_of=str(decision_as_of))
    ledger = _load_candidate_effect_ledger(ledger_path)
    policy_key = _candidate_effect_policy_key()
    group = ledger["policy_groups"].setdefault(policy_key, _new_candidate_effect_group())
    if group.get("policy") != _new_candidate_effect_group()["policy"] or \
            group.get("admission_binding") != _new_candidate_effect_group()["admission_binding"]:
        raise ValueError("candidate-effect current policy group identity is inconsistent")
    if not isinstance(group.get("weeks"), dict) or not isinstance(group.get("records"), list):
        raise ValueError("candidate-effect policy group is malformed")

    prior_week = group["weeks"].get(str(decision_as_of))
    prior_records = [r for r in group["records"] if str(r.get("as_of")) == str(decision_as_of)]
    current_source = {**m67_meta, **tracker_meta, "state_source_as_of": state_source_as_of,
                      "capture_mode": capture_mode}
    if prior_week is not None and prior_week.get("candidate_digest") == tracker_meta["candidate_digest"] \
            and prior_week.get("m67_sha256") != m67_meta["m67_sha256"]:
        return {"status": "skipped_source_mismatch", "counted": False,
                "reason_code": "m67_digest_drift",
                "reason": "same-date M6.7 SHA-256 changed under an otherwise frozen cohort"}
    # Every new weekly invocation is also the cache-only maturation pass for all older frozen
    # observations.  A missing historical tracker row remains unchanged (never zero-filled); this
    # makes the tracker the only authority for return replacement without making a later M6.7 file
    # rewrite old candidate eligibility.
    tracker_by_frozen_key = _tracker_rows_by_frozen_key(all_tracker_rows)
    group["records"] = [
        _frozen_record_refresh(record, tracker_by_frozen_key[(str(record["as_of"]), str(record["ts_code"]))])
        if (str(record["as_of"]), str(record["ts_code"])) in tracker_by_frozen_key else record
        for record in group["records"]
    ]
    prior_records = [r for r in group["records"] if str(r.get("as_of")) == str(decision_as_of)]
    if prior_week is not None and prior_week.get("candidate_digest") != tracker_meta["candidate_digest"]:
        if any(_record_has_mature_return(record) for record in prior_records):
            return {"status": "skipped_immutable_mature_week", "counted": False,
                    "reason_code": "immutable_mature_week",
                    "reason": "same-date tracker replacement arrived after a mature return"}
        group["records"] = [r for r in group["records"] if str(r.get("as_of")) != str(decision_as_of)]
        prior_records = []

    if prior_week is None or not prior_records:
        fresh_records = []
        for candidate in candidates:
            record = build_candidate_effect_record(
                candidate=candidate, stateful_regime=state,
                forward_returns=_tracker_return_map(tracker_by_code[candidate["ts_code"]]),
                evidence_origin={"capture_mode": capture_mode, "decision_as_of": str(decision_as_of)},
            )
            if record is not None:
                fresh_records.append(record)
        group["records"].extend(fresh_records)
        group["weeks"][str(decision_as_of)] = current_source
    else:
        # Same input reruns do not re-decide M6.7 eligibility or state.  They only apply the
        # forward tracker’s sanctioned return backfill to the already frozen candidate set.
        refreshed = [_frozen_record_refresh(record, tracker_by_code[record["ts_code"]])
                     for record in prior_records]
        group["records"] = [r for r in group["records"] if str(r.get("as_of")) != str(decision_as_of)] + refreshed

    group["records"].sort(key=lambda r: (str(r["as_of"]), str(r["ts_code"])))
    summary = summarize_candidate_effect_records(group["records"])
    # The active summary is one policy cohort.  Expose the total isolated groups as a data-quality
    # count, never by pooling old and new policy records.
    summary["data_quality"]["policy_groups"] = len(ledger["policy_groups"])
    # The policy-group count is added by the runner after aggregation, so
    # validate the final exact public object before either paired artifact.
    validate_candidate_effect_summary(summary)
    _write_json(ledger, ledger_path)
    _write_json(summary, summary_path)
    _atomic_write_text(_render_candidate_effect_summary(summary), markdown_path)
    return {"status": "updated", "reason_code": "updated",
            "counted": capture_mode == "live", "summary": summary,
            "records_frozen": len(group["records"])}


def run_regime_step(*, as_of: str, trade_calendar, v14_2_regime: str,
                    daily: pd.DataFrame, stk_limit: pd.DataFrame,
                    csi300: pd.DataFrame, csi1000: pd.DataFrame, iv_feed: dict | None,
                    ledger_path: str, records_path: str, panel_path: str,
                    bootstrap: bool = False, feature_provider=None,
                    raw_v14_2_regime: str | None = None, m67_report_path: str | None = None,
                    action_records_path: str | None = None, action_summary_path: str | None = None,
                    action_decision_as_of: str | None = None,
                    candidate_effect_ledger_path: str | None = None,
                    candidate_effect_summary_path: str | None = None,
                    candidate_effect_markdown_path: str | None = None,
                    forward_tracker_path: str | None = None) -> dict:
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
    candidate_effect_requested = any(v is not None for v in
                                     (candidate_effect_ledger_path, candidate_effect_summary_path,
                                      candidate_effect_markdown_path, forward_tracker_path))
    if action_requested and not all(v is not None for v in
                                    (raw_v14_2_regime, m67_report_path, action_records_path, action_summary_path,
                                     action_decision_as_of)):
        raise ValueError("D2 action comparison requires raw V14.2 regime, M6.7 source, paths and decision date")
    if candidate_effect_requested and not all(v is not None for v in
                                              (candidate_effect_ledger_path, candidate_effect_summary_path,
                                               candidate_effect_markdown_path, forward_tracker_path)):
        raise ValueError("candidate-effect sidecar requires all private/public/tracker paths")
    if candidate_effect_requested and not action_requested:
        raise ValueError("candidate-effect sidecar requires the same-week D2 M6.7 source and decision date")
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
        existing_action = next((row for row in refreshed if str(row["as_of"]) == str(as_of)), None)
        if existing_action is None:
            m67_source = m67_provenance(str(m67_report_path), as_of=as_of)
            m67_doc = json.loads(Path(m67_report_path).read_text(encoding="utf-8"))
            m67_lineage = m67_doc.get("run_lineage") or {}
            price_freshness = m67_lineage.get("price_freshness") or {}
            source_price_data_through = str(price_freshness.get("price_data_through") or "")
            if price_freshness.get("mode") not in {"strict_as_of", "intraday_prior_settled"} \
                    or not source_price_data_through:
                raise ValueError("D2 M6.7 source lacks a complete price freshness clock")
            receipt_path = Path(m67_report_path).with_name("weekly_m67.receipt.json")
            source_receipt_complete = False
            if receipt_path.is_file():
                receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
                source_receipt_complete = (
                    receipt.get("stage_status") == "complete"
                    and receipt.get("as_of") == as_of
                    and receipt.get("run_id") == m67_lineage.get("run_id")
                    and receipt.get("candidate_digest") == m67_lineage.get("candidate_digest")
                )
            if price_freshness.get("mode") == "intraday_prior_settled":
                price_day_latest_settled = (
                    str(price_freshness.get("accepted_prior_settled_date") or "") == source_price_data_through
                    and source_price_data_through < str(action_decision_as_of)
                )
            else:
                price_day_latest_settled = source_price_data_through == str(action_decision_as_of)
            current_action = build_action_record(
                regime_record=out["comparison_record"], raw_v14_2_regime=str(raw_v14_2_regime),
                effective_v14_2_regime=v14_2_regime,
                m67_source=m67_source,
                forward_origin={"decision_as_of": str(action_decision_as_of),
                                "run_date": str(action_run_date),
                                "capture_mode": ("live" if str(action_decision_as_of) >= str(action_run_date)
                                                 else "historical_replay"),
                                "price_data_through": source_price_data_through,
                                "source_receipt_complete": source_receipt_complete,
                                "price_day_latest_settled": price_day_latest_settled},
            )
            actions = merge_action_records(refreshed, current_action)
        else:
            # A rerun on the same settled week may use a different private M6.7 artifact
            # after account-state refresh. D2 is immutable comparison evidence, so retain
            # the first sanctioned observation rather than treating that expected rerun as
            # a history conflict. The engine-level merge guard remains strict for callers.
            current_action = existing_action
            actions = refreshed
        summary = summarize_action_records(actions)
        reminder = render_action_review_reminder(summary)
        save_action_records(actions, str(action_records_path), current_action=current_action,
                            regime_records=out["comparison_records"])
        _write_json(summary, str(action_summary_path))
        out["action_comparison"] = {"records": actions, "summary": summary,
                                    "review_reminder": reminder}
        if reminder is not None:
            out["panel_markdown"] = append_action_review_reminder(out["panel_markdown"], reminder)
            save_panel(out["panel_markdown"], panel_path)
    if candidate_effect_requested:
        out["candidate_effect"] = run_candidate_effect_sidecar(
            decision_as_of=str(action_decision_as_of), regime_ledger=out["ledger"],
            m67_report_path=str(m67_report_path), tracker_path=str(forward_tracker_path),
            ledger_path=str(candidate_effect_ledger_path), summary_path=str(candidate_effect_summary_path),
            markdown_path=str(candidate_effect_markdown_path),
        )
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
                     "action_decision_as_of": as_of,
                     "candidate_effect_ledger_path": paths["candidate_effect_ledger"],
                     "candidate_effect_summary_path": paths["candidate_effect_summary"],
                     "candidate_effect_markdown_path": paths["candidate_effect_markdown"],
                     "forward_tracker_path": paths["forward_tracker"]}
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
    action_comparison = out.get("action_comparison")
    if action_comparison:
        summary = action_comparison["summary"]
        reminder = action_comparison["review_reminder"]
        if reminder is not None:
            print(f"[REGIME REVIEW REQUIRED]\n{reminder}")
        else:
            print("[regime] V14.3 action comparison accumulating: "
                  f"forward={summary['total_forward_weeks']}, "
                  f"settled_divergence_h10={summary['settled_divergence_h10']}; "
                  "comparison-only, no production switch.")
    candidate_effect = out.get("candidate_effect")
    if candidate_effect:
        write_candidate_effect_outcome(
            as_of=as_of,
            result=candidate_effect,
            summary_path=paths["candidate_effect_summary"],
            outcome_path=paths["candidate_effect_outcome"],
        )
        if candidate_effect["status"] == "updated":
            progress = candidate_effect["summary"]["evidence_progress"]
            print("[candidate-effect] updated (comparison-only): "
                  f"forward_live_weeks={progress['forward_live_weeks']}, "
                  f"ready={progress['ready_for_verdict']}")
        else:
            print(f"[candidate-effect] {candidate_effect['status']}: {candidate_effect['reason']}; "
                  "this week is not counted and no prior result was overwritten")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

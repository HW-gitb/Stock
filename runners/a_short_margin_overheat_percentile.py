"""Bounded provider runner for the A-short margin-overheat percentile (queue row 19).

It makes only the authorized historical reads -- one ``trade_cal`` window and the
segmented ``pro.margin`` calls that cover it -- writes their raw responses below
the gitignored ``provider_samples/`` root, and writes a tracked evidence artifact
holding counts, coverage and percentiles.

Its job is to answer the one question row 19 refuses to answer by invention: at
p80 / p85 / p90 / p95, how many weeks in the observable history would this gate
have fired, how long was the longest run, and how were they distributed?  The
user picks the threshold and the cash factor from that; this runner never picks
either, never touches ``production_effect_enabled``, and never enters the weekly
production path.
"""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import sys
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from engine import a_short_margin_overheat as margin_overheat  # noqa: E402
from engine.a_short_market_history import canonical_dates  # noqa: E402
from engine.a_short_tushare_client import SUPPORTED_TUSHARE_VERSION, init_tushare_pro  # noqa: E402


PROBE_DATE = "20260806"
#: Budget for the ratio-basis evidence run (user adjudication 2026-08-06):
#: one six-year calendar read, five margin segments and five denominator
#: segments -- eleven planned calls under a twelve-call ceiling.
CALL_BUDGET = 12
SCHEMA_NAME = "a_short_margin_overheat_percentile_evidence"
SCHEMA_VERSION = "2.0.0"
RAW_ROOT = Path(f"provider_samples/a_short_margin_overheat_{PROBE_DATE}")
SUMMARY_PATH = Path(
    "research/results/a_short/margin_overheat_percentile_threshold_evidence.json"
)
CALENDAR_EXCHANGE = "SSE"


def _project_path(path: Path) -> Path:
    path = Path(path)
    return path if path.is_absolute() else PROJECT_ROOT / path


def _assert_raw_root(raw_root: Path) -> Path:
    resolved = _project_path(raw_root).resolve()
    provider_root = (PROJECT_ROOT / "provider_samples").resolve()
    try:
        resolved.relative_to(provider_root)
    except ValueError as exc:
        raise ValueError("raw payloads must stay under the gitignored provider_samples root") from exc
    return resolved


def _assert_not_production_output(out: Path) -> Path:
    resolved = _project_path(out).resolve()
    parts = [part.casefold() for part in resolved.parts]
    if any(
        parts[index:index + 2] == ["result", "a_short"]
        for index in range(len(parts) - 1)
    ):
        raise ValueError("margin overheat evidence cannot be written to result/a_short")
    return resolved


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str, allow_nan=False),
        encoding="utf-8",
    )


def _nonfinite_safe(value: Any) -> Any:
    """Make a raw provider payload writable under the strict no-NaN writer.

    The tracked summary must keep rejecting non-finite numbers, but on the raw
    capture path "refuse to persist" is the wrong response: the reviewed budget
    is already spent, and crashing here left nothing on disk to diagnose from
    (review Optional O-3).  Non-finite floats become their string names; every
    finite value passes through unchanged, so the engine still fails closed on
    the same input when the raw file is replayed.
    """
    if isinstance(value, float) and not math.isfinite(value):
        return "NaN" if math.isnan(value) else ("Infinity" if value > 0 else "-Infinity")
    if isinstance(value, dict):
        return {key: _nonfinite_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_nonfinite_safe(item) for item in value]
    return value


def _raw_json_value(value: Any) -> Any:
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        try:
            return {"kind": "dataframe", "rows": to_dict(orient="records")}
        except (TypeError, ValueError):
            return {"kind": type(value).__name__}
    if isinstance(value, dict):
        return value
    if isinstance(value, (list, tuple)):
        return list(value)
    return {"kind": type(value).__name__}


def _payload_records(payload: Any) -> list[dict[str, Any]] | None:
    to_dict = getattr(payload, "to_dict", None)
    if callable(to_dict):
        try:
            payload = to_dict(orient="records")
        except (TypeError, ValueError):
            return None
    if not isinstance(payload, (list, tuple)):
        return None
    if any(not isinstance(row, dict) for row in payload):
        return None
    return [dict(row) for row in payload]


def _load_raw_rows(path: Path) -> Any:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict) and payload.get("kind") in {"dataframe", "segmented_rows"}:
        return payload.get("rows")
    return payload


def _calendar_sessions(payload: Any, *, start: str, end: str) -> tuple[str, ...]:
    rows = _payload_records(payload)
    if rows is None:
        return ()
    if len(rows) >= margin_overheat.MARGIN_PROVIDER_ROW_CAP:
        return ()          # a capped calendar is truncated, not a short history
    dates = []
    for row in rows:
        value = str(row.get("cal_date", "")).strip()
        if value.endswith(".0"):
            value = value[:-2]
        if len(value) == 8 and value.isdigit() and start <= value <= end:
            dates.append(value)
    return canonical_dates(dates)


def build_evidence(
    margin_rows: Any,
    denominator_rows: Any,
    sessions: tuple[str, ...],
    *,
    as_of: str,
) -> dict[str, Any]:
    """Build the tracked ratio-basis evidence artifact from fetched windows.

    The scored quantity is the ratio (required-exchange ``rzye`` total over
    Shanghai Composite ``float_mv``), each week at the live gate's own rolling
    three-year caliber; six years of history make the last three years of
    weeks fully evaluable (user adjudication 2026-08-06).
    """
    calendar_session_count = len(sessions)
    sessions = margin_overheat.resolve_published_window(
        margin_rows, calendar_dates=sessions
    )
    # The evidence window is the full fetched history; the LIVE facts are the
    # newest rolling three years of it (the gate's own window).
    live_sessions = tuple(
        date for date in sessions
        if sessions and date >= margin_overheat.window_start(sessions[0])
    )
    facts = margin_overheat.margin_overheat_facts(
        margin_rows, denominator_rows, requested_dates=live_sessions
    )
    series = margin_overheat.margin_ratio_series(
        margin_rows, denominator_rows, requested_dates=sessions
    )
    not_verified: list[str] = [
        "no percentile threshold or cash factor is proposed here; both remain user adjudications",
        "the pre-BSE portion of the ratio sums two exchanges by the date-effective rule; "
        "BSE is about 0.3% of the total, an accepted step at its first published session",
    ]
    if not calendar_session_count:
        not_verified.append("no trading calendar was observed for the requested window")
    elif not sessions:
        not_verified.append(
            "no session within the normal publication lag carries its required exchange set, "
            "so the window could not be closed at a published reference date"
        )
    # Same floor discipline as the live facts
    # (R-ASHORT-SEQ19-EVIDENCE-LEG-SKIPS-THE-MIN-WINDOW-FLOOR): no table from
    # a window the gate itself would refuse.
    if not facts["coverage_complete"] or not series["coverage_complete"]:
        if (series["coverage_complete"]
                and len(live_sessions) < margin_overheat.MARGIN_OVERHEAT_MIN_WINDOW_SESSIONS):
            not_verified.append(
                f"the published live window has only {len(live_sessions)} trading sessions, below "
                f"the {margin_overheat.MARGIN_OVERHEAT_MIN_WINDOW_SESSIONS}-session rolling-window "
                "floor, so no percentile and no threshold evidence can be derived"
            )
        else:
            not_verified.append(
                "the margin or denominator window did not reconcile exactly, so no percentile "
                "and no trigger evidence could be derived"
            )
        evidence: dict[str, Any] = {
            "basis": None,
            "week_count": 0,
            "evaluable_week_count": 0,
            "unavailable_week_count": 0,
            "unavailable_breakdown": {"warm_up": 0, "source_gap": 0},
            "by_threshold": [],
            "weeks": [],
        }
        status = "NOT_VERIFIED"
    else:
        evidence = margin_overheat.threshold_trigger_evidence(series["ratios"])
        if evidence["evaluable_week_count"] == 0:
            status = "NOT_VERIFIED"
            not_verified.append(
                "no week carries a full live-caliber rolling window to be scored against"
            )
        elif evidence["unavailable_week_count"]:
            status = "PARTIAL"
            not_verified.append(
                "weeks whose rolling three-year window reaches before the fetched history "
                "are reported as warm-up, not scored"
            )
        else:
            status = "COMPLETE"

    return {
        "schema_name": SCHEMA_NAME,
        "schema_version": SCHEMA_VERSION,
        "as_of": str(as_of),
        # Two different windows live in this artifact and they must never be
        # reported as one: the LIVE window (rolling three years) is what
        # current_percentile is taken over, the EVIDENCE window (six years) is
        # only the history the weekly table is scored across.  Mixing them made
        # the top level state a six-year span with 726/1454 sessions and
        # coverage_complete=true at the same time -- a reader either computes a
        # bogus 50% coverage or believes the percentile spans six years.
        "window_start": facts["window_start"],
        "window_end": facts["window_end"],
        "requested_session_count": facts["requested_session_count"],
        "observed_session_count": facts["observed_session_count"],
        "coverage_complete": facts["coverage_complete"],
        "evidence_window": {
            "start": sessions[-1] if sessions else None,
            "end": sessions[0] if sessions else None,
            "session_count": len(sessions),
        },
        "exchange_observed_session_count": series["numerator"]["exchange_coverage"],
        "bse_effective_from": series["numerator"]["bse_effective_from"],
        "current_percentile": facts["percentile"],
        "current_ratio": facts["ratio"],
        "current_balance_yuan": facts["balance_yuan"],
        "current_denominator_float_mv_yuan": facts["denominator_float_mv_yuan"],
        "status": status,
        "comparison_only": True,
        "production_effect_enabled": False,
        "source_binding": {
            "margin": "tushare:pro.margin.rzye",
            "margin_unit": margin_overheat.MARGIN_BALANCE_UNIT,
            "exchanges": list(margin_overheat.MARGIN_OVERHEAT_EXCHANGES),
            "exchange_set_rule": "date_effective_bse_from_first_published_session",
            "denominator": (
                f"tushare:index_dailybasic.{margin_overheat.MARGIN_RATIO_DENOMINATOR_INDEX}"
                f".{margin_overheat.MARGIN_RATIO_DENOMINATOR_FIELD}"
            ),
            "denominator_unit": "CNY",
            "calendar_basis": f"tushare:trade_cal.{CALENDAR_EXCHANGE}.cal_date",
            "reconciliation": "engine.a_short_market_history.reconcile_dated_series",
            "predicate": "engine.a_short_margin_overheat.should_reduce_new_exposure",
            "window_years": margin_overheat.MARGIN_OVERHEAT_WINDOW_YEARS,
            "evidence_history_years": margin_overheat.MARGIN_OVERHEAT_EVIDENCE_HISTORY_YEARS,
        },
        "threshold_evidence": evidence,
        "not_verified": not_verified,
    }


def run_probe(
    pro_client: Any,
    *,
    as_of: str = PROBE_DATE,
    raw_root: Path = RAW_ROOT,
    call_budget: int = CALL_BUDGET,
) -> dict[str, Any]:
    """Run the bounded calendar + margin + denominator reads for the evidence."""
    raw_root = _assert_raw_root(Path(raw_root))
    window_start = margin_overheat.window_start(
        as_of, margin_overheat.MARGIN_OVERHEAT_EVIDENCE_HISTORY_YEARS
    )
    calls = 0
    results: list[dict[str, Any]] = []
    payloads: dict[str, Any] = {}
    raw_payloads: dict[str, Any] = {}

    def _call(label: str, endpoint: str, parameters: dict[str, Any]) -> None:
        nonlocal calls
        record = {"label": label, "endpoint": endpoint}
        if calls >= call_budget:
            record["status"] = "budget_exhausted"
            results.append(record)
            return
        method = getattr(pro_client, endpoint, None)
        if not callable(method):
            record["status"] = "sdk_method_missing"
            results.append(record)
            return
        calls += 1
        try:
            payload = method(**parameters)
        except Exception as exc:  # No vendor message, URL, body or token reaches the summary.
            record.update({"status": "error", "error_class": type(exc).__name__})
        else:
            payloads[label] = payload
            raw_payloads[label] = _raw_json_value(payload)
            record["status"] = "ok"
        results.append(record)

    _call(
        "trade_cal",
        "trade_cal",
        {
            "exchange": CALENDAR_EXCHANGE,
            "start_date": window_start,
            "end_date": str(as_of),
            "is_open": "1",
            "fields": "cal_date",
        },
    )
    sessions = _calendar_sessions(
        payloads.get("trade_cal"), start=window_start, end=str(as_of)
    )
    segments = margin_overheat.fetch_segments(sessions)
    budget_abort_message = None
    if 2 * len(segments) > call_budget - calls:
        # Refuse to publish a partial window rather than spend past the budget.
        # The calendar stays: it was really observed, and blanking it made the
        # summary blame a missing calendar and a failed call when in truth no
        # margin call was ever attempted (review Optional O-4).  Both legs
        # (margin + denominator) must fit, or neither is fetched.
        budget_abort_message = (
            f"the margin and denominator windows need {2 * len(segments)} segment call(s) "
            f"but only {call_budget - calls} remain in the reviewed budget, so no "
            "data call was attempted"
        )
        results.append({
            "label": "margin_window",
            "endpoint": "margin",
            "status": "aborted_call_budget_would_be_exceeded",
        })
        segments = []
    margin_rows: list[dict[str, Any]] = []
    denominator_rows: list[dict[str, Any]] = []
    segment_manifest: list[dict[str, Any]] = []
    truncated_segments = 0

    def _fetch_leg(leg: str, endpoint: str, parameters: dict[str, Any], sink: list) -> None:
        nonlocal truncated_segments
        for index, segment in enumerate(segments, start=1):
            label = f"{leg}_part_{index:03d}"
            _call(label, endpoint, {
                **parameters,
                "start_date": segment[-1],
                "end_date": segment[0],
            })
            rows = _payload_records(payloads.get(label))
            row_count = len(rows) if rows is not None else 0
            truncated = rows is not None and row_count >= margin_overheat.MARGIN_PROVIDER_ROW_CAP
            if truncated:
                truncated_segments += 1
            if rows is not None:
                sink.extend(rows)
            segment_manifest.append({
                "leg": leg,
                "segment": index,
                "start_date": segment[-1],
                "end_date": segment[0],
                "requested_session_count": len(segment),
                "observed_row_count": row_count,
                "truncated": truncated,
                "status": "ok" if rows is not None else "unavailable",
            })

    _fetch_leg("margin", "margin", {"fields": "trade_date,exchange_id,rzye"}, margin_rows)
    _fetch_leg(
        "denominator", "index_dailybasic",
        {
            "ts_code": margin_overheat.MARGIN_RATIO_DENOMINATOR_INDEX,
            "fields": f"ts_code,trade_date,{margin_overheat.MARGIN_RATIO_DENOMINATOR_FIELD}",
        },
        denominator_rows,
    )

    for label, payload in raw_payloads.items():
        _write_json(raw_root / f"{label}.json", _nonfinite_safe(payload))
    if margin_rows:
        _write_json(raw_root / "margin_window.json",
                    _nonfinite_safe({"kind": "segmented_rows", "rows": margin_rows}))
    if denominator_rows:
        _write_json(raw_root / "denominator_window.json",
                    _nonfinite_safe({"kind": "segmented_rows", "rows": denominator_rows}))
    _write_json(raw_root / "margin_fetch_manifest.json", {
        "row_cap": margin_overheat.MARGIN_PROVIDER_ROW_CAP,
        "segment_max_sessions": margin_overheat.MARGIN_FETCH_SEGMENT_MAX_SESSIONS,
        "segments": segment_manifest,
        "truncated_segment_count": truncated_segments,
    })

    summary = build_evidence(
        margin_rows or None, denominator_rows or None, sessions, as_of=as_of
    )
    if budget_abort_message is not None:
        summary["not_verified"].append(budget_abort_message)
    # The budget-abort marker is a decision not to call, never a call that
    # failed; counting it under "did not return a usable payload" misreported
    # the abort as a provider fault (review Optional O-4).
    failed = [
        item for item in results
        if item.get("status") not in {"ok", "aborted_call_budget_would_be_exceeded"}
    ]
    if failed:
        summary["not_verified"].append(
            f"{len(failed)} authorized provider call(s) did not return a usable payload"
        )
    if (failed or budget_abort_message is not None) and summary["status"] == "COMPLETE":
        summary["status"] = "PARTIAL"
    if truncated_segments:
        summary["not_verified"].append(
            f"{truncated_segments} margin segment(s) came back at the vendor row cap and are treated as truncated"
        )
    summary["margin_fetch"] = {
        "row_cap": margin_overheat.MARGIN_PROVIDER_ROW_CAP,
        "segment_max_sessions": margin_overheat.MARGIN_FETCH_SEGMENT_MAX_SESSIONS,
        "segment_count": len(segment_manifest),
        "truncated_segment_count": truncated_segments,
        "truncated": bool(truncated_segments),
        "status": "not_attempted" if not segments else ("partial" if failed or truncated_segments else "complete"),
    }
    summary["execution"] = {
        "call_budget": int(call_budget),
        "calls_made": calls,
        "within_budget": calls <= int(call_budget),
        "successful_calls": sum(item.get("status") == "ok" for item in results),
        "failed_or_skipped_calls": len(failed),
        "status": "completed" if not failed and calls <= int(call_budget) else "completed_with_errors",
        "tushare_version": SUPPORTED_TUSHARE_VERSION,
    }
    summary["storage"] = {
        "raw_payload_root": raw_root.relative_to(PROJECT_ROOT).as_posix(),
        "raw_payload_root_gitignored": True,
        "tracked_summary_contains_raw_rows": False,
        "tracked_summary_contains_request_urls": False,
        "tracked_summary_contains_secret": False,
    }
    return summary


def replay_raw(
    *,
    as_of: str = PROBE_DATE,
    raw_root: Path = RAW_ROOT,
    existing_summary: Path = SUMMARY_PATH,
) -> dict[str, Any]:
    """Rebuild the evidence from an already acquired raw window, with no new call."""
    raw_root = _assert_raw_root(Path(raw_root))
    calendar_path = raw_root / "trade_cal.json"
    margin_path = raw_root / "margin_window.json"
    denominator_path = raw_root / "denominator_window.json"
    window_start = margin_overheat.window_start(
        as_of, margin_overheat.MARGIN_OVERHEAT_EVIDENCE_HISTORY_YEARS
    )
    sessions = _calendar_sessions(
        _load_raw_rows(calendar_path) if calendar_path.is_file() else None,
        start=window_start,
        end=str(as_of),
    )
    margin_rows = _load_raw_rows(margin_path) if margin_path.is_file() else None
    denominator_rows = _load_raw_rows(denominator_path) if denominator_path.is_file() else None
    summary = build_evidence(margin_rows, denominator_rows, sessions, as_of=as_of)
    del existing_summary  # kept for CLI compatibility; a replay copies nothing from it
    # A replayed summary must be distinguishable from a live fetch.  The old
    # form copied the prior summary's execution/margin_fetch verbatim, so a
    # rebuilt artifact still claimed four successful provider calls and a real
    # tushare version (review Optional O-1).  The fetch-time facts live in the
    # raw manifest; the execution block always carries the replay marker.
    manifest_path = raw_root / "margin_fetch_manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        manifest = {}
    segments = manifest.get("segments") or []
    truncated_count = int(manifest.get("truncated_segment_count") or 0)
    summary["margin_fetch"] = {
        "row_cap": int(manifest.get("row_cap") or margin_overheat.MARGIN_PROVIDER_ROW_CAP),
        "segment_max_sessions": int(
            manifest.get("segment_max_sessions")
            or margin_overheat.MARGIN_FETCH_SEGMENT_MAX_SESSIONS
        ),
        "segment_count": len(segments),
        "truncated_segment_count": truncated_count,
        "truncated": bool(truncated_count),
        "status": "not_attempted" if not segments else ("partial" if truncated_count else "complete"),
    }
    summary["execution"] = {
        "call_budget": CALL_BUDGET,
        "calls_made": 0,
        "within_budget": True,
        "successful_calls": 0,
        "failed_or_skipped_calls": 0,
        "status": "completed_with_errors",
        "tushare_version": "replayed_without_new_call",
    }
    summary["not_verified"].append(
        "this artifact was rebuilt from persisted raw payloads without any new provider call; "
        "the raw files are gitignored and mutable, so their lineage is only as strong as the raw root"
    )
    if summary["status"] == "COMPLETE":
        summary["status"] = "PARTIAL"
    summary["storage"] = {
        "raw_payload_root": raw_root.relative_to(PROJECT_ROOT).as_posix(),
        "raw_payload_root_gitignored": True,
        "tracked_summary_contains_raw_rows": False,
        "tracked_summary_contains_request_urls": False,
        "tracked_summary_contains_secret": False,
    }
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Bounded A-short margin-overheat percentile evidence (queue row 19)")
    parser.add_argument("--as-of", default=PROBE_DATE)
    parser.add_argument("--raw-root", type=Path, default=RAW_ROOT)
    parser.add_argument("--out", type=Path, default=SUMMARY_PATH)
    parser.add_argument(
        "--replay-raw",
        action="store_true",
        help="rebuild the evidence from an existing raw window without provider calls",
    )
    args = parser.parse_args(argv)

    out = _assert_not_production_output(args.out)
    if args.replay_raw:
        summary = replay_raw(as_of=args.as_of, raw_root=args.raw_root, existing_summary=args.out)
        mode = "replayed"
    else:
        token = os.environ.get("TUSHARE_TOKEN")
        if not token:
            raise RuntimeError("TUSHARE_TOKEN is required for the margin overheat evidence run")
        pro = init_tushare_pro(token)
        summary = run_probe(pro, as_of=args.as_of, raw_root=args.raw_root)
        mode = summary["execution"]["status"]
    _write_json(out, summary)
    print(
        f"[a-short margin overheat] {mode} "
        f"calls={summary['execution']['calls_made']}/{CALL_BUDGET} "
        f"sessions={summary['observed_session_count']}/{summary['requested_session_count']} "
        f"percentile={summary['current_percentile']} "
        f"weeks={summary['threshold_evidence']['evaluable_week_count']} -> {out}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

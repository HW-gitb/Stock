"""Bounded provider runner for A-short northbound lookback row 22b.

The runner makes only the two authorized historical reads
(``moneyflow_hsgt`` and ``index_daily``), writes their raw responses below the
gitignored ``provider_samples/`` root, and writes a tracked counts-only
comparison artifact.  It never imports or starts the weekly production
pipeline and never changes ``production_effect_enabled``.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from engine.a_short_northbound_lookback import (
    _canonical_date,
    _normalise_rows,
    build_lookback_summary,
    three_year_lookback_start,
)
from engine.a_short_tushare_client import SUPPORTED_TUSHARE_VERSION, init_tushare_pro


PROBE_DATE = "20260804"
CALL_BUDGET = 6
PROVIDER_ROW_CAP = 300
FLOW_SEGMENT_MAX_SESSIONS = 250
RAW_ROOT = Path(f"provider_samples/a_short_northbound_lookback_{PROBE_DATE}")
SUMMARY_PATH = Path(
    "research/results/a_short/northbound_market_silence_lookback_summary.json"
)
INDEX_CODE = "000300.SH"


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
        raise ValueError("northbound lookback output cannot be written to result/a_short")
    return resolved


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str, allow_nan=False),
        encoding="utf-8",
    )


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
    """Return provider rows for segmentation/raw assembly, or fail closed."""
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


def _index_session_dates(payload: Any, *, lookback_start: str, as_of: str) -> tuple[str, ...]:
    rows = _normalise_rows(
        payload,
        value_key="close",
        expected_ts_code=INDEX_CODE,
    )
    if rows is None:
        return ()
    return tuple(
        sorted(
            {
                row["trade_date"]
                for row in rows
                if lookback_start <= row["trade_date"] <= as_of
            },
            reverse=True,
        )
    )


def _flow_segments(
    index_dates: tuple[str, ...],
    *,
    max_sessions: int = FLOW_SEGMENT_MAX_SESSIONS,
) -> list[tuple[str, ...]]:
    if max_sessions <= 0:
        raise ValueError("max_sessions must be positive")
    return [
        index_dates[offset:offset + max_sessions]
        for offset in range(0, len(index_dates), max_sessions)
    ]


def run_probe(
    pro_client: Any,
    *,
    as_of: str = PROBE_DATE,
    raw_root: Path = RAW_ROOT,
    call_budget: int = CALL_BUDGET,
) -> dict[str, Any]:
    """Run the bounded two-source read and return a safe tracked summary."""
    raw_root = _assert_raw_root(Path(raw_root))
    lookback_start = three_year_lookback_start(as_of)
    calls = 0
    results: list[dict[str, Any]] = []
    payloads: dict[str, Any] = {}
    raw_payloads: dict[str, Any] = {}
    flow_rows: list[dict[str, Any]] = []
    truncated_dates: set[str] = set()
    segment_count = 0
    truncated_segment_count = 0
    requested_session_count = 0
    observed_session_dates: set[str] = set()
    segment_manifest: list[dict[str, Any]] = []

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
        except Exception as exc:  # Do not copy vendor messages/URLs into tracked output.
            record.update({"status": "error", "error_class": type(exc).__name__})
        else:
            payloads[label] = payload
            raw_payloads[label] = _raw_json_value(payload)
            record["status"] = "ok"
        results.append(record)

    _call(
        "csi300_index_daily",
        "index_daily",
        {
            "ts_code": INDEX_CODE,
            "start_date": lookback_start,
            "end_date": as_of,
            "fields": "ts_code,trade_date,close",
        },
    )

    index_dates = _index_session_dates(
        payloads.get("csi300_index_daily"),
        lookback_start=lookback_start,
        as_of=as_of,
    )
    segments = _flow_segments(index_dates)
    segment_count = len(segments)
    if not segments:
        results.append({
            "label": "northbound_moneyflow_hsgt",
            "endpoint": "moneyflow_hsgt",
            "status": "not_attempted_no_usable_index_calendar",
        })
    for segment_index, requested_dates in enumerate(segments, start=1):
        requested_session_count += len(requested_dates)
        label = f"northbound_moneyflow_hsgt_part_{segment_index:03d}"
        _call(
            label,
            "moneyflow_hsgt",
            {
                "start_date": requested_dates[-1],
                "end_date": requested_dates[0],
                "fields": "trade_date,north_money",
            },
        )
        payload = payloads.get(label)
        rows = _payload_records(payload)
        row_count = len(rows) if rows is not None else 0
        requested_set = set(requested_dates)
        observed_dates = {
            canonical
            for row in (rows or [])
            if (canonical := _canonical_date(row.get("trade_date"))) is not None
        }
        observed_session_dates.update(observed_dates)
        truncated = bool(
            rows is not None
            and (
                row_count >= PROVIDER_ROW_CAP
                or row_count > len(requested_dates)
                or not observed_dates.issubset(requested_set)
            )
        )
        if truncated:
            truncated_segment_count += 1
            truncated_dates.update(requested_dates)
        if rows is not None:
            flow_rows.extend(rows)
        segment_manifest.append({
            "segment": segment_index,
            "start_date": requested_dates[-1],
            "end_date": requested_dates[0],
            "requested_session_count": len(requested_dates),
            "observed_row_count": row_count,
            "truncated": truncated,
            "status": "ok" if payload is not None else "unavailable",
        })

    for label, payload in raw_payloads.items():
        _write_json(raw_root / f"{label}.json", payload)
    if flow_rows:
        _write_json(
            raw_root / "northbound_moneyflow_hsgt.json",
            {"kind": "segmented_rows", "rows": flow_rows},
        )
    _write_json(
        raw_root / "northbound_moneyflow_hsgt_fetch_manifest.json",
        {
            "row_cap": PROVIDER_ROW_CAP,
            "segment_max_sessions": FLOW_SEGMENT_MAX_SESSIONS,
            "segments": segment_manifest,
            "truncated_segment_count": truncated_segment_count,
        },
    )

    summary = build_lookback_summary(
        flow_rows or None,
        payloads.get("csi300_index_daily"),
        as_of=as_of,
        source_artifact_count=sum(
            payloads.get(label) is not None
            for label in ("csi300_index_daily",)
        ) + int(bool(flow_rows)),
        northbound_fetch_truncated_dates=truncated_dates,
    )
    failed = [item for item in results if item.get("status") != "ok"]
    if failed:
        summary["not_verified"].append(
            f"{len(failed)} authorized provider call(s) did not return a usable payload"
        )
        if summary["status"] == "COMPLETE":
            summary["status"] = "PARTIAL"
    fetch_status = (
        "not_attempted"
        if not segments
        else "partial"
        if failed or truncated_segment_count
        else "complete"
    )
    summary["northbound_fetch"] = {
        "row_cap": PROVIDER_ROW_CAP,
        "segment_max_sessions": FLOW_SEGMENT_MAX_SESSIONS,
        "segment_count": segment_count,
        "requested_session_count": requested_session_count,
        "observed_session_count": len(observed_session_dates),
        "truncated_segment_count": truncated_segment_count,
        "truncated": bool(truncated_segment_count),
        "status": fetch_status,
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
    raw_root: Path = RAW_ROOT,
    existing_summary: Path = SUMMARY_PATH,
) -> dict[str, Any]:
    """Rebuild counts from an already acquired raw pair without provider calls."""
    raw_root = _assert_raw_root(Path(raw_root))
    flow_path = raw_root / "northbound_moneyflow_hsgt.json"
    index_path = raw_root / "csi300_index_daily.json"
    flow = _load_raw_rows(flow_path) if flow_path.is_file() else None
    index = _load_raw_rows(index_path) if index_path.is_file() else None
    index_dates = _index_session_dates(
        index,
        lookback_start=three_year_lookback_start(PROBE_DATE),
        as_of=PROBE_DATE,
    )
    flow_records = _payload_records(flow)
    inferred_truncated_dates: set[str] = set()
    if (
        flow_records is not None
        and len(flow_records) >= PROVIDER_ROW_CAP
        and len(index_dates) > len({row.get("trade_date") for row in flow_records})
    ):
        inferred_truncated_dates.update(index_dates)
    prior = _project_path(existing_summary)
    prior_summary = json.loads(prior.read_text(encoding="utf-8")) if prior.is_file() else None
    summary = build_lookback_summary(
        flow,
        index,
        as_of=PROBE_DATE,
        source_artifact_count=sum(path.is_file() for path in (flow_path, index_path)),
        northbound_fetch_truncated_dates=inferred_truncated_dates,
    )
    summary["execution"] = (prior_summary or {}).get(
        "execution",
        {
            "call_budget": CALL_BUDGET,
            "calls_made": 0,
            "within_budget": True,
            "successful_calls": 0,
            "failed_or_skipped_calls": 0,
            "status": "completed_with_errors",
            "tushare_version": "replayed_without_new_call",
        },
    )
    summary["storage"] = {
        "raw_payload_root": raw_root.relative_to(PROJECT_ROOT).as_posix(),
        "raw_payload_root_gitignored": True,
        "tracked_summary_contains_raw_rows": False,
        "tracked_summary_contains_request_urls": False,
        "tracked_summary_contains_secret": False,
    }
    summary["northbound_fetch"] = {
        "row_cap": PROVIDER_ROW_CAP,
        "segment_max_sessions": FLOW_SEGMENT_MAX_SESSIONS,
        "segment_count": 0,
        "requested_session_count": len(index_dates),
        "observed_session_count": len({
            canonical
            for row in (flow_records or [])
            if (canonical := _canonical_date(row.get("trade_date"))) is not None
        }),
        "truncated_segment_count": int(bool(inferred_truncated_dates)),
        "truncated": bool(inferred_truncated_dates),
        "status": "partial" if inferred_truncated_dates else "not_supplied",
    }
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Bounded A-short northbound lookback (queue row 22b)")
    parser.add_argument("--as-of", default=PROBE_DATE)
    parser.add_argument("--raw-root", type=Path, default=RAW_ROOT)
    parser.add_argument("--out", type=Path, default=SUMMARY_PATH)
    parser.add_argument(
        "--replay-raw",
        action="store_true",
        help="rebuild the counts-only summary from an existing raw pair without provider calls",
    )
    args = parser.parse_args(argv)

    out = _assert_not_production_output(args.out)
    if args.replay_raw:
        if args.as_of != PROBE_DATE:
            raise ValueError("--replay-raw uses the pinned provider acquisition as_of")
        summary = replay_raw(raw_root=args.raw_root, existing_summary=args.out)
        mode = "replayed"
    else:
        token = os.environ.get("TUSHARE_TOKEN")
        if not token:
            raise RuntimeError("TUSHARE_TOKEN is required for the northbound lookback")
        pro = init_tushare_pro(token)
        summary = run_probe(pro, as_of=args.as_of, raw_root=args.raw_root)
        mode = summary["execution"]["status"]
    _write_json(out, summary)
    print(
        f"[a-short northbound lookback] {mode} "
        f"calls={summary['execution']['calls_made']}/{CALL_BUDGET} "
        f"weeks={summary['lookback_week_count']} eligible={summary['eligible_week_count']} "
        f"triggers={summary['trigger_count']} -> {out}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

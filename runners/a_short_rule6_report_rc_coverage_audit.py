"""Bounded Tushare ``report_rc`` coverage/PIT-shape audit for one A-short pool.

This is an evidence-only runner.  It reads a validated EGS ``analysis_input``
artifact, makes exactly one read per candidate, retains vendor rows only in a
gitignored directory, and writes an aggregate no-ticker summary.  It is not
imported by EGS, weekly, or the Rule6 gate.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from engine.a_short_tushare_client import SUPPORTED_TUSHARE_VERSION, init_tushare_pro
from engine.data.analysis_input_contract import candidate_digest, validate_analysis_input_file


AUDIT_DATE = "20260714"
LOOKBACK_DAYS = 120
MAX_PACED_INTERVAL_SECONDS = 60.0
RAW_ROOT = Path(f"provider_samples/a_short_rule6_report_rc_coverage_audit_{AUDIT_DATE}")
SUMMARY_PATH = Path(f"docs/a_short_rule6_report_rc_coverage_audit_summary_{AUDIT_DATE}.json")


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def _raw_json_value(value: Any) -> Any:
    if isinstance(value, pd.DataFrame):
        return {"kind": "dataframe", "rows": value.to_dict(orient="records")}
    if isinstance(value, pd.Series):
        return {"kind": "series", "values": value.to_dict()}
    if isinstance(value, dict):
        return value
    if isinstance(value, (list, tuple)):
        return list(value)
    return {"kind": type(value).__name__}


def _error_category(exc: Exception) -> str:
    """Classify a provider failure without retaining vendor text or a response body."""
    message = str(exc).casefold()
    if any(marker in message for marker in ("频繁", "频率", "每分钟", "rate limit", "too many", "429")):
        return "rate_limited_or_frequency_cap"
    if any(marker in message for marker in ("权限", "积分", "permission", "entitlement", "access denied")):
        return "permission_or_entitlement"
    if any(marker in message for marker in ("token", "auth", "认证", "鉴权")):
        return "authentication"
    if any(marker in message for marker in ("接口", "api name", "parameter", "参数", "not found")):
        return "endpoint_or_parameter"
    return "provider_or_undetermined"


def _parse_date8(value: Any) -> str | None:
    text = str(value or "")
    try:
        datetime.strptime(text, "%Y%m%d")
    except ValueError:
        return None
    return text


def _audit_report_frame(frame: pd.DataFrame, as_of: str) -> dict[str, int | bool]:
    """Summarize coverage/PIT shape without returning report content or identities."""
    total_rows = int(len(frame))
    columns = {str(column) for column in frame.columns}
    date_values = frame.get("report_date", pd.Series(dtype=object)).tolist()
    parsed_dates = [_parse_date8(value) for value in date_values]
    valid_dates = [value for value in parsed_dates if value is not None]
    as_of_rows = sum(value <= as_of for value in valid_dates)
    future_rows = sum(value > as_of for value in valid_dates)
    invalid_or_missing_dates = total_rows - len(valid_dates)
    org_values = frame.get("org_name", pd.Series(dtype=object)).tolist()
    distinct_orgs = len({str(value).strip() for value in org_values if str(value or "").strip()})

    identity_columns = [column for column in ("report_date", "org_name", "author_name", "report_title", "quarter") if column in columns]
    if identity_columns:
        duplicate_rows = int(frame.duplicated(subset=identity_columns, keep="first").sum())
    else:
        duplicate_rows = 0
    return {
        "response_rows": total_rows,
        "as_of_rows": as_of_rows,
        "future_dated_rows": future_rows,
        "invalid_or_missing_report_date_rows": invalid_or_missing_dates,
        "distinct_org_count": distinct_orgs,
        "duplicate_identity_rows": duplicate_rows,
        "report_date_column_present": "report_date" in columns,
        "org_name_column_present": "org_name" in columns,
    }


def _safe_source_reference(path: Path) -> str:
    parts = path.resolve().parts
    for index, part in enumerate(parts):
        if part.lower() == "result":
            return Path(*parts[index:]).as_posix()
    return path.name


def _window_start(as_of: str) -> str:
    as_of_date = datetime.strptime(as_of, "%Y%m%d").date()
    return (as_of_date - timedelta(days=LOOKBACK_DAYS - 1)).strftime("%Y%m%d")


def run_audit(
    pro_client: Any,
    analysis_input: dict[str, Any],
    raw_root: Path = RAW_ROOT,
    min_interval_seconds: float = 0.0,
    sleep_fn=time.sleep,
) -> dict[str, Any]:
    """Run the one-read-per-candidate audit with an injected Tushare Pro client."""
    as_of = str(analysis_input["trade_date"])
    candidates = analysis_input.get("candidates") or []
    symbols = [str(candidate.get("ts_code") or "") for candidate in candidates]
    if not symbols or any(not symbol for symbol in symbols) or len(set(symbols)) != len(symbols):
        raise ValueError("analysis_input candidates must contain unique non-empty ts_code values")
    if not isinstance(min_interval_seconds, (int, float)) or not 0 <= min_interval_seconds <= MAX_PACED_INTERVAL_SECONDS:
        raise ValueError(f"min_interval_seconds must be within [0, {MAX_PACED_INTERVAL_SECONDS}]")

    start_date = _window_start(as_of)
    raw_root = Path(raw_root)
    per_candidate_metrics: list[dict[str, Any]] = []
    error_categories: dict[str, int] = {}
    completed_calls = 0
    error_calls = 0
    for index, symbol in enumerate(symbols):
        if index and min_interval_seconds:
            sleep_fn(min_interval_seconds)
        audit_record: dict[str, Any] = {"ts_code": symbol, "request": {"start_date": start_date, "end_date": as_of}}
        try:
            frame = pro_client.report_rc(ts_code=symbol, start_date=start_date, end_date=as_of)
            if not isinstance(frame, pd.DataFrame):
                raise TypeError("report_rc did not return a DataFrame")
            metrics = _audit_report_frame(frame, as_of)
            audit_record.update({"status": "ok", "metrics": metrics, "raw_response": _raw_json_value(frame)})
            per_candidate_metrics.append(metrics)
            completed_calls += 1
        except Exception as exc:  # Keep provider text/URLs/tokens out of tracked state.
            error_category = _error_category(exc)
            audit_record.update(
                {"status": "error", "error_class": type(exc).__name__, "error_category": error_category}
            )
            error_categories[error_category] = error_categories.get(error_category, 0) + 1
            error_calls += 1
        _write_json(raw_root / f"{symbol.replace('.', '_')}.json", audit_record)

    response_rows = [int(metrics["response_rows"]) for metrics in per_candidate_metrics]
    as_of_rows = [int(metrics["as_of_rows"]) for metrics in per_candidate_metrics]
    future_rows = [int(metrics["future_dated_rows"]) for metrics in per_candidate_metrics]
    invalid_dates = [int(metrics["invalid_or_missing_report_date_rows"]) for metrics in per_candidate_metrics]
    distinct_orgs = [int(metrics["distinct_org_count"]) for metrics in per_candidate_metrics]
    duplicates = [int(metrics["duplicate_identity_rows"]) for metrics in per_candidate_metrics]

    return {
        "schema_name": "a_short_rule6_report_rc_coverage_audit_summary",
        "schema_version": "1.0.0",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "scope": {
            "market": "A-share",
            "purpose": "rule6_good_data_bad_reaction_report_rc_coverage_and_pit_shape_audit_only",
            "tushare_is_wired_into_rule6": False,
            "egs_or_weekly_behavior_changed": False,
            "production_or_ship_gate_claimed": False,
            "broker_or_order_action": False,
        },
        "candidate_pool": {
            "trade_date": as_of,
            "candidate_count": len(symbols),
            "candidate_digest": candidate_digest(candidates),
            "report_window_start": start_date,
            "report_window_end": as_of,
            "pinned_tushare_version": SUPPORTED_TUSHARE_VERSION,
        },
        "execution": {
            "status": "completed" if error_calls == 0 else "completed_with_errors",
            "planned_report_rc_reads": len(symbols),
            "completed_report_rc_reads": completed_calls,
            "error_report_rc_reads": error_calls,
            "min_interval_seconds": min_interval_seconds,
            "error_category_counts": error_categories,
        },
        "coverage": {
            "candidates_with_nonempty_response": sum(rows > 0 for rows in response_rows),
            "candidates_with_as_of_rows": sum(rows > 0 for rows in as_of_rows),
            "candidates_with_multiple_orgs": sum(count > 1 for count in distinct_orgs),
            "total_response_rows": sum(response_rows),
            "total_as_of_rows": sum(as_of_rows),
            "total_future_dated_rows": sum(future_rows),
            "total_invalid_or_missing_report_date_rows": sum(invalid_dates),
            "total_duplicate_identity_rows": sum(duplicates),
        },
        "pit_assessment": {
            "cutoff_field": "report_date",
            "all_successful_responses_have_report_date_column": all(
                bool(metrics["report_date_column_present"]) for metrics in per_candidate_metrics
            ),
            "all_successful_response_rows_are_on_or_before_trade_date": sum(future_rows) == 0,
            "provider_observed_at_or_ingested_at_present": False,
            "historical_consensus_reconstruction_proven": False,
            "rule6_wiring_authorized": False,
            "reason": "report_date supports only a basic cutoff; provider observed-time, consensus methodology, and event-reaction alignment are not established by this audit",
        },
        "storage": {
            "raw_payload_root": RAW_ROOT.as_posix(),
            "raw_payload_root_gitignored": True,
            "tracked_summary_contains_candidate_tickers": False,
            "tracked_summary_contains_raw_rows": False,
            "tracked_summary_contains_request_urls": False,
            "tracked_summary_contains_secret": False,
        },
        "decision": {
            "rule6_d_tier_status_remains_not_applicable": True,
            "downstream_rule6_wiring_authorized": False,
            "separate_review_required_before_any_future_use": True,
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="A-short candidate-pool Tushare report_rc coverage/PIT-shape audit")
    parser.add_argument("--analysis-input", type=Path, required=True)
    parser.add_argument("--raw-root", type=Path, default=RAW_ROOT)
    parser.add_argument("--out", type=Path, default=SUMMARY_PATH)
    parser.add_argument("--min-interval-seconds", type=float, default=0.0)
    args = parser.parse_args(argv)

    analysis_input = validate_analysis_input_file(args.analysis_input, label="report_rc coverage audit analysis_input")
    token = os.environ.get("TUSHARE_TOKEN")
    if not token:
        raise RuntimeError("TUSHARE_TOKEN is required for the report_rc coverage audit")
    summary = run_audit(
        init_tushare_pro(token), analysis_input, args.raw_root, args.min_interval_seconds
    )
    summary["candidate_pool"]["analysis_input_reference"] = _safe_source_reference(args.analysis_input)
    summary["candidate_pool"]["analysis_input_sha256"] = hashlib.sha256(args.analysis_input.read_bytes()).hexdigest()
    _write_json(args.out, summary)
    print(f"[a-short Rule6 report_rc coverage audit] {summary['execution']['status']} -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

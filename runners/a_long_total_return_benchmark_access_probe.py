import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runners import a_long_tushare_route_validation_packet as route_base


SUMMARY_PATH = ROOT / "docs" / "a_long_total_return_benchmark_access_probe_summary_20260606.json"
SCHEMA_PATH = ROOT / "schemas" / "a_long_total_return_benchmark_access_probe_summary.schema.json"
START_DATE = "20200102"
END_DATE = "20200110"
FIELDS = "ts_code,trade_date,open,close"
PRICE_INDEX_CONTROLS = {
    "CSI300": "000300.SH",
    "CSI1000": "000852.SH",
}
TOTAL_RETURN_CANDIDATES = {
    "CSI300": ["H00300.CSI", "H000300.CSI", "000300.CSI"],
    "CSI1000": ["H00852.CSI", "H000852.CSI", "000852.CSI"],
}
MAX_TOTAL_CALLS = 8


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Probe existing-account Tushare access to CSI300/CSI1000 total-return benchmark index_daily series. "
            "This writes only a no-secret tracked summary, no raw rows, no signal search."
        )
    )
    parser.add_argument("--summary-path", type=Path, default=SUMMARY_PATH)
    parser.add_argument("--generated-at", help="Optional deterministic timestamp for tests.")
    parser.add_argument("--confirm-user-approved-route-a", action="store_true")
    return parser.parse_args(argv)


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def validate_json(schema_path: Path, payload: dict[str, Any]) -> None:
    try:
        from jsonschema import Draft7Validator
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "jsonschema is required for A-long schema-gated benchmark access probes; "
            "install project requirements before running this producer."
        ) from exc
    schema = read_json(schema_path)
    errors = sorted(Draft7Validator(schema).iter_errors(payload), key=lambda error: list(error.path))
    if errors:
        joined = "; ".join(f"{list(error.path)}: {error.message}" for error in errors[:8])
        raise ValueError(f"{schema_path} validation failed: {joined}")


def require_user_approval(confirm_user_approved_route_a: bool) -> None:
    if not confirm_user_approved_route_a:
        raise RuntimeError("total-return benchmark probe requires --confirm-user-approved-route-a")


def probe_plan() -> list[dict[str, str]]:
    calls: list[dict[str, str]] = []
    for label, code in PRICE_INDEX_CONTROLS.items():
        calls.append({"benchmark_label": label, "candidate_role": "price_index_control", "ts_code": code})
    for label, codes in TOTAL_RETURN_CANDIDATES.items():
        for code in codes:
            calls.append({"benchmark_label": label, "candidate_role": "total_return_candidate", "ts_code": code})
    if len(calls) != MAX_TOTAL_CALLS:
        raise ValueError("total-return benchmark probe call plan drifted")
    return calls


def non_null_count(records: list[dict[str, Any]], field: str) -> int:
    return sum(1 for row in records if row.get(field) not in (None, ""))


def probe_one(pro: Any, call: dict[str, str]) -> dict[str, Any]:
    try:
        value = pro.index_daily(ts_code=call["ts_code"], start_date=START_DATE, end_date=END_DATE, fields=FIELDS)
        columns, row_count, records = route_base.normalize_records(value)
        clean_records = [row for row in records if isinstance(row, dict)]
        open_count = non_null_count(clean_records, "open")
        close_count = non_null_count(clean_records, "close")
        status = "success" if row_count and row_count > 0 else "empty"
        same_anchor_available = bool(row_count and row_count > 0 and open_count == row_count and close_count == row_count)
        close_only_tr = (
            call["candidate_role"] == "total_return_candidate"
            and bool(row_count and row_count > 0)
            and open_count == 0
            and close_count == row_count
        )
        return {
            **call,
            "call_status": status,
            "row_count": row_count,
            "columns": columns,
            "open_non_null_count": open_count,
            "close_non_null_count": close_count,
            "same_anchor_open_close_available": same_anchor_available,
            "close_only_total_return_candidate": close_only_tr,
            "tracked_summary_contains_raw_rows": False,
            "error_class": None,
            "error_message_redacted": None,
        }
    except Exception as exc:
        return {
            **call,
            "call_status": "error",
            "row_count": None,
            "columns": [],
            "open_non_null_count": 0,
            "close_non_null_count": 0,
            "same_anchor_open_close_available": False,
            "close_only_total_return_candidate": False,
            "tracked_summary_contains_raw_rows": False,
            "error_class": type(exc).__name__,
            "error_message_redacted": route_base.redact_error(exc),
        }


def selected_codes_if_ready(results: list[dict[str, Any]]) -> dict[str, str | None]:
    out: dict[str, str | None] = {"CSI300": None, "CSI1000": None}
    for label, preferred_codes in TOTAL_RETURN_CANDIDATES.items():
        for code in preferred_codes:
            item = next((row for row in results if row["benchmark_label"] == label and row["ts_code"] == code), None)
            if item and item.get("same_anchor_open_close_available") is True:
                out[label] = code
                break
    return out


def control_price_index_probe_passed(results: list[dict[str, Any]]) -> bool:
    return all(
        item.get("same_anchor_open_close_available") is True
        for item in results
        if item.get("candidate_role") == "price_index_control"
    )


def build_summary(*, results: list[dict[str, Any]], generated_at: str) -> dict[str, Any]:
    selected = selected_codes_if_ready(results)
    ready = all(selected.values())
    status = (
        "passed_total_return_same_anchor_open_available"
        if ready
        else "blocked_total_return_same_anchor_open_unavailable"
    )
    plain = (
        "Total-return benchmark open/close data is available for CSI300 and CSI1000."
        if ready
        else "Total-return benchmark close data exists for the preferred CSI series, but open is missing; A-long cannot run valid same-anchor total-vs-total excess now."
    )
    next_action = (
        "Create the reviewed 2018-2025 total-return benchmark materialization packet before running signal search."
        if ready
        else "Stop A-long signal search. Choose a reviewed alternative source for total-return benchmark open data, or approve a separate derivation policy before any rerun."
    )
    return {
        "schema_name": "a_long_total_return_benchmark_access_probe_summary",
        "schema_version": "1.0.0",
        "generated_at": generated_at,
        "artifact_id": "a_long_total_return_benchmark_access_probe_summary_20260606",
        "scope": {
            "phase": "7a_alpha_validation",
            "purpose": "a_long_total_return_benchmark_access_probe",
            "lane_id": "a_long",
            "market": "A-share",
            "research_only": True,
            "provider_family": "tushare_existing_account",
            "existing_account_only": True,
            "tushare_calls_executed": True,
            "provider_expansion_allowed": False,
            "paid_tier_change_allowed": False,
            "raw_payloads_written": False,
            "tracked_summary_contains_raw_rows": False,
            "tracked_summary_contains_secret": False,
            "signal_search_executed": False,
            "alpha_backtest_executed": False,
            "production_use_allowed": False,
            "ship_gate_claim_allowed": False,
            "full_size_manual_use_allowed": False,
            "broker_or_order_automation_allowed": False,
        },
        "probe_design": {
            "start_date": START_DATE,
            "end_date": END_DATE,
            "required_basis": "benchmark_total_return_index_next_trading_day_open_to_same_exit_close",
            "required_fields": ["ts_code", "trade_date", "open", "close"],
            "control_price_indices": dict(PRICE_INDEX_CONTROLS),
            "total_return_candidates": {key: list(value) for key, value in TOTAL_RETURN_CANDIDATES.items()},
            "max_total_calls": MAX_TOTAL_CALLS,
        },
        "direct_probes": results,
        "decision": {
            "benchmark_access_status": status,
            "control_price_index_probe_passed": control_price_index_probe_passed(results),
            "selected_total_return_codes": selected,
            "signal_search_may_execute": False,
            "runner_benchmark_switch_allowed": False,
            "price_index_fallback_allowed": False,
            "derived_total_return_open_allowed": False,
            "plain_result": plain,
            "next_action": next_action,
        },
        "prohibited_claims": {
            "a_long_alpha_found": False,
            "signal_search_authorized": False,
            "benchmark_total_return_route_ready": False,
            "price_index_benchmark_allowed": False,
            "derived_total_return_open_allowed": False,
            "production_ready": False,
            "ship_gate_evidence": False,
            "full_size_allowed": False,
            "datahub_authorized": False,
            "broker_or_order_automation_authorized": False,
        },
        "limitations": [
            "This summary records endpoint shape counts only; it stores no raw rows, token, or request URL.",
            "A close-only total-return index is not enough for the frozen same-anchor open-to-close benchmark rule.",
            "This does not authorize price-index fallback, derived total-return open construction, signal search, production, ship-gate evidence, or full-size use.",
        ],
    }


def run(
    *,
    summary_path: Path = SUMMARY_PATH,
    generated_at: str | None = None,
    confirm_user_approved_route_a: bool = False,
    pro_factory: Callable[[], Any] = route_base.get_tushare_client,
) -> dict[str, Any]:
    require_user_approval(confirm_user_approved_route_a)
    pro = pro_factory()
    results = [probe_one(pro, call) for call in probe_plan()]
    summary = build_summary(results=results, generated_at=generated_at or iso_now())
    validate_json(SCHEMA_PATH, summary)
    write_json(summary_path, summary)
    return summary


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    summary = run(
        summary_path=args.summary_path,
        generated_at=args.generated_at,
        confirm_user_approved_route_a=args.confirm_user_approved_route_a,
    )
    print(
        json.dumps(
            {
                "benchmark_access_status": summary["decision"]["benchmark_access_status"],
                "plain_result": summary["decision"]["plain_result"],
                "summary_ref": str(args.summary_path).replace("\\", "/"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.data.a_share_board_scope import is_main_board_ts_code
from runners import a_long_tushare_incremental_materialization_packet as thin_runner
from runners import a_long_tushare_route_validation_packet as route_base


PACKET_PATH = ROOT / "docs" / "a_long_large_cap_market_cap_materialization_packet_20260607.json"
SUMMARY_PATH = ROOT / "docs" / "a_long_large_cap_market_cap_materialization_execution_summary_20260607.json"
PACKET_SCHEMA_PATH = ROOT / "schemas" / "a_long_large_cap_market_cap_materialization_packet.schema.json"
SUMMARY_SCHEMA_PATH = ROOT / "schemas" / "a_long_large_cap_market_cap_materialization_execution_summary.schema.json"
PREREGISTRATION_PATH = ROOT / "research" / "preregistrations" / "a_long_large_cap_pure_quality_20260607.json"
LEDGER_PATH = ROOT / "research" / "ledgers" / "a_long_large_cap_pure_quality_program_test_budget_ledger_20260607.json"
FIELD_PROBE_SUMMARY_PATH = ROOT / "docs" / "a_long_large_cap_market_cap_field_probe_execution_summary_20260607.json"
RAW_ROOT_REL = Path("data/a_long/raw/tushare/large_cap_market_cap_materialization_20260607")
RAW_ROOT = ROOT / RAW_ROOT_REL

SELECTED_MARKET_CAP_FIELD = "circ_mv"
DAILY_BASIC_FIELDS = "ts_code,trade_date,circ_mv"
UNIVERSE_SIZE_N = 500
MIN_DAILY_BASIC_ROW_COUNT = 1000
MIN_MAIN_BOARD_POSITIVE_FIELD_ROWS = 500
MAX_TOTAL_ENDPOINT_CALLS = 96
PLANNED_TOTAL_ENDPOINT_CALLS = 96
DEFAULT_MIN_SECONDS_BETWEEN_NETWORK_CALLS = 1.25

MONTHLY_AS_OF_DATES = [
    "20180131",
    "20180228",
    "20180330",
    "20180427",
    "20180531",
    "20180629",
    "20180731",
    "20180831",
    "20180928",
    "20181031",
    "20181130",
    "20181228",
    "20190131",
    "20190228",
    "20190329",
    "20190430",
    "20190531",
    "20190628",
    "20190731",
    "20190830",
    "20190930",
    "20191031",
    "20191129",
    "20191231",
    "20200123",
    "20200228",
    "20200331",
    "20200430",
    "20200529",
    "20200630",
    "20200731",
    "20200831",
    "20200930",
    "20201030",
    "20201130",
    "20201231",
    "20210129",
    "20210226",
    "20210331",
    "20210430",
    "20210531",
    "20210630",
    "20210730",
    "20210831",
    "20210930",
    "20211029",
    "20211130",
    "20211231",
    "20220128",
    "20220228",
    "20220331",
    "20220429",
    "20220531",
    "20220630",
    "20220729",
    "20220831",
    "20220930",
    "20221031",
    "20221130",
    "20221230",
    "20230131",
    "20230228",
    "20230331",
    "20230428",
    "20230531",
    "20230630",
    "20230731",
    "20230831",
    "20230928",
    "20231031",
    "20231130",
    "20231229",
    "20240131",
    "20240229",
    "20240329",
    "20240430",
    "20240531",
    "20240628",
    "20240731",
    "20240830",
    "20240930",
    "20241031",
    "20241129",
    "20241231",
    "20250127",
    "20250228",
    "20250331",
    "20250430",
    "20250530",
    "20250630",
    "20250731",
    "20250829",
    "20250930",
    "20251031",
    "20251128",
    "20251231",
]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run only the reviewed A-long large-cap monthly daily_basic market-cap materialization. "
            "It writes raw payloads under gitignored data/a_long/raw/ and a tracked no-raw summary. "
            "It does not run audit, signal search, alpha backtest, DataHub, or production logic."
        )
    )
    parser.add_argument("--packet-path", type=Path, default=PACKET_PATH)
    parser.add_argument("--summary-path", type=Path, default=SUMMARY_PATH)
    parser.add_argument("--raw-root", type=Path, default=RAW_ROOT)
    parser.add_argument("--generated-at", help="Optional deterministic timestamp for tests.")
    parser.add_argument("--confirm-independent-review-pass", action="store_true")
    parser.add_argument("--confirm-post-review-execute", action="store_true")
    parser.add_argument("--dry-run-env", action="store_true")
    parser.add_argument(
        "--min-seconds-between-network-calls",
        type=float,
        default=DEFAULT_MIN_SECONDS_BETWEEN_NETWORK_CALLS,
    )
    return parser.parse_args(argv)


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json_atomic(payload: Any, path: Path) -> None:
    thin_runner.write_json_atomic(payload, path)


def validate_json(schema_path: Path, payload: dict[str, Any]) -> None:
    try:
        from jsonschema import Draft7Validator
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "jsonschema is required for A-long schema-gated market-cap materialization; "
            "install project requirements before running this producer."
        ) from exc
    schema = read_json(schema_path)
    errors = sorted(Draft7Validator(schema).iter_errors(payload), key=lambda error: list(error.path))
    if errors:
        joined = "; ".join(f"{list(error.path)}: {error.message}" for error in errors[:8])
        raise ValueError(f"{schema_path} validation failed: {joined}")


def materialization_call_plan() -> list[dict[str, Any]]:
    return [
        {
            "call_id": f"daily_basic_market_cap_{trade_date}",
            "table_id": "daily_basic_market_cap_monthly",
            "api_family": "daily_basic",
            "method": "daily_basic",
            "trade_date": trade_date,
            "kwargs": {"trade_date": trade_date, "fields": DAILY_BASIC_FIELDS},
            "minimum_fields": ["ts_code", "trade_date", SELECTED_MARKET_CAP_FIELD],
            "selected_market_cap_field": SELECTED_MARKET_CAP_FIELD,
            "authorizes_audit_rerun": False,
            "authorizes_signal_search": False,
        }
        for trade_date in MONTHLY_AS_OF_DATES
    ]


def _packet_call_with_flags(call: dict[str, Any]) -> dict[str, Any]:
    return {
        "call_id": call["call_id"],
        "table_id": call["table_id"],
        "api_family": call["api_family"],
        "method": call["method"],
        "trade_date": call["trade_date"],
        "fields": DAILY_BASIC_FIELDS,
        "minimum_fields": list(call["minimum_fields"]),
        "selected_market_cap_field": SELECTED_MARKET_CAP_FIELD,
        "authorizes_audit_rerun": False,
        "authorizes_signal_search": False,
    }


def load_and_validate_packet(path: Path = PACKET_PATH) -> dict[str, Any]:
    packet = read_json(path)
    validate_json(PACKET_SCHEMA_PATH, packet)
    if packet.get("schema_name") != "a_long_large_cap_market_cap_materialization_packet":
        raise ValueError("market-cap materialization packet schema_name mismatch")

    scope = packet.get("scope") or {}
    required_true = [
        "research_only",
        "ready_for_later_execution_after_independent_review",
        "actual_tushare_calls_require_post_review_execute_command",
        "network_access_required_for_later_execution",
        "market_cap_materialization_allowed_after_gates",
        "manual_order_only",
    ]
    for field in required_true:
        if scope.get(field) is not True:
            raise ValueError(f"packet scope.{field} must be true")
    required_false = [
        "provider_calls_executed_by_this_artifact",
        "tushare_calls_executed_by_this_artifact",
        "data_fetch_executed_by_this_artifact",
        "raw_payloads_read_by_this_artifact",
        "audit_rerun_allowed_by_this_artifact",
        "signal_search_allowed",
        "alpha_backtest_allowed",
        "datahub_allowed",
        "production_use_allowed",
        "ship_gate_claim_allowed",
        "full_size_manual_use_allowed",
        "broker_or_order_automation_allowed",
    ]
    for field in required_false:
        if scope.get(field) is not False:
            raise ValueError(f"packet scope.{field} must be false")

    boundary = packet.get("materialization_boundary") or {}
    if boundary.get("materialization_id") != "a_long_large_cap_market_cap_top500_monthly_2018_2025":
        raise ValueError("packet materialization_id mismatch")
    if boundary.get("selected_market_cap_field") != SELECTED_MARKET_CAP_FIELD:
        raise ValueError("packet must freeze circ_mv as selected market-cap field")
    if boundary.get("monthly_as_of_dates") != MONTHLY_AS_OF_DATES:
        raise ValueError("packet monthly_as_of_dates drifted")
    if boundary.get("monthly_as_of_count") != PLANNED_TOTAL_ENDPOINT_CALLS:
        raise ValueError("packet monthly_as_of_count mismatch")
    if boundary.get("universe_size_n") != UNIVERSE_SIZE_N:
        raise ValueError("packet universe size drifted")
    if boundary.get("top_500_selection_written_to_tracked_summary") is not False:
        raise ValueError("tracked summary must not carry the full top-500 selection")

    generation = packet.get("call_generation_rule") or {}
    expected_generation = {
        "table_id": "daily_basic_market_cap_monthly",
        "api_family": "daily_basic",
        "method": "daily_basic",
        "call_id_template": "daily_basic_market_cap_{trade_date}",
        "fields": DAILY_BASIC_FIELDS,
        "minimum_fields": ["ts_code", "trade_date", SELECTED_MARKET_CAP_FIELD],
        "selected_market_cap_field": SELECTED_MARKET_CAP_FIELD,
        "one_call_per_monthly_as_of_date": True,
        "authorizes_audit_rerun": False,
        "authorizes_signal_search": False,
    }
    if generation != expected_generation:
        raise ValueError("packet call generation rule drifted")

    budget = packet.get("call_budget") or {}
    if budget.get("max_total_endpoint_calls") != MAX_TOTAL_ENDPOINT_CALLS:
        raise ValueError("packet max_total_endpoint_calls mismatch")
    if budget.get("planned_total_endpoint_calls") != PLANNED_TOTAL_ENDPOINT_CALLS:
        raise ValueError("packet planned_total_endpoint_calls mismatch")
    if budget.get("retry_count_allowed") != 0:
        raise ValueError("packet retry_count_allowed must be zero")
    if budget.get("abort_if_budget_exceeded") is not True:
        raise ValueError("packet must abort if budget is exceeded")

    storage = packet.get("storage_and_hygiene") or {}
    if storage.get("raw_output_root") != RAW_ROOT_REL.as_posix() + "/":
        raise ValueError("packet raw output root mismatch")
    if storage.get("tracked_summary_path") != "docs/a_long_large_cap_market_cap_materialization_execution_summary_20260607.json":
        raise ValueError("packet tracked summary path mismatch")
    for field in [
        "raw_output_root_must_be_gitignored",
        "tracked_summary_must_not_contain_raw_rows",
        "tracked_summary_must_not_contain_top500_symbols",
        "tracked_summary_must_not_contain_secret",
        "tracked_summary_must_not_contain_request_url",
    ]:
        if storage.get(field) is not True:
            raise ValueError(f"packet storage.{field} must be true")

    for field, value in (packet.get("pre_execution_gates") or {}).items():
        if value is not True:
            raise ValueError(f"packet gate must stay true: {field}")
    for field, value in (packet.get("prohibited_claims") or {}).items():
        if value is not False:
            raise ValueError(f"packet prohibited claim must stay false: {field}")
    if len(materialization_call_plan()) != PLANNED_TOTAL_ENDPOINT_CALLS:
        raise ValueError("runner call plan no longer matches packet planned_total_endpoint_calls")
    return packet


def validate_preregistration_probe_and_ledger() -> None:
    prereg = read_json(PREREGISTRATION_PATH)
    if prereg.get("schema_name") != "a_long_large_cap_pure_quality_preregistration":
        raise ValueError("large-cap preregistration schema_name mismatch")
    gate = prereg.get("data_dependency_gate") or {}
    if gate.get("selected_market_cap_field_status") != SELECTED_MARKET_CAP_FIELD:
        raise ValueError("large-cap preregistration must freeze circ_mv before materialization")
    if gate.get("market_cap_field_probe_execution_summary_ref") != "docs/a_long_large_cap_market_cap_field_probe_execution_summary_20260607.json":
        raise ValueError("large-cap preregistration must point to the reviewed field probe summary")
    universe = ((prereg.get("frozen_design") or {}).get("universe_rule") or {})
    if universe.get("market_cap_field_choice_status") != "circ_mv_reviewed_probe_passed_frozen_for_materialization":
        raise ValueError("large-cap universe field status must record reviewed circ_mv freeze")
    if prereg.get("scope", {}).get("signal_search_authorized_by_this_artifact") is not False:
        raise ValueError("preregistration must not authorize signal search")

    probe = read_json(FIELD_PROBE_SUMMARY_PATH)
    decision = probe.get("decision") or {}
    if decision.get("market_cap_field_probe_status") != "circ_mv_ready_for_reviewed_freeze":
        raise ValueError("field probe summary did not pass for circ_mv")
    if decision.get("recommended_market_cap_field") != SELECTED_MARKET_CAP_FIELD:
        raise ValueError("field probe summary recommended field mismatch")
    if decision.get("field_freeze_ready_for_review") is not True:
        raise ValueError("field probe summary must be freeze-ready for review")
    if decision.get("market_cap_materialization_authorized_by_this_summary") is not False:
        raise ValueError("field probe summary must not directly authorize materialization")

    ledger = read_json(LEDGER_PATH)
    budget = ledger.get("budget_policy") or {}
    if budget.get("tests_spent_count") != 0:
        raise ValueError("large-cap pure-quality singleton ledger must remain unspent before materialization")
    if ledger.get("test_spend_log") != []:
        raise ValueError("large-cap pure-quality ledger spend log must remain empty before signal-search execution")


def validate_raw_root(raw_root: Path) -> None:
    resolved = raw_root.resolve()
    approved = (ROOT / RAW_ROOT_REL).resolve()
    try:
        resolved.relative_to(approved)
    except ValueError as exc:
        raise ValueError(
            "raw output must stay under data/a_long/raw/tushare/large_cap_market_cap_materialization_20260607/"
        ) from exc
    if not route_base.path_is_gitignored_by_policy(raw_root):
        raise ValueError("raw output root is not protected by .gitignore policy")


def require_live_execution_confirmations(
    *,
    dry_run_env: bool,
    confirm_independent_review_pass: bool,
    confirm_post_review_execute: bool,
) -> None:
    thin_runner.require_live_execution_confirmations(
        dry_run_env=dry_run_env,
        confirm_independent_review_pass=confirm_independent_review_pass,
        confirm_post_review_execute=confirm_post_review_execute,
    )


def raw_payload_path(raw_root: Path, call_id: str) -> Path:
    safe = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in call_id)
    return raw_root / f"{safe}.json"


def write_raw_payload(raw_root: Path, call_id: str, payload: dict[str, Any]) -> str:
    path = raw_payload_path(raw_root, call_id)
    write_json_atomic(payload, path)
    return path.resolve().relative_to(ROOT.resolve()).as_posix()


def load_existing_raw_payload(raw_root: Path, call_id: str) -> tuple[dict[str, Any], str] | None:
    path = raw_payload_path(raw_root, call_id)
    if not path.exists():
        return None
    payload = read_json(path)
    return payload, path.resolve().relative_to(ROOT.resolve()).as_posix()


def _positive_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def top500_stats(records: list[dict[str, Any]]) -> dict[str, Any]:
    main_board_rows = [row for row in records if is_main_board_ts_code(row.get("ts_code"))]
    positive_rows: list[tuple[float, dict[str, Any]]] = []
    for row in main_board_rows:
        value = _positive_float(row.get(SELECTED_MARKET_CAP_FIELD))
        if value is not None:
            positive_rows.append((value, row))
    positive_rows.sort(key=lambda item: item[0], reverse=True)
    selected_values = [value for value, _row in positive_rows[:UNIVERSE_SIZE_N]]
    selected_count = len(selected_values)
    return {
        "main_board_row_count": len(main_board_rows),
        "main_board_positive_selected_field_count": len(positive_rows),
        "selected_top500_count": selected_count,
        "selected_top500_complete": selected_count == UNIVERSE_SIZE_N,
        "selected_market_cap_field": SELECTED_MARKET_CAP_FIELD,
        "top500_min_market_cap": min(selected_values) if selected_values else None,
        "top500_max_market_cap": max(selected_values) if selected_values else None,
        "top500_symbols_written_to_tracked_summary": False,
    }


def result_from_payload(call: dict[str, Any], payload: dict[str, Any], raw_ref: str | None, checkpoint_status: str) -> dict[str, Any]:
    columns = [str(col) for col in payload.get("columns") or []]
    row_count = payload.get("row_count")
    records = [row for row in payload.get("records") or [] if isinstance(row, dict)]
    missing = [field for field in call["minimum_fields"] if field not in columns]
    stats = top500_stats(records) if records else {
        "main_board_row_count": 0,
        "main_board_positive_selected_field_count": 0,
        "selected_top500_count": 0,
        "selected_top500_complete": False,
        "selected_market_cap_field": SELECTED_MARKET_CAP_FIELD,
        "top500_min_market_cap": None,
        "top500_max_market_cap": None,
        "top500_symbols_written_to_tracked_summary": False,
    }
    return {
        "call_id": call["call_id"],
        "table_id": call["table_id"],
        "api_family": call["api_family"],
        "request_shape_without_token": dict(call["kwargs"]),
        "call_status": payload.get("call_status", "error"),
        "trade_date": call["trade_date"],
        "row_count": row_count,
        "columns": columns,
        "minimum_fields_present": [field for field in call["minimum_fields"] if field in columns],
        "minimum_fields_missing": missing,
        "top500_main_board_stats": stats,
        "raw_payload_ref": raw_ref,
        "checkpoint_status": checkpoint_status,
        "tracked_summary_excludes_raw_rows": True,
        "tracked_summary_excludes_top500_symbols": True,
        "error_class": payload.get("error_class"),
        "error_message_redacted": payload.get("error_message_redacted"),
    }


def execute_call(pro: Any, call: dict[str, Any], raw_root: Path) -> tuple[dict[str, Any], bool]:
    existing = load_existing_raw_payload(raw_root, call["call_id"])
    if existing is not None:
        payload, raw_ref = existing
        return result_from_payload(call, payload, raw_ref, "reused_existing_raw"), False

    request_shape_without_token = dict(call["kwargs"])
    try:
        value = getattr(pro, call["method"])(**call["kwargs"])
        columns, row_count, records = route_base.normalize_records(value)
        status = "success" if row_count and row_count > 0 else "empty"
        raw_ref = write_raw_payload(
            raw_root,
            call["call_id"],
            {
                "call_id": call["call_id"],
                "table_id": call["table_id"],
                "api_family": call["api_family"],
                "request_shape_without_token": request_shape_without_token,
                "call_status": status,
                "row_count": row_count,
                "columns": columns,
                "records": records,
            },
        )
        payload = {
            "call_status": status,
            "row_count": row_count,
            "columns": columns,
            "records": records,
            "error_class": None,
            "error_message_redacted": None,
        }
    except Exception as exc:
        raw_ref = write_raw_payload(
            raw_root,
            call["call_id"],
            {
                "call_id": call["call_id"],
                "table_id": call["table_id"],
                "api_family": call["api_family"],
                "request_shape_without_token": request_shape_without_token,
                "call_status": "error",
                "error_class": type(exc).__name__,
                "error_message_redacted": route_base.redact_error(exc),
            },
        )
        payload = {
            "call_status": "error",
            "row_count": None,
            "columns": [],
            "records": [],
            "error_class": type(exc).__name__,
            "error_message_redacted": route_base.redact_error(exc),
        }
    return result_from_payload(call, payload, raw_ref, "written_new_raw"), True


def materialization_decision(results: list[dict[str, Any]], environment_precheck_passed: bool) -> tuple[str, bool, str, str]:
    if not environment_precheck_passed:
        return (
            "not_executed_environment_missing",
            False,
            "No daily_basic materialization call ran because the Tushare environment was missing.",
            "Set TUSHARE_TOKEN, keep the double gate, and run only the reviewed 96-call materialization.",
        )
    if not results:
        return (
            "not_executed_environment_check_only",
            False,
            "No daily_basic materialization call ran; this was an environment-only check.",
            "After independent review and user execute, run only the fixed 96 daily_basic calls.",
        )
    if len(results) != PLANNED_TOTAL_ENDPOINT_CALLS:
        return (
            "partial_or_failed_market_cap_materialization",
            False,
            "The materialization did not produce all 96 required daily_basic results.",
            "Fix incomplete materialization before audit or signal search.",
        )
    for result in results:
        if result.get("call_status") != "success":
            return (
                "partial_or_failed_market_cap_materialization",
                False,
                "At least one monthly daily_basic materialization call failed.",
                "Fix endpoint errors before audit or signal search.",
            )
        if (result.get("row_count") or 0) < MIN_DAILY_BASIC_ROW_COUNT:
            return (
                "partial_or_failed_market_cap_materialization",
                False,
                "At least one monthly daily_basic payload returned too few rows.",
                "Fix sparse daily_basic coverage before audit or signal search.",
            )
        stats = result.get("top500_main_board_stats") or {}
        if stats.get("main_board_positive_selected_field_count", 0) < MIN_MAIN_BOARD_POSITIVE_FIELD_ROWS:
            return (
                "partial_or_failed_market_cap_materialization",
                False,
                "At least one month cannot form a main-board top-500 by positive circ_mv.",
                "Fix monthly market-cap coverage before audit or signal search.",
            )
        if stats.get("selected_top500_complete") is not True:
            return (
                "partial_or_failed_market_cap_materialization",
                False,
                "At least one month has an incomplete top-500 main-board selection.",
                "Fix monthly market-cap coverage before audit or signal search.",
            )
    return (
        "passed_market_cap_materialization_shape",
        True,
        "daily_basic monthly circ_mv materialization produced enough main-board positive rows for top-500 selection on all 96 as-of dates.",
        "Send the execution summary for independent review; if passed, a later audit package may consume the raw market-cap payloads.",
    )


def build_summary(
    *,
    results: list[dict[str, Any]],
    generated_at: str,
    environment_precheck_passed: bool,
    independent_review_confirmed: bool,
    post_review_execute_confirmed: bool,
    new_network_call_count: int,
    reused_raw_payload_count: int,
) -> dict[str, Any]:
    status, shape_available, plain_result, next_action = materialization_decision(results, environment_precheck_passed)
    network_or_reuse = new_network_call_count > 0 or reused_raw_payload_count > 0
    selected_counts = [
        int((result.get("top500_main_board_stats") or {}).get("selected_top500_count") or 0)
        for result in results
    ]
    main_board_counts = [
        int((result.get("top500_main_board_stats") or {}).get("main_board_row_count") or 0)
        for result in results
    ]
    return {
        "schema_name": "a_long_large_cap_market_cap_materialization_execution_summary",
        "schema_version": "1.0.0",
        "generated_at": generated_at,
        "artifact_id": "a_long_large_cap_market_cap_materialization_execution_summary_20260607",
        "packet_ref": "docs/a_long_large_cap_market_cap_materialization_packet_20260607.json",
        "preregistration_ref": "research/preregistrations/a_long_large_cap_pure_quality_20260607.json",
        "ledger_ref": "research/ledgers/a_long_large_cap_pure_quality_program_test_budget_ledger_20260607.json",
        "field_probe_summary_ref": "docs/a_long_large_cap_market_cap_field_probe_execution_summary_20260607.json",
        "scope": {
            "phase": "7a_alpha_validation",
            "purpose": "a_long_large_cap_market_cap_materialization_execution",
            "lane_id": "a_long",
            "market": "A-share",
            "research_only": True,
            "provider_family": "tushare_existing_account",
            "provider_call_executed": new_network_call_count > 0,
            "tushare_call_executed": new_network_call_count > 0,
            "data_fetch_executed": new_network_call_count > 0,
            "raw_payload_available_in_gitignored_path": network_or_reuse,
            "tracked_summary_contains_raw_rows": False,
            "tracked_summary_contains_top500_symbols": False,
            "tracked_summary_contains_secret": False,
            "market_cap_field_freeze_already_reviewed": True,
            "market_cap_materialization_executed": network_or_reuse,
            "audit_rerun_executed": False,
            "signal_search_executed": False,
            "alpha_backtest_executed": False,
            "datahub_allowed": False,
            "production_use_allowed": False,
            "ship_gate_claim_allowed": False,
            "full_size_manual_use_allowed": False,
            "broker_or_order_automation_allowed": False,
            "manual_order_only": True,
        },
        "execution": {
            "summary_path": "docs/a_long_large_cap_market_cap_materialization_execution_summary_20260607.json",
            "raw_output_root": RAW_ROOT_REL.as_posix() + "/",
            "raw_output_root_is_gitignored": True,
            "max_total_endpoint_calls": MAX_TOTAL_ENDPOINT_CALLS,
            "planned_total_endpoint_calls": PLANNED_TOTAL_ENDPOINT_CALLS,
            "endpoint_results_count": len(results),
            "new_network_call_count": new_network_call_count,
            "reused_raw_payload_count": reused_raw_payload_count,
            "budget_exceeded": False,
            "network_call_attempted": new_network_call_count > 0,
            "environment_precheck_passed": environment_precheck_passed,
            "independent_review_confirmed": independent_review_confirmed,
            "post_review_execute_confirmed": post_review_execute_confirmed,
            "token_logged": False,
            "request_url_logged": False,
        },
        "materialization_boundary": {
            "materialization_id": "a_long_large_cap_market_cap_top500_monthly_2018_2025",
            "method": "daily_basic",
            "selected_market_cap_field": SELECTED_MARKET_CAP_FIELD,
            "monthly_as_of_count": PLANNED_TOTAL_ENDPOINT_CALLS,
            "monthly_as_of_dates": list(MONTHLY_AS_OF_DATES),
            "universe_size_n": UNIVERSE_SIZE_N,
            "board_scope": "main_board_only",
            "top_500_selection_written_to_tracked_summary": False,
            "not_signal_search": True,
        },
        "coverage_rollup": {
            "months_with_success": sum(1 for result in results if result.get("call_status") == "success"),
            "months_with_complete_top500": sum(
                1 for result in results if (result.get("top500_main_board_stats") or {}).get("selected_top500_complete") is True
            ),
            "min_main_board_row_count": min(main_board_counts) if main_board_counts else None,
            "min_selected_top500_count": min(selected_counts) if selected_counts else None,
            "selected_market_cap_field": SELECTED_MARKET_CAP_FIELD,
        },
        "endpoint_results": results,
        "decision": {
            "market_cap_materialization_status": status,
            "raw_market_cap_materialization_shape_available": shape_available,
            "selected_market_cap_field": SELECTED_MARKET_CAP_FIELD,
            "audit_rerun_authorized_by_this_summary": False,
            "signal_search_authorized_by_this_summary": False,
            "plain_result": plain_result,
            "next_action": next_action,
        },
        "prohibited_claims": {
            "a_long_alpha_found": False,
            "audit_passed": False,
            "signal_search_authorized": False,
            "production_ready": False,
            "ship_gate_evidence": False,
            "full_size_allowed": False,
            "datahub_authorized": False,
            "broker_or_order_automation_authorized": False,
        },
        "limitations": [
            "This summary records monthly daily_basic market-cap materialization shape and counts only.",
            "Raw rows stay under gitignored data/a_long/raw/ and are not included in the tracked summary.",
            "Tracked summary does not include the 96 monthly top-500 symbol lists.",
            "A materialization pass is not an audit pass and does not authorize signal search, alpha, production, ship-gate evidence, full-size use, DataHub, or broker/order automation.",
        ],
    }


def execute_market_cap_materialization(
    *,
    packet_path: Path = PACKET_PATH,
    summary_path: Path = SUMMARY_PATH,
    raw_root: Path = RAW_ROOT,
    pro_factory: Callable[[], Any] = route_base.get_tushare_client,
    generated_at: str | None = None,
    dry_run_env: bool = False,
    confirm_independent_review_pass: bool = False,
    confirm_post_review_execute: bool = False,
    min_seconds_between_network_calls: float = DEFAULT_MIN_SECONDS_BETWEEN_NETWORK_CALLS,
) -> dict[str, Any]:
    load_and_validate_packet(packet_path)
    validate_preregistration_probe_and_ledger()
    validate_raw_root(raw_root)
    require_live_execution_confirmations(
        dry_run_env=dry_run_env,
        confirm_independent_review_pass=confirm_independent_review_pass,
        confirm_post_review_execute=confirm_post_review_execute,
    )
    generated = generated_at or iso_now()
    calls = materialization_call_plan()
    if len(calls) > MAX_TOTAL_ENDPOINT_CALLS:
        raise ValueError("planned daily_basic materialization calls exceed max budget")

    if dry_run_env:
        summary = build_summary(
            results=[],
            generated_at=generated,
            environment_precheck_passed=bool(os.environ.get("TUSHARE_TOKEN")),
            independent_review_confirmed=confirm_independent_review_pass,
            post_review_execute_confirmed=confirm_post_review_execute,
            new_network_call_count=0,
            reused_raw_payload_count=0,
        )
        validate_json(SUMMARY_SCHEMA_PATH, summary)
        write_json_atomic(summary, summary_path)
        return summary

    if pro_factory is route_base.get_tushare_client and not os.environ.get("TUSHARE_TOKEN"):
        summary = build_summary(
            results=[],
            generated_at=generated,
            environment_precheck_passed=False,
            independent_review_confirmed=confirm_independent_review_pass,
            post_review_execute_confirmed=confirm_post_review_execute,
            new_network_call_count=0,
            reused_raw_payload_count=0,
        )
        validate_json(SUMMARY_SCHEMA_PATH, summary)
        write_json_atomic(summary, summary_path)
        return summary

    pro = pro_factory()
    results: list[dict[str, Any]] = []
    new_network_call_count = 0
    reused_raw_payload_count = 0
    last_network_started: float | None = None
    for call in calls:
        if last_network_started is not None and min_seconds_between_network_calls > 0:
            elapsed = time.monotonic() - last_network_started
            if elapsed < min_seconds_between_network_calls:
                time.sleep(min_seconds_between_network_calls - elapsed)
        result, used_network = execute_call(pro, call, raw_root)
        results.append(result)
        if used_network:
            new_network_call_count += 1
            last_network_started = time.monotonic()
        else:
            reused_raw_payload_count += 1
        if new_network_call_count + reused_raw_payload_count > MAX_TOTAL_ENDPOINT_CALLS:
            raise ValueError("daily_basic market-cap materialization exceeded max budget")

    summary = build_summary(
        results=results,
        generated_at=generated,
        environment_precheck_passed=True,
        independent_review_confirmed=confirm_independent_review_pass,
        post_review_execute_confirmed=confirm_post_review_execute,
        new_network_call_count=new_network_call_count,
        reused_raw_payload_count=reused_raw_payload_count,
    )
    validate_json(SUMMARY_SCHEMA_PATH, summary)
    write_json_atomic(summary, summary_path)
    return summary


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    summary = execute_market_cap_materialization(
        packet_path=args.packet_path,
        summary_path=args.summary_path,
        raw_root=args.raw_root,
        generated_at=args.generated_at,
        dry_run_env=args.dry_run_env,
        confirm_independent_review_pass=args.confirm_independent_review_pass,
        confirm_post_review_execute=args.confirm_post_review_execute,
        min_seconds_between_network_calls=args.min_seconds_between_network_calls,
    )
    print(
        json.dumps(
            {
                "market_cap_materialization_status": summary["decision"]["market_cap_materialization_status"],
                "selected_market_cap_field": summary["decision"]["selected_market_cap_field"],
                "raw_market_cap_materialization_shape_available": summary["decision"][
                    "raw_market_cap_materialization_shape_available"
                ],
                "plain_result": summary["decision"]["plain_result"],
                "next_action": summary["decision"]["next_action"],
                "new_network_call_count": summary["execution"]["new_network_call_count"],
                "reused_raw_payload_count": summary["execution"]["reused_raw_payload_count"],
                "summary_path": summary["execution"]["summary_path"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

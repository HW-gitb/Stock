from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runners import a_long_tushare_incremental_materialization_packet as thin_runner
from runners import a_long_tushare_route_validation_packet as route_base


PACKET_PATH = ROOT / "docs" / "a_long_large_cap_market_cap_field_probe_packet_20260607.json"
PREREGISTRATION_PATH = ROOT / "research" / "preregistrations" / "a_long_large_cap_pure_quality_20260607.json"
LEDGER_PATH = ROOT / "research" / "ledgers" / "a_long_large_cap_pure_quality_program_test_budget_ledger_20260607.json"
SUMMARY_SCHEMA_PATH = ROOT / "schemas" / "a_long_large_cap_market_cap_field_probe_execution_summary.schema.json"
SUMMARY_PATH = ROOT / "docs" / "a_long_large_cap_market_cap_field_probe_execution_summary_20260607.json"
RAW_ROOT_REL = Path("data/a_long/raw/tushare/large_cap_market_cap_field_probe_20260607")
RAW_ROOT = ROOT / RAW_ROOT_REL

TRADE_DATES = ["20180131", "20211231", "20251231"]
FIELDS = "ts_code,trade_date,circ_mv,total_mv"
MARKET_CAP_FIELDS = ["circ_mv", "total_mv"]
MINIMUM_FIELDS = ["ts_code", "trade_date", "circ_mv", "total_mv"]
MINIMUM_ROW_COUNT_PER_PROBE = 1000
MINIMUM_NON_NULL_RATIO = 0.95
MINIMUM_POSITIVE_RATIO = 0.95
MAX_TOTAL_ENDPOINT_CALLS = 3
PLANNED_TOTAL_ENDPOINT_CALLS = 3


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run the reviewed A-long large-cap daily_basic market-cap field probe. "
            "This executes only three fixed trade_date calls after the double gate; "
            "it does not materialize market cap, run audit, or search alpha."
        )
    )
    parser.add_argument("--packet-path", type=Path, default=PACKET_PATH)
    parser.add_argument("--summary-path", type=Path, default=SUMMARY_PATH)
    parser.add_argument("--raw-root", type=Path, default=RAW_ROOT)
    parser.add_argument("--generated-at", help="Optional deterministic timestamp for tests.")
    parser.add_argument(
        "--confirm-independent-review-pass",
        action="store_true",
        help="Required for live execution; confirms independent review passed the packet.",
    )
    parser.add_argument(
        "--confirm-post-review-execute",
        action="store_true",
        help="Required for live execution; confirms the user issued the post-review execute command.",
    )
    parser.add_argument(
        "--dry-run-env",
        action="store_true",
        help="Validate packet, preregistration, ledger, gitignore, and environment boundary without Tushare calls.",
    )
    return parser.parse_args(argv)


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def read_json(path: Path) -> Any:
    return thin_runner.read_json(path)


def write_json_atomic(payload: Any, path: Path) -> None:
    thin_runner.write_json_atomic(payload, path)


def call_plan() -> list[dict[str, Any]]:
    return [
        {
            "call_id": f"daily_basic_market_cap_{trade_date}_probe",
            "table_id": "daily_basic_market_cap_field_probe",
            "api_family": "daily_basic",
            "method": "daily_basic",
            "kwargs": {
                "trade_date": trade_date,
                "fields": FIELDS,
            },
            "minimum_fields": list(MINIMUM_FIELDS),
        }
        for trade_date in TRADE_DATES
    ]


def _packet_call_with_flags(call: dict[str, Any]) -> dict[str, Any]:
    return call | {
        "raw_parse_allowed_for_summary_shape_only": True,
        "authorizes_market_cap_field_freeze": False,
        "authorizes_market_cap_materialization": False,
        "authorizes_factor_derivation": False,
        "authorizes_audit_rerun": False,
        "authorizes_signal_search": False,
    }


def load_and_validate_packet(path: Path = PACKET_PATH) -> dict[str, Any]:
    packet = read_json(path)
    if packet.get("schema_name") != "a_long_large_cap_market_cap_field_probe_packet":
        raise ValueError("A-long large-cap market-cap field probe packet schema_name mismatch")

    scope = packet.get("scope") or {}
    required_true = [
        "research_only",
        "ready_for_later_execution_after_independent_review",
        "actual_tushare_calls_require_post_review_execute_command",
        "network_access_required_for_later_execution",
        "daily_basic_market_cap_field_probe_allowed_after_gates",
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
        "market_cap_field_freeze_allowed_by_this_artifact",
        "market_cap_materialization_allowed_by_this_artifact",
        "full_market_materialization_allowed",
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

    boundary = packet.get("probe_boundary") or {}
    if boundary.get("probe_id") != "a_long_large_cap_daily_basic_market_cap_field_probe_3_dates":
        raise ValueError("packet probe_id mismatch")
    if boundary.get("preregistration_ref") != "research/preregistrations/a_long_large_cap_pure_quality_20260607.json":
        raise ValueError("packet preregistration_ref mismatch")
    if boundary.get("ledger_ref") != "research/ledgers/a_long_large_cap_pure_quality_program_test_budget_ledger_20260607.json":
        raise ValueError("packet ledger_ref mismatch")
    if boundary.get("method") != "daily_basic" or boundary.get("api_family") != "daily_basic":
        raise ValueError("packet must remain a daily_basic field probe")
    if boundary.get("trade_dates") != TRADE_DATES:
        raise ValueError("packet trade_dates must stay fixed")
    if boundary.get("field_preference_order") != MARKET_CAP_FIELDS:
        raise ValueError("packet field preference order must stay circ_mv then total_mv")
    for field in ["not_full_96_month_pull", "not_signal_search", "pass_does_not_make_data_alpha_ready"]:
        if boundary.get(field) is not True:
            raise ValueError(f"packet boundary.{field} must be true")

    expected_calls = [_packet_call_with_flags(call) for call in call_plan()]
    if packet.get("probe_calls") != expected_calls:
        raise ValueError("packet probe calls must stay fixed")

    selection = packet.get("selection_rule") or {}
    expected_selection = {
        "field_preference_order": MARKET_CAP_FIELDS,
        "minimum_row_count_per_probe": MINIMUM_ROW_COUNT_PER_PROBE,
        "minimum_non_null_ratio_for_selected_field": MINIMUM_NON_NULL_RATIO,
        "minimum_positive_ratio_for_selected_field": MINIMUM_POSITIVE_RATIO,
        "circ_mv_selected_if_all_probe_dates_pass": True,
        "total_mv_fallback_selected_only_if_circ_mv_fails_and_total_mv_passes": True,
        "selection_after_execution_requires_independent_review": True,
        "selected_field_freezes_before_materialization_only_after_reviewed_result": True,
    }
    if selection != expected_selection:
        raise ValueError("packet selection rule drifted")

    budget = packet.get("call_budget") or {}
    if budget.get("max_total_endpoint_calls") != MAX_TOTAL_ENDPOINT_CALLS:
        raise ValueError("packet max_total_endpoint_calls must be 3")
    if budget.get("planned_total_endpoint_calls") != PLANNED_TOTAL_ENDPOINT_CALLS:
        raise ValueError("packet planned_total_endpoint_calls must be 3")
    if budget.get("retry_count_allowed") != 0:
        raise ValueError("packet retry_count_allowed must be zero")
    if budget.get("abort_if_budget_exceeded") is not True:
        raise ValueError("packet must abort on budget exceed")

    storage = packet.get("storage_and_checkpoint_boundary") or {}
    if storage.get("raw_output_root") != RAW_ROOT_REL.as_posix() + "/":
        raise ValueError("packet raw output root mismatch")
    if storage.get("tracked_summary_path") != "docs/a_long_large_cap_market_cap_field_probe_execution_summary_20260607.json":
        raise ValueError("packet tracked summary path mismatch")
    for field in [
        "raw_output_root_must_be_gitignored",
        "tracked_summary_must_exclude_raw_rows",
        "tracked_summary_must_exclude_request_urls",
        "tracked_summary_must_exclude_secret",
        "checkpoint_resume_allowed",
        "existing_raw_payload_reuse_allowed",
        "append_or_versioned_only",
    ]:
        if storage.get(field) is not True:
            raise ValueError(f"packet storage.{field} must be true")
    for field in ["overwrite_existing_raw_without_resume_allowed", "raw_retention_authorizes_production_storage"]:
        if storage.get(field) is not False:
            raise ValueError(f"packet storage.{field} must be false")

    for field, value in (packet.get("pre_execution_gates") or {}).items():
        if value is not True:
            raise ValueError(f"packet gate must stay true: {field}")
    for field, value in (packet.get("prohibited_claims") or {}).items():
        if value is not False:
            raise ValueError(f"packet prohibited claim must stay false: {field}")
    if len(call_plan()) != PLANNED_TOTAL_ENDPOINT_CALLS:
        raise ValueError("runner call plan no longer matches packet planned_total_endpoint_calls")
    return packet


def validate_preregistration_and_ledger() -> None:
    prereg = read_json(PREREGISTRATION_PATH)
    if prereg.get("schema_name") != "a_long_large_cap_pure_quality_preregistration":
        raise ValueError("large-cap pure-quality preregistration schema_name mismatch")
    scope = prereg.get("scope") or {}
    if scope.get("preregistration_review_status") != "passed_independent_review_ready_for_freeze":
        raise ValueError("large-cap preregistration must be independently reviewed before this probe")
    if scope.get("market_cap_probe_allowed_by_this_artifact") is not False:
        raise ValueError("preregistration must not itself authorize the probe")
    gate = prereg.get("data_dependency_gate") or {}
    if gate.get("selected_market_cap_field_status") != "pending_probe_not_selected":
        raise ValueError("market-cap field should still be pending before this probe")
    if gate.get("separate_review_required_before_probe_or_pull") is not True:
        raise ValueError("preregistration must require a separate reviewed probe")
    if gate.get("separate_user_execute_required_before_probe_or_pull") is not True:
        raise ValueError("preregistration must require a separate user execute before probe")

    ledger = read_json(LEDGER_PATH)
    if ledger.get("schema_name") != "program_test_budget_ledger":
        raise ValueError("large-cap pure-quality ledger schema_name mismatch")
    if ledger.get("artifact_id") != "a_long_large_cap_pure_quality_program_test_budget_ledger_20260607":
        raise ValueError("large-cap pure-quality ledger artifact_id mismatch")
    budget = ledger.get("budget_policy") or {}
    if budget.get("tests_spent_count") != 0:
        raise ValueError("large-cap pure-quality singleton ledger must be unspent before field probe")
    if ledger.get("test_spend_log") != []:
        raise ValueError("large-cap pure-quality ledger spend log must remain empty before signal-search execution")


def validate_raw_root(raw_root: Path) -> None:
    resolved = raw_root.resolve()
    approved = (ROOT / RAW_ROOT_REL).resolve()
    try:
        resolved.relative_to(approved)
    except ValueError as exc:
        raise ValueError(
            "raw output must stay under data/a_long/raw/tushare/large_cap_market_cap_field_probe_20260607/"
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


def _numeric_positive(value: Any) -> bool:
    if value in (None, ""):
        return False
    try:
        return float(value) > 0
    except (TypeError, ValueError):
        return False


def field_stats(columns: list[str], row_count: int | None, records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    stats: dict[str, dict[str, Any]] = {}
    denominator = row_count if row_count and row_count > 0 else None
    for field in MARKET_CAP_FIELDS:
        present = field in columns
        non_null_count = sum(1 for row in records if row.get(field) not in (None, ""))
        positive_count = sum(1 for row in records if _numeric_positive(row.get(field)))
        non_null_ratio = (non_null_count / denominator) if denominator else None
        positive_ratio = (positive_count / denominator) if denominator else None
        stats[field] = {
            "present_in_columns": present,
            "non_null_count": non_null_count,
            "positive_count": positive_count,
            "non_null_ratio": non_null_ratio,
            "positive_ratio": positive_ratio,
            "passes_selection_rule": bool(
                present
                and denominator is not None
                and denominator >= MINIMUM_ROW_COUNT_PER_PROBE
                and non_null_ratio is not None
                and non_null_ratio >= MINIMUM_NON_NULL_RATIO
                and positive_ratio is not None
                and positive_ratio >= MINIMUM_POSITIVE_RATIO
            ),
        }
    return stats


def result_from_payload(call: dict[str, Any], payload: dict[str, Any], raw_ref: str | None, checkpoint_status: str) -> dict[str, Any]:
    columns = [str(col) for col in payload.get("columns") or []]
    row_count = payload.get("row_count")
    records = [row for row in payload.get("records") or [] if isinstance(row, dict)]
    minimum = list(call["minimum_fields"])
    present = [field for field in minimum if field in columns]
    missing = [field for field in minimum if field not in columns]
    status = payload.get("call_status", "error")
    return {
        "call_id": call["call_id"],
        "table_id": call["table_id"],
        "api_family": call["api_family"],
        "request_shape_without_token": dict(call["kwargs"]),
        "call_status": status,
        "row_count": row_count,
        "columns": columns,
        "minimum_fields_present": present,
        "minimum_fields_missing": missing,
        "market_cap_field_stats": field_stats(columns, row_count, records),
        "raw_payload_ref": raw_ref,
        "checkpoint_status": checkpoint_status,
        "tracked_summary_excludes_raw_rows": True,
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


def _all_field_pass(results: list[dict[str, Any]], field: str) -> bool:
    if len(results) != PLANNED_TOTAL_ENDPOINT_CALLS:
        return False
    for result in results:
        if result.get("call_status") != "success":
            return False
        if result.get("row_count") is None or result.get("row_count") < MINIMUM_ROW_COUNT_PER_PROBE:
            return False
        if result.get("minimum_fields_missing"):
            return False
        stats = (result.get("market_cap_field_stats") or {}).get(field) or {}
        if stats.get("passes_selection_rule") is not True:
            return False
    return True


def field_probe_decision(results: list[dict[str, Any]], environment_precheck_passed: bool) -> tuple[str, str | None, bool, bool, str, str]:
    if not environment_precheck_passed:
        return (
            "not_executed_environment_missing",
            None,
            False,
            False,
            "No daily_basic call ran because the Tushare environment was missing.",
            "Set TUSHARE_TOKEN, keep the double gate, and run only this three-call field probe.",
        )
    if not results:
        return (
            "not_executed_environment_check_only",
            None,
            False,
            False,
            "No daily_basic call ran; this was an environment-only check.",
            "After independent review and user execute, run only the three fixed daily_basic probes.",
        )
    if len(results) != PLANNED_TOTAL_ENDPOINT_CALLS:
        return (
            "partial_probe_incomplete",
            None,
            False,
            False,
            "The probe did not produce all three required daily_basic results.",
            "Fix the incomplete probe before any market-cap field freeze or materialization.",
        )
    if any(result.get("call_status") == "error" for result in results):
        return (
            "daily_basic_probe_error",
            None,
            False,
            False,
            "At least one daily_basic probe errored.",
            "Fix the endpoint error before any market-cap field freeze or materialization.",
        )
    if any(result.get("call_status") == "empty" or (result.get("row_count") or 0) < MINIMUM_ROW_COUNT_PER_PROBE for result in results):
        return (
            "daily_basic_probe_empty_or_too_sparse",
            None,
            False,
            False,
            "At least one daily_basic probe returned empty or too few rows for field-selection evidence.",
            "Repair the daily_basic route or choose a new reviewed market-cap source before materialization.",
        )
    if _all_field_pass(results, "circ_mv"):
        return (
            "circ_mv_ready_for_reviewed_freeze",
            "circ_mv",
            False,
            True,
            "daily_basic returned usable circ_mv across all fixed probe dates.",
            "Send the execution summary for independent review; if passed, a later materialization packet may freeze circ_mv.",
        )
    if _all_field_pass(results, "total_mv"):
        return (
            "total_mv_ready_for_reviewed_freeze",
            "total_mv",
            True,
            True,
            "circ_mv did not pass the frozen probe rule, but total_mv did across all fixed probe dates.",
            "Send the execution summary for independent review; if passed, a later materialization packet may freeze total_mv fallback.",
        )
    return (
        "blocked_no_market_cap_field_passed",
        None,
        False,
        False,
        "Neither circ_mv nor total_mv passed the frozen field-selection rule across all probe dates.",
        "Do not materialize or search signals; create a new reviewed source or field-resolution plan.",
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
    status, selected_field, fallback_used, freeze_ready, plain_result, next_action = field_probe_decision(
        results,
        environment_precheck_passed,
    )
    network_or_reuse = new_network_call_count > 0 or reused_raw_payload_count > 0
    return {
        "schema_name": "a_long_large_cap_market_cap_field_probe_execution_summary",
        "schema_version": "1.0.0",
        "generated_at": generated_at,
        "artifact_id": "a_long_large_cap_market_cap_field_probe_execution_summary_20260607",
        "packet_ref": "docs/a_long_large_cap_market_cap_field_probe_packet_20260607.json",
        "preregistration_ref": "research/preregistrations/a_long_large_cap_pure_quality_20260607.json",
        "ledger_ref": "research/ledgers/a_long_large_cap_pure_quality_program_test_budget_ledger_20260607.json",
        "scope": {
            "phase": "7a_alpha_validation",
            "purpose": "a_long_large_cap_market_cap_field_probe_execution",
            "lane_id": "a_long",
            "market": "A-share",
            "research_only": True,
            "provider_family": "tushare_existing_account",
            "provider_call_executed": new_network_call_count > 0,
            "tushare_call_executed": new_network_call_count > 0,
            "data_fetch_executed": new_network_call_count > 0,
            "raw_payload_available_in_gitignored_path": network_or_reuse,
            "tracked_summary_contains_raw_rows": False,
            "tracked_summary_contains_secret": False,
            "market_cap_field_freeze_executed": False,
            "market_cap_materialization_executed": False,
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
            "summary_path": "docs/a_long_large_cap_market_cap_field_probe_execution_summary_20260607.json",
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
        "probe_boundary": {
            "probe_id": "a_long_large_cap_daily_basic_market_cap_field_probe_3_dates",
            "method": "daily_basic",
            "trade_dates": list(TRADE_DATES),
            "field_preference_order": list(MARKET_CAP_FIELDS),
            "minimum_row_count_per_probe": MINIMUM_ROW_COUNT_PER_PROBE,
            "minimum_non_null_ratio_for_selected_field": MINIMUM_NON_NULL_RATIO,
            "minimum_positive_ratio_for_selected_field": MINIMUM_POSITIVE_RATIO,
            "not_full_96_month_pull": True,
            "not_signal_search": True,
        },
        "endpoint_results": results,
        "decision": {
            "market_cap_field_probe_status": status,
            "recommended_market_cap_field": selected_field,
            "fallback_used": fallback_used,
            "field_freeze_ready_for_review": freeze_ready,
            "market_cap_field_frozen_by_this_summary": False,
            "market_cap_materialization_authorized_by_this_summary": False,
            "audit_rerun_authorized_by_this_summary": False,
            "signal_search_authorized_by_this_summary": False,
            "plain_result": plain_result,
            "next_action": next_action,
        },
        "prohibited_claims": {
            "a_long_alpha_found": False,
            "daily_basic_full_history_materialized": False,
            "market_cap_field_frozen": False,
            "market_cap_materialized": False,
            "audit_passed": False,
            "signal_search_authorized": False,
            "production_ready": False,
            "ship_gate_evidence": False,
            "full_size_allowed": False,
            "datahub_authorized": False,
            "broker_or_order_automation_authorized": False,
        },
        "limitations": [
            "This summary records only three fixed daily_basic field probes.",
            "Raw rows stay under gitignored data/a_long/raw/ and are not included in the tracked summary.",
            "The result can only recommend a market-cap field for independent review; it does not freeze the field by itself.",
            "No market-cap materialization, audit rerun, signal search, alpha backtest, DataHub, production, ship-gate, full-size use, or broker/order automation is authorized.",
        ],
    }


def validate_json(schema_path: Path, payload: dict[str, Any]) -> None:
    try:
        from jsonschema import Draft7Validator
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "jsonschema is required for A-long schema-gated market-cap field probes; "
            "install project requirements before running this producer."
        ) from exc
    schema = read_json(schema_path)
    errors = sorted(Draft7Validator(schema).iter_errors(payload), key=lambda error: list(error.path))
    if errors:
        joined = "; ".join(f"{list(error.path)}: {error.message}" for error in errors[:8])
        raise ValueError(f"{schema_path} validation failed: {joined}")


def execute_market_cap_field_probe(
    *,
    packet_path: Path = PACKET_PATH,
    summary_path: Path = SUMMARY_PATH,
    raw_root: Path = RAW_ROOT,
    pro_factory: Callable[[], Any] = route_base.get_tushare_client,
    generated_at: str | None = None,
    dry_run_env: bool = False,
    confirm_independent_review_pass: bool = False,
    confirm_post_review_execute: bool = False,
) -> dict[str, Any]:
    load_and_validate_packet(packet_path)
    validate_preregistration_and_ledger()
    validate_raw_root(raw_root)
    require_live_execution_confirmations(
        dry_run_env=dry_run_env,
        confirm_independent_review_pass=confirm_independent_review_pass,
        confirm_post_review_execute=confirm_post_review_execute,
    )
    generated = generated_at or iso_now()
    calls = call_plan()
    if len(calls) > MAX_TOTAL_ENDPOINT_CALLS:
        raise ValueError("planned daily_basic field probes exceed max budget")

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
    for call in calls:
        result, used_network = execute_call(pro, call, raw_root)
        results.append(result)
        if used_network:
            new_network_call_count += 1
        else:
            reused_raw_payload_count += 1
        if new_network_call_count + reused_raw_payload_count > MAX_TOTAL_ENDPOINT_CALLS:
            raise ValueError("daily_basic field probe exceeded max budget")

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
    summary = execute_market_cap_field_probe(
        packet_path=args.packet_path,
        summary_path=args.summary_path,
        raw_root=args.raw_root,
        generated_at=args.generated_at,
        dry_run_env=args.dry_run_env,
        confirm_independent_review_pass=args.confirm_independent_review_pass,
        confirm_post_review_execute=args.confirm_post_review_execute,
    )
    decision = summary["decision"]
    print(
        json.dumps(
            {
                "market_cap_field_probe_status": decision["market_cap_field_probe_status"],
                "recommended_market_cap_field": decision["recommended_market_cap_field"],
                "field_freeze_ready_for_review": decision["field_freeze_ready_for_review"],
                "plain_result": decision["plain_result"],
                "next_action": decision["next_action"],
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

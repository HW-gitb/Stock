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


PACKET_PATH = ROOT / "docs" / "a_long_tushare_daily_price_route_diagnostic_packet_20260604.json"
PRIOR_BROADER_SUMMARY_PATH = ROOT / "docs" / "a_long_tushare_broader_materialization_execution_summary_20260604.json"
SUMMARY_PATH = ROOT / "docs" / "a_long_tushare_daily_price_route_diagnostic_execution_summary_20260604.json"
RAW_ROOT_REL = Path("data/a_long/raw/tushare/daily_price_route_diagnostic_20260604")
RAW_ROOT = ROOT / RAW_ROOT_REL

FIXED_SYMBOL = "000001.SZ"
EIGHT_YEAR_START_DATE = "20180101"
EIGHT_YEAR_END_DATE = "20251231"
CONTROL_START_DATE = "20220101"
CONTROL_END_DATE = "20221231"
EIGHT_YEAR_CALL_ID = "daily_000001_SZ_2018_2025_isolated_probe"
CONTROL_CALL_ID = "daily_000001_SZ_2022_control_probe"
MAX_TOTAL_ENDPOINT_CALLS = 2
PLANNED_TOTAL_ENDPOINT_CALLS = 2


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run the reviewed A-long Tushare daily price route diagnostic packet. "
            "This executes only two fixed daily calls after the double gate; "
            "it does not repair data, rerun audit, or search alpha."
        )
    )
    parser.add_argument("--packet-path", type=Path, default=PACKET_PATH)
    parser.add_argument("--summary-path", type=Path, default=SUMMARY_PATH)
    parser.add_argument("--raw-root", type=Path, default=RAW_ROOT)
    parser.add_argument("--generated-at", help="Optional deterministic timestamp for tests.")
    parser.add_argument(
        "--confirm-independent-review-pass",
        action="store_true",
        help="Required for live execution; confirms Claude review passed the packet.",
    )
    parser.add_argument(
        "--confirm-post-review-execute",
        action="store_true",
        help="Required for live execution; confirms the user issued the post-review execute command.",
    )
    parser.add_argument(
        "--dry-run-env",
        action="store_true",
        help="Validate packet, prior summary, gitignore, and environment boundary without Tushare calls.",
    )
    return parser.parse_args(argv)


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def read_json(path: Path) -> Any:
    return thin_runner.read_json(path)


def write_json_atomic(payload: Any, path: Path) -> None:
    thin_runner.write_json_atomic(payload, path)


def diagnostic_call_plan() -> list[dict[str, Any]]:
    return [
        {
            "call_id": EIGHT_YEAR_CALL_ID,
            "table_id": "daily_price_eight_year_isolated_probe",
            "api_family": "daily",
            "method": "daily",
            "kwargs": {
                "ts_code": FIXED_SYMBOL,
                "start_date": EIGHT_YEAR_START_DATE,
                "end_date": EIGHT_YEAR_END_DATE,
                "fields": "ts_code,trade_date,open,close,vol,amount",
            },
            "minimum_fields": ["ts_code", "trade_date", "open", "close"],
        },
        {
            "call_id": CONTROL_CALL_ID,
            "table_id": "daily_price_one_year_control_probe",
            "api_family": "daily",
            "method": "daily",
            "kwargs": {
                "ts_code": FIXED_SYMBOL,
                "start_date": CONTROL_START_DATE,
                "end_date": CONTROL_END_DATE,
                "fields": "ts_code,trade_date,open,close,vol,amount",
            },
            "minimum_fields": ["ts_code", "trade_date", "open", "close"],
        }
    ]


def _packet_call_with_flags(call: dict[str, Any]) -> dict[str, Any]:
    return call | {
        "raw_parse_allowed_for_summary_shape_only": True,
        "authorizes_price_route_repair": False,
        "authorizes_return_calculation": False,
        "authorizes_factor_derivation": False,
        "authorizes_audit_rerun": False,
        "authorizes_signal_search": False,
    }


def load_and_validate_packet(path: Path = PACKET_PATH) -> dict[str, Any]:
    packet = read_json(path)
    if packet.get("schema_name") != "a_long_tushare_daily_price_route_diagnostic_packet":
        raise ValueError("A-long daily price diagnostic packet schema_name mismatch")

    scope = packet.get("scope") or {}
    required_true = [
        "research_only",
        "ready_for_later_execution_after_independent_review",
        "actual_tushare_calls_require_post_review_execute_command",
        "network_access_required_for_later_execution",
        "daily_price_route_diagnostic_allowed_after_gates",
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
        "daily_price_route_repair_allowed_by_this_artifact",
        "broader_materialization_rerun_allowed_by_this_artifact",
        "full_universe_materialization_allowed",
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

    boundary = packet.get("diagnostic_boundary") or {}
    if boundary.get("diagnostic_id") != "a_long_daily_isolated_window_probe_000001_2018_2025_plus_2022_control":
        raise ValueError("packet diagnostic_id mismatch")
    if boundary.get("fixed_symbol") != FIXED_SYMBOL:
        raise ValueError("packet fixed symbol mismatch")
    if (
        boundary.get("eight_year_window_start_date") != EIGHT_YEAR_START_DATE
        or boundary.get("eight_year_window_end_date") != EIGHT_YEAR_END_DATE
        or boundary.get("control_window_start_date") != CONTROL_START_DATE
        or boundary.get("control_window_end_date") != CONTROL_END_DATE
    ):
        raise ValueError("packet diagnostic date boundary mismatch")
    for field in ["not_full_market", "not_full_universe", "not_broader_panel_rerun", "pass_does_not_make_data_alpha_ready"]:
        if boundary.get(field) is not True:
            raise ValueError(f"packet boundary.{field} must be true")

    expected_calls = [_packet_call_with_flags(call) for call in diagnostic_call_plan()]
    if packet.get("diagnostic_calls") != expected_calls:
        raise ValueError("packet diagnostic calls must stay fixed")

    budget = packet.get("call_budget") or {}
    if budget.get("max_total_endpoint_calls") != MAX_TOTAL_ENDPOINT_CALLS:
        raise ValueError("packet max_total_endpoint_calls must be 2")
    if budget.get("planned_total_endpoint_calls") != PLANNED_TOTAL_ENDPOINT_CALLS:
        raise ValueError("packet planned_total_endpoint_calls must be 2")
    if budget.get("retry_count_allowed") != 0:
        raise ValueError("packet retry_count_allowed must be zero")
    if budget.get("abort_if_budget_exceeded") is not True:
        raise ValueError("packet must abort on budget exceed")

    storage = packet.get("storage_and_checkpoint_boundary") or {}
    if storage.get("raw_output_root") != RAW_ROOT_REL.as_posix() + "/":
        raise ValueError("packet raw output root mismatch")
    if storage.get("tracked_summary_path") != "docs/a_long_tushare_daily_price_route_diagnostic_execution_summary_20260604.json":
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
    if len(diagnostic_call_plan()) != PLANNED_TOTAL_ENDPOINT_CALLS:
        raise ValueError("runner call plan no longer matches packet planned_total_endpoint_calls")
    return packet


def validate_prior_broader_summary(path: Path = PRIOR_BROADER_SUMMARY_PATH) -> dict[str, Any]:
    summary = read_json(path)
    if summary.get("schema_name") != "a_long_tushare_broader_materialization_execution_summary":
        raise ValueError("prior broader materialization summary schema_name mismatch")
    decision = summary.get("decision") or {}
    if decision.get("materialization_status") != "partial_or_failed_full_period_panel_materialization":
        raise ValueError("prior broader summary must be the partial materialization result")
    if decision.get("signal_search_authorized_by_this_summary") is not False:
        raise ValueError("prior broader summary must not authorize signal search")

    daily_results = [
        item
        for item in summary.get("endpoint_results", [])
        if item.get("api_family") == "daily" and item.get("table_id") == "daily_price_adj_factor_dividend"
    ]
    if len(daily_results) != 9:
        raise ValueError("prior broader summary must contain the 9 fixed-panel daily calls")
    if not all(item.get("call_status") == "empty" and item.get("row_count") == 0 for item in daily_results):
        raise ValueError("prior broader daily calls must all be empty before this diagnostic")
    return summary


def validate_raw_root(raw_root: Path) -> None:
    resolved = raw_root.resolve()
    approved = (ROOT / RAW_ROOT_REL).resolve()
    try:
        resolved.relative_to(approved)
    except ValueError as exc:
        raise ValueError("raw output must stay under data/a_long/raw/tushare/daily_price_route_diagnostic_20260604/") from exc
    if not thin_runner.path_is_gitignored_by_policy(raw_root):
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


def diagnostic_decision(results: list[dict[str, Any]], environment_precheck_passed: bool) -> tuple[str, str, str]:
    if not environment_precheck_passed:
        return (
            "not_executed_environment_missing",
            "No data call ran because the Tushare environment was missing.",
            "Set TUSHARE_TOKEN, keep the double gate, and run only this two-call diagnostic.",
        )
    if not results:
        return (
            "not_executed_environment_check_only",
            "No data call ran; this was an environment-only check.",
            "After review and user execute, run only the two fixed daily probes.",
        )

    by_call_id = {result.get("call_id"): result for result in results}
    eight_year = by_call_id.get(EIGHT_YEAR_CALL_ID)
    control = by_call_id.get(CONTROL_CALL_ID)
    if len(results) != PLANNED_TOTAL_ENDPOINT_CALLS or not eight_year or not control:
        return (
            "partial_probe_incomplete",
            "The diagnostic did not produce both required daily probe results. A-long price data still cannot be used.",
            "Fix the incomplete diagnostic execution before any repair, broader pull, audit, or signal search.",
        )

    if any(result.get("call_status") == "error" for result in [eight_year, control]):
        return (
            "daily_probe_error",
            "At least one daily probe errored. A-long price data still cannot be used.",
            "Fix the daily endpoint error before any broader pull, audit, or signal search.",
        )

    eight_year_success = eight_year.get("call_status") == "success" and not eight_year.get("minimum_fields_missing")
    control_success = control.get("call_status") == "success" and not control.get("minimum_fields_missing")
    eight_year_empty = eight_year.get("call_status") == "empty"
    control_empty = control.get("call_status") == "empty"

    if eight_year_success:
        return (
            "eight_year_isolated_returned_rows",
            "The 2018-2025 daily probe returned rows in isolation. The old failure is likely a burst-rate / pacing problem, not a window-size problem.",
            "Create a separate reviewed pacing / rate-limit repair packet before any broader materialization rerun.",
        )
    if eight_year_empty and control_success:
        return (
            "eight_year_empty_control_returned_rows",
            "The 2018-2025 daily probe was empty, but the 2022 control returned rows. The likely problem is an eight-year window / row limit.",
            "Create a separate reviewed chunked-daily repair packet before any broader materialization rerun.",
        )
    if eight_year_empty and control_empty:
        return (
            "both_windows_empty",
            "Both daily probes returned zero rows. The daily endpoint / account / parameter route is still broken.",
            "Repair endpoint parameters or account route before any broader pull, audit, or signal search.",
        )

    return (
        "partial_probe_incomplete",
        "The daily probes did not produce a clean classification. A-long price data still cannot be used.",
        "Fix the diagnostic result quality before any repair, broader pull, audit, or signal search.",
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
    status, plain_result, next_action = diagnostic_decision(results, environment_precheck_passed)
    network_or_reuse = new_network_call_count > 0 or reused_raw_payload_count > 0
    return {
        "schema_name": "a_long_tushare_daily_price_route_diagnostic_execution_summary",
        "schema_version": "1.0.0",
        "generated_at": generated_at,
        "artifact_id": "a_long_tushare_daily_price_route_diagnostic_execution_summary_20260604",
        "packet_ref": "docs/a_long_tushare_daily_price_route_diagnostic_packet_20260604.json",
        "prior_summary_ref": "docs/a_long_tushare_broader_materialization_execution_summary_20260604.json",
        "scope": {
            "phase": "7a_alpha_validation",
            "purpose": "a_long_tushare_daily_price_route_diagnostic_execution",
            "lane_id": "a_long",
            "market": "A-share",
            "research_only": True,
            "provider_family": "tushare_existing_account",
            "provider_call_executed": new_network_call_count > 0,
            "tushare_call_executed": new_network_call_count > 0,
            "data_fetch_executed": new_network_call_count > 0,
            "raw_payload_written_to_gitignored_path": network_or_reuse,
            "tracked_summary_contains_raw_rows": False,
            "tracked_summary_contains_secret": False,
            "daily_price_route_repair_executed": False,
            "broader_materialization_rerun_executed": False,
            "full_market_materialization_executed": False,
            "full_universe_materialization_executed": False,
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
            "summary_path": "docs/a_long_tushare_daily_price_route_diagnostic_execution_summary_20260604.json",
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
        "diagnostic_boundary": {
            "diagnostic_id": "a_long_daily_isolated_window_probe_000001_2018_2025_plus_2022_control",
            "fixed_symbol": FIXED_SYMBOL,
            "eight_year_window_start_date": EIGHT_YEAR_START_DATE,
            "eight_year_window_end_date": EIGHT_YEAR_END_DATE,
            "control_window_start_date": CONTROL_START_DATE,
            "control_window_end_date": CONTROL_END_DATE,
            "not_full_market": True,
            "not_full_universe": True,
            "not_broader_panel_rerun": True,
        },
        "endpoint_results": results,
        "decision": {
            "price_route_diagnostic_status": status,
            "data_can_be_used_for_alpha_now": False,
            "price_route_repair_authorized_by_this_summary": False,
            "broader_materialization_rerun_authorized_by_this_summary": False,
            "audit_rerun_authorized_by_this_summary": False,
            "signal_search_authorized_by_this_summary": False,
            "plain_result": plain_result,
            "next_action": next_action,
        },
        "prohibited_claims": {
            "a_long_data_ready": False,
            "a_long_alpha_found": False,
            "daily_route_repaired": False,
            "broader_materialization_rerun_authorized": False,
            "audit_passed": False,
            "signal_search_authorized": False,
            "full_universe_materialization_done": False,
            "production_ready": False,
            "ship_gate_evidence": False,
            "full_size_allowed": False,
            "datahub_authorized": False,
            "broker_or_order_automation_authorized": False,
        },
        "limitations": [
            "This summary records only two fixed daily diagnostic calls.",
            "Raw rows stay under gitignored data/a_long/raw/ and are not included in the tracked summary.",
            "The result only narrows the failure mode; it does not repair data or authorize a broader rerun.",
            "No full audit, signal search, alpha backtest, DataHub, production, ship-gate, full-size use, or broker/order automation is authorized.",
        ],
    }


def execute_daily_price_route_diagnostic(
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
    validate_prior_broader_summary()
    validate_raw_root(raw_root)
    require_live_execution_confirmations(
        dry_run_env=dry_run_env,
        confirm_independent_review_pass=confirm_independent_review_pass,
        confirm_post_review_execute=confirm_post_review_execute,
    )
    generated = generated_at or iso_now()
    calls = diagnostic_call_plan()
    if len(calls) > MAX_TOTAL_ENDPOINT_CALLS:
        raise ValueError("planned diagnostic calls exceed max budget")

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
        write_json_atomic(summary, summary_path)
        return summary

    pro = pro_factory()
    results: list[dict[str, Any]] = []
    new_network_call_count = 0
    reused_raw_payload_count = 0
    for call in calls:
        result, used_network = thin_runner.execute_call(pro, call, raw_root)
        results.append(result)
        if used_network:
            new_network_call_count += 1
        else:
            reused_raw_payload_count += 1
        if new_network_call_count + reused_raw_payload_count > MAX_TOTAL_ENDPOINT_CALLS:
            raise ValueError("diagnostic execution exceeded max budget")

    summary = build_summary(
        results=results,
        generated_at=generated,
        environment_precheck_passed=True,
        independent_review_confirmed=confirm_independent_review_pass,
        post_review_execute_confirmed=confirm_post_review_execute,
        new_network_call_count=new_network_call_count,
        reused_raw_payload_count=reused_raw_payload_count,
    )
    write_json_atomic(summary, summary_path)
    return summary


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    summary = execute_daily_price_route_diagnostic(
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
                "price_route_diagnostic_status": decision["price_route_diagnostic_status"],
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

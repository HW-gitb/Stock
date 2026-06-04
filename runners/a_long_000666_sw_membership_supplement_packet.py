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

from runners import a_long_tushare_route_validation_packet as route_base


PACKET_PATH = ROOT / "docs" / "a_long_000666_sw_membership_supplement_packet_20260604.json"
SUMMARY_PATH = ROOT / "docs" / "a_long_000666_sw_membership_supplement_execution_summary_20260604.json"
RAW_ROOT_REL = Path("data/a_long/raw/tushare/000666_sw_membership_supplement_20260604")
RAW_ROOT = ROOT / RAW_ROOT_REL
SCHEMA_PATH = ROOT / "schemas" / "a_long_000666_sw_membership_supplement_packet.schema.json"
SUMMARY_SCHEMA_PATH = ROOT / "schemas" / "a_long_000666_sw_membership_supplement_execution_summary.schema.json"
TARGET_SYMBOL = "000666.SZ"
MAX_TOTAL_CALLS = 4
PLANNED_CALLS = 3


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run the reviewed A-long 000666.SZ SW membership supplement packet. "
            "It probes only the remaining delisted-name SW industry source gap; "
            "it does not run signal search or audit rerun."
        )
    )
    parser.add_argument("--packet-path", type=Path, default=PACKET_PATH)
    parser.add_argument("--summary-path", type=Path, default=SUMMARY_PATH)
    parser.add_argument("--raw-root", type=Path, default=RAW_ROOT)
    parser.add_argument("--generated-at", help="Optional deterministic timestamp for tests.")
    parser.add_argument("--dry-run-env", action="store_true", help="Validate packet/env boundary without Tushare calls.")
    parser.add_argument("--confirm-independent-review-pass", action="store_true")
    parser.add_argument("--confirm-post-review-execute", action="store_true")
    return parser.parse_args(argv)


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json_atomic(payload: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f"{path.name}.tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    tmp_path.replace(path)


def validate_json(schema_path: Path, payload: dict[str, Any]) -> None:
    try:
        from jsonschema import Draft7Validator
    except ModuleNotFoundError:
        return
    schema = read_json(schema_path)
    errors = sorted(Draft7Validator(schema).iter_errors(payload), key=lambda error: list(error.path))
    if errors:
        joined = "; ".join(f"{list(error.path)}: {error.message}" for error in errors[:8])
        raise ValueError(f"{schema_path} validation failed: {joined}")


def path_is_gitignored_by_policy(raw_root: Path) -> bool:
    gitignore_path = ROOT / ".gitignore"
    if not gitignore_path.exists():
        return False
    normalized = raw_root.resolve().relative_to(ROOT.resolve()).as_posix().rstrip("/") + "/"
    lines = [
        line.strip().replace("\\", "/")
        for line in gitignore_path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    return "data/a_long/raw/" in lines or "data/a_long/raw/tushare/" in lines or normalized in lines


def validate_raw_root(raw_root: Path) -> None:
    resolved = raw_root.resolve()
    approved = (ROOT / RAW_ROOT_REL).resolve()
    try:
        resolved.relative_to(approved)
    except ValueError as exc:
        raise ValueError("raw output must stay under data/a_long/raw/tushare/000666_sw_membership_supplement_20260604/") from exc
    if not path_is_gitignored_by_policy(raw_root):
        raise ValueError("raw output root is not protected by .gitignore policy")


def require_live_execution_confirmations(
    *,
    dry_run_env: bool,
    confirm_independent_review_pass: bool,
    confirm_post_review_execute: bool,
) -> None:
    if dry_run_env:
        return
    if not confirm_independent_review_pass or not confirm_post_review_execute:
        raise RuntimeError("live supplement execution requires independent review pass and post-review user execute confirmation")


def supplement_call_plan() -> list[dict[str, Any]]:
    return [
        {
            "call_id": "stock_basic_000666_delisted_context",
            "component_id": "delisted_symbol_context",
            "api_family": "stock_basic",
            "method": "stock_basic",
            "kwargs": {
                "exchange": "",
                "list_status": "D",
                "fields": "ts_code,symbol,name,exchange,market,list_status,list_date,delist_date",
            },
            "required_fields": ["ts_code", "name", "list_status", "list_date", "delist_date"],
            "target_match_field": "ts_code",
        },
        {
            "call_id": "index_member_000666_ts_code_filter",
            "component_id": "sw_membership_candidate",
            "api_family": "index_member",
            "method": "index_member",
            "kwargs": {
                "ts_code": TARGET_SYMBOL,
                "fields": "index_code,con_code,in_date,out_date,is_new",
            },
            "required_fields": ["index_code", "con_code", "in_date", "out_date"],
            "target_match_field": "con_code",
        },
        {
            "call_id": "index_member_all_000666_ts_code_filter",
            "component_id": "sw_membership_candidate",
            "api_family": "index_member_all",
            "method": "index_member_all",
            "kwargs": {
                "ts_code": TARGET_SYMBOL,
                "fields": "ts_code,name,l1_code,l1_name,l2_code,l2_name,in_date,out_date,is_new",
            },
            "required_fields": ["ts_code", "l2_code", "l2_name", "in_date", "out_date"],
            "target_match_field": "ts_code",
        },
    ]


def load_and_validate_packet(path: Path = PACKET_PATH) -> dict[str, Any]:
    packet = read_json(path)
    validate_json(SCHEMA_PATH, packet)
    if packet.get("schema_name") != "a_long_000666_sw_membership_supplement_packet":
        raise ValueError("packet schema_name mismatch")
    target = packet.get("target") or {}
    if target.get("symbol") != TARGET_SYMBOL:
        raise ValueError("packet target symbol must stay 000666.SZ")
    budget = packet.get("call_budget") or {}
    if budget.get("max_total_endpoint_calls") != MAX_TOTAL_CALLS:
        raise ValueError("packet max_total_endpoint_calls mismatch")
    if budget.get("planned_total_endpoint_calls") != PLANNED_CALLS:
        raise ValueError("packet planned_total_endpoint_calls mismatch")
    if budget.get("retry_count_allowed") != 0 or budget.get("abort_if_budget_exceeded") is not True:
        raise ValueError("packet retry policy must stay zero-retry and abort-on-budget")
    scope = packet.get("scope") or {}
    for field in [
        "provider_calls_executed_by_this_artifact",
        "tushare_calls_executed_by_this_artifact",
        "raw_payloads_read_by_this_artifact",
        "signal_search_allowed",
        "audit_rerun_allowed_by_this_artifact",
        "production_use_allowed",
        "ship_gate_claim_allowed",
        "full_size_manual_use_allowed",
        "broker_or_order_automation_allowed",
    ]:
        if scope.get(field) is not False:
            raise ValueError(f"packet scope.{field} must stay false")
    gates = packet.get("pre_execution_gates") or {}
    for field, value in gates.items():
        if value is not True:
            raise ValueError(f"packet gate must stay true: {field}")
    if packet.get("call_plan") != supplement_call_plan():
        raise ValueError("packet call_plan no longer matches runner")
    return packet


def raw_payload_path(raw_root: Path, call_id: str) -> Path:
    safe = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in call_id)
    return raw_root / f"{safe}.json"


def write_raw_payload(raw_root: Path, call_id: str, payload: dict[str, Any]) -> str:
    path = raw_payload_path(raw_root, call_id)
    write_json_atomic(payload, path)
    return path.resolve().relative_to(ROOT.resolve()).as_posix()


def normalize_records(value: Any) -> tuple[list[str], int | None, list[dict[str, Any]]]:
    return route_base.normalize_records(value)


def call_status(row_count: int | None) -> str:
    return "success" if row_count and row_count > 0 else "empty"


def count_target_matches(records: list[dict[str, Any]], target_match_field: str) -> int:
    return sum(1 for row in records if str(row.get(target_match_field)) == TARGET_SYMBOL)


def execute_call(pro: Any, call: dict[str, Any], raw_root: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    request_shape_without_token = dict(call["kwargs"])
    try:
        value = getattr(pro, call["method"])(**call["kwargs"])
        columns, row_count, records = normalize_records(value)
        present = [field for field in call["required_fields"] if field in columns]
        missing = [field for field in call["required_fields"] if field not in columns]
        target_match_count = count_target_matches(records, call["target_match_field"])
        raw_ref = write_raw_payload(
            raw_root,
            call["call_id"],
            {
                "call_id": call["call_id"],
                "api_family": call["api_family"],
                "request_shape_without_token": request_shape_without_token,
                "call_status": call_status(row_count),
                "row_count": row_count,
                "columns": columns,
                "records": records,
            },
        )
        return (
            {
                "call_id": call["call_id"],
                "component_id": call["component_id"],
                "api_family": call["api_family"],
                "request_shape_without_token": request_shape_without_token,
                "call_status": call_status(row_count),
                "row_count": row_count,
                "columns": columns,
                "required_fields_present": present,
                "required_fields_missing": missing,
                "target_symbol": TARGET_SYMBOL,
                "target_match_field": call["target_match_field"],
                "target_match_count": target_match_count,
                "raw_payload_ref": raw_ref,
                "tracked_summary_excludes_raw_rows": True,
                "error_class": None,
                "error_message_redacted": None,
            },
            records,
        )
    except Exception as exc:
        raw_ref = write_raw_payload(
            raw_root,
            call["call_id"],
            {
                "call_id": call["call_id"],
                "api_family": call["api_family"],
                "request_shape_without_token": request_shape_without_token,
                "call_status": "error",
                "error_class": type(exc).__name__,
                "error_message_redacted": route_base.redact_error(exc),
            },
        )
        return (
            {
                "call_id": call["call_id"],
                "component_id": call["component_id"],
                "api_family": call["api_family"],
                "request_shape_without_token": request_shape_without_token,
                "call_status": "error",
                "row_count": None,
                "columns": [],
                "required_fields_present": [],
                "required_fields_missing": list(call["required_fields"]),
                "target_symbol": TARGET_SYMBOL,
                "target_match_field": call["target_match_field"],
                "target_match_count": 0,
                "raw_payload_ref": raw_ref,
                "tracked_summary_excludes_raw_rows": True,
                "error_class": type(exc).__name__,
                "error_message_redacted": route_base.redact_error(exc),
            },
            [],
        )


def build_summary(
    *,
    results: list[dict[str, Any]],
    generated_at: str,
    environment_precheck_passed: bool,
    network_call_attempted: bool,
) -> dict[str, Any]:
    membership_results = [item for item in results if item["component_id"] == "sw_membership_candidate"]
    candidate_found = any(
        item["call_status"] == "success"
        and item["target_match_count"] > 0
        and not item["required_fields_missing"]
        for item in membership_results
    )
    any_errors = any(item["call_status"] == "error" for item in results)
    any_missing_required = any(item["required_fields_missing"] for item in membership_results if item["call_status"] == "success")

    if not network_call_attempted and environment_precheck_passed:
        status = "dry_run_environment_ready"
        plain = "Dry-run only: the environment boundary is ready, but no Tushare call was executed."
        next_action = "After independent review passes, the user must issue a separate execute command before the fixed supplement probe can run."
    elif not environment_precheck_passed:
        status = "not_executed_environment_missing"
        plain = "No supplement probe ran because the Tushare environment is missing."
        next_action = "After TUSHARE_TOKEN is available, independent review and a separate user execute command are still required."
    elif candidate_found:
        status = "candidate_sw_membership_source_found"
        plain = "A candidate SW membership source for 000666.SZ was found, but A-long still cannot search for alpha."
        next_action = "Next, wire the reviewed raw source into an audit repair and rerun the full-period data-integrity audit."
    elif any_errors or any_missing_required:
        status = "partial_or_failed_supplement_probe"
        plain = "The 000666.SZ SW membership supplement probe did not produce usable evidence; A-long still cannot search for alpha."
        next_action = "Decide whether to try a different reviewed Tushare endpoint/parameter set or keep industry-normalized A-long signal search blocked."
    else:
        status = "no_candidate_sw_membership_source_found"
        plain = "No SW membership source for 000666.SZ was found; A-long still cannot search for alpha."
        next_action = "Use another reviewed data source or explicitly keep delisted-name industry normalization blocked."

    return {
        "schema_name": "a_long_000666_sw_membership_supplement_execution_summary",
        "schema_version": "1.0.0",
        "generated_at": generated_at,
        "artifact_id": "a_long_000666_sw_membership_supplement_execution_summary_20260604",
        "packet_ref": "docs/a_long_000666_sw_membership_supplement_packet_20260604.json",
        "scope": {
            "phase": "7a_alpha_validation",
            "purpose": "a_long_000666_sw_membership_supplement_execution",
            "lane_id": "a_long",
            "market": "A-share",
            "research_only": True,
            "single_symbol_supplement_only": True,
            "target_symbol": TARGET_SYMBOL,
            "provider_family": "tushare_existing_account",
            "provider_call_executed": network_call_attempted,
            "tushare_call_executed": network_call_attempted,
            "data_fetch_executed": network_call_attempted,
            "raw_payload_written_to_gitignored_path": network_call_attempted,
            "tracked_summary_contains_raw_rows": False,
            "tracked_summary_contains_secret": False,
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
            "summary_path": "docs/a_long_000666_sw_membership_supplement_execution_summary_20260604.json",
            "raw_output_root": RAW_ROOT_REL.as_posix() + "/",
            "raw_output_root_is_gitignored": True,
            "max_total_calls": MAX_TOTAL_CALLS,
            "planned_call_count": PLANNED_CALLS,
            "actual_call_count": len(results),
            "budget_exceeded": False,
            "network_call_attempted": network_call_attempted,
            "environment_precheck_passed": environment_precheck_passed,
            "token_logged": False,
            "request_url_logged": False,
        },
        "target": {
            "symbol": TARGET_SYMBOL,
            "remaining_audit_blocker": "missing_sw_membership_for_delisted_sample",
            "existing_materialized_membership_row_count_for_target": 0,
        },
        "endpoint_results": results,
        "decision": {
            "supplement_status": status,
            "candidate_sw_membership_source_found": candidate_found,
            "data_can_be_used_for_alpha_now": False,
            "audit_rerun_authorized_by_this_summary": False,
            "signal_search_authorized_by_this_summary": False,
            "plain_result": plain,
            "next_action": next_action,
        },
        "prohibited_claims": {
            "a_long_data_ready": False,
            "a_long_alpha_found": False,
            "sw_membership_gap_closed_by_packet_artifact": False,
            "signal_search_authorized": False,
            "audit_rerun_authorized": False,
            "production_ready": False,
            "ship_gate_evidence": False,
            "full_size_allowed": False,
            "provider_selected": False,
            "datahub_authorized": False,
            "broker_or_order_automation_authorized": False,
        },
        "limitations": [
            "This is a single-symbol supplement probe for 000666.SZ only.",
            "Tracked summary stores shape and counts only; raw rows stay under gitignored data/a_long/raw/.",
            "A found candidate source still requires a separate reviewed audit repair and full-period audit rerun.",
            "No signal search, alpha backtest, production use, ship-gate claim, full-size use, or broker/order automation is authorized.",
        ],
    }


def execute_supplement(
    *,
    pro_factory: Callable[[], Any] = route_base.get_tushare_client,
    packet_path: Path = PACKET_PATH,
    raw_root: Path = RAW_ROOT,
    summary_path: Path = SUMMARY_PATH,
    generated_at: str | None = None,
    dry_run_env: bool = False,
    confirm_independent_review_pass: bool = False,
    confirm_post_review_execute: bool = False,
) -> dict[str, Any]:
    load_and_validate_packet(packet_path)
    validate_raw_root(raw_root)
    require_live_execution_confirmations(
        dry_run_env=dry_run_env,
        confirm_independent_review_pass=confirm_independent_review_pass,
        confirm_post_review_execute=confirm_post_review_execute,
    )
    generated = generated_at or iso_now()

    if dry_run_env:
        summary = build_summary(
            results=[],
            generated_at=generated,
            environment_precheck_passed=bool(os.environ.get("TUSHARE_TOKEN")),
            network_call_attempted=False,
        )
        validate_json(SUMMARY_SCHEMA_PATH, summary)
        write_json_atomic(summary, summary_path)
        return summary

    if pro_factory is route_base.get_tushare_client and not os.environ.get("TUSHARE_TOKEN"):
        summary = build_summary(
            results=[],
            generated_at=generated,
            environment_precheck_passed=False,
            network_call_attempted=False,
        )
        validate_json(SUMMARY_SCHEMA_PATH, summary)
        write_json_atomic(summary, summary_path)
        return summary

    pro = pro_factory()
    results: list[dict[str, Any]] = []
    for call in supplement_call_plan():
        result, _records = execute_call(pro, call, raw_root)
        results.append(result)
    if len(results) > MAX_TOTAL_CALLS:
        raise ValueError("000666 SW membership supplement call budget exceeded")

    summary = build_summary(
        results=results,
        generated_at=generated,
        environment_precheck_passed=True,
        network_call_attempted=True,
    )
    validate_json(SUMMARY_SCHEMA_PATH, summary)
    write_json_atomic(summary, summary_path)
    return summary


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    summary = execute_supplement(
        packet_path=args.packet_path,
        raw_root=args.raw_root,
        summary_path=args.summary_path,
        generated_at=args.generated_at,
        dry_run_env=args.dry_run_env,
        confirm_independent_review_pass=args.confirm_independent_review_pass,
        confirm_post_review_execute=args.confirm_post_review_execute,
    )
    decision = summary["decision"]
    print(
        json.dumps(
            {
                "supplement_status": decision["supplement_status"],
                "plain_result": decision["plain_result"],
                "next_action": decision["next_action"],
                "actual_call_count": summary["execution"]["actual_call_count"],
                "summary_path": summary["execution"]["summary_path"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

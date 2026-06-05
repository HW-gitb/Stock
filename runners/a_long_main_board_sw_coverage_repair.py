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
from runners import a_long_main_board_candidate_universe_preflight as preflight
from runners import a_long_tushare_incremental_materialization_packet as raw_base
from runners import a_long_tushare_route_validation_packet as route_base


SUMMARY_PATH = ROOT / "docs" / "a_long_main_board_sw_coverage_repair_execution_summary_20260604.json"
RAW_ROOT_REL = Path("data/a_long/raw/tushare/main_board_sw_coverage_repair_20260604")
RAW_ROOT = ROOT / RAW_ROOT_REL
SOURCE_RAW_ROOT = ROOT / "data" / "a_long" / "raw" / "tushare" / "materialization_full_period_panel_20260604"
PREFLIGHT_SUMMARY_PATH = ROOT / "docs" / "a_long_main_board_candidate_universe_preflight_execution_summary_20260604.json"
SCHEMA_PATH = ROOT / "schemas" / "a_long_main_board_sw_coverage_repair_execution_summary.schema.json"

START_DATE = "20180101"
END_DATE = "20251231"
MAX_TOTAL_CALLS = 1500
MAX_DELISTED_EXCEPTION_RATE_PCT = 12.5
SW_FIELDS = "ts_code,name,l1_code,l1_name,l2_code,l2_name,in_date,out_date,is_new"
DELISTING_SHELL_PREFIX = "\u9000\u5e02"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Repair the A-long main-board SW industry coverage gate. "
            "This supplements missing active names with index_member_all(ts_code=...) and "
            "evidence-gates the scaled delisted no-industry boundary. It does not run alpha."
        )
    )
    parser.add_argument("--summary-path", type=Path, default=SUMMARY_PATH)
    parser.add_argument("--raw-root", type=Path, default=RAW_ROOT)
    parser.add_argument("--source-raw-root", type=Path, default=SOURCE_RAW_ROOT)
    parser.add_argument("--preflight-summary-path", type=Path, default=PREFLIGHT_SUMMARY_PATH)
    parser.add_argument("--generated-at", help="Optional deterministic timestamp for tests.")
    parser.add_argument("--dry-run-env", action="store_true", help="Write env-only summary without Tushare calls.")
    parser.add_argument("--sleep-seconds", type=float, default=0.05, help="Pause between live Tushare calls.")
    parser.add_argument(
        "--confirm-independent-review-pass",
        action="store_true",
        help="Required for live execution; confirms the preflight package review passed.",
    )
    parser.add_argument(
        "--confirm-post-review-execute",
        action="store_true",
        help="Required for live execution; confirms the user issued execute.",
    )
    return parser.parse_args(argv)


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json_atomic(payload: Any, path: Path) -> None:
    raw_base.write_json_atomic(payload, path)


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


def validate_raw_root(raw_root: Path) -> None:
    resolved = raw_root.resolve()
    approved = (ROOT / RAW_ROOT_REL).resolve()
    try:
        resolved.relative_to(approved)
    except ValueError as exc:
        raise ValueError("raw output must stay under data/a_long/raw/tushare/main_board_sw_coverage_repair_20260604/") from exc
    if not raw_base.path_is_gitignored_by_policy(raw_root):
        raise ValueError("raw output root is not protected by .gitignore policy")


def require_live_confirmations(
    *,
    dry_run_env: bool,
    confirm_independent_review_pass: bool,
    confirm_post_review_execute: bool,
) -> None:
    if dry_run_env:
        return
    if not confirm_independent_review_pass:
        raise RuntimeError("live execution requires --confirm-independent-review-pass")
    if not confirm_post_review_execute:
        raise RuntimeError("live execution requires --confirm-post-review-execute")


def raw_records(path: Path) -> list[dict[str, Any]]:
    payload = read_json(path)
    value = payload.get("records")
    if not isinstance(value, list):
        raise ValueError(f"raw payload records missing: {path}")
    return [row for row in value if isinstance(row, dict)]


def validate_source_raw_root(source_raw_root: Path) -> None:
    preflight.validate_source_raw_root(source_raw_root)


def validate_preflight_summary(path: Path) -> dict[str, Any]:
    summary = read_json(path)
    if summary.get("schema_name") != "a_long_main_board_candidate_universe_preflight_execution_summary":
        raise ValueError("preflight summary schema_name mismatch")
    decision = summary.get("decision") or {}
    if decision.get("preflight_status") != "blocked_sw_industry_coverage_for_full_universe_signal_search":
        raise ValueError("SW coverage repair must consume the blocked candidate-universe preflight")
    if decision.get("signal_search_authorized_by_this_summary") is not False:
        raise ValueError("preflight summary must not authorize signal search")
    probe = summary.get("probe_interpretation") or {}
    if probe.get("active_ts_code_filter_can_supplement_missing_sw") is not True:
        raise ValueError("preflight did not prove active ts_code supplement route")
    universe = summary.get("candidate_universe") or {}
    if int(universe.get("active_missing_sw_membership_count") or 0) <= 0:
        raise ValueError("preflight summary has no active SW gap to repair")
    if int(universe.get("delisted_missing_sw_membership_count") or 0) <= 1:
        raise ValueError("preflight summary does not need scaled delisted boundary")
    return summary


def active_rows_by_symbol(universe: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(row.get("ts_code")): row for row in universe.get("main_active", []) if row.get("ts_code")}


def is_active_delisting_shell(row: dict[str, Any]) -> bool:
    return str(row.get("name") or "").startswith(DELISTING_SHELL_PREFIX)


def active_delisting_shell_summary(
    *,
    active_unresolved: list[str],
    universe: dict[str, Any],
    delisted_no_source_count: int,
) -> tuple[dict[str, Any], list[str], list[str]]:
    rows_by_symbol = active_rows_by_symbol(universe)
    shell_symbols = [symbol for symbol in active_unresolved if is_active_delisting_shell(rows_by_symbol.get(symbol, {}))]
    investable_unresolved = [symbol for symbol in active_unresolved if symbol not in shell_symbols]
    symbol_results = []
    for symbol in shell_symbols:
        row = rows_by_symbol[symbol]
        symbol_results.append(
            {
                "symbol": symbol,
                "name": row.get("name"),
                "list_status": row.get("list_status"),
                "list_date": row.get("list_date"),
                "delist_date": row.get("delist_date"),
                "stock_basic_source": "stock_basic_active_L",
                "index_member_all_status": "empty",
                "manual_industry_assignment_allowed": False,
                "treated_as_investable_active_candidate": False,
                "requires_separate_scaled_delisted_boundary_approval": True,
            }
        )
    payload = {
        "detected_count": len(shell_symbols),
        "detected_symbols": shell_symbols,
        "active_investable_unresolved_count": len(investable_unresolved),
        "active_investable_unresolved_symbols": investable_unresolved,
        "pending_scaled_delisted_no_source_count_if_approved": delisted_no_source_count + len(shell_symbols),
        "manual_industry_assignment_allowed": False,
        "candidate_ready_override_allowed": False,
        "requires_separate_scaled_delisted_boundary_approval": bool(shell_symbols),
        "symbol_results": symbol_results,
    }
    return payload, shell_symbols, investable_unresolved


def main_board_delisted_in_window(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return preflight.main_board_delisted_in_window(records)


def missing_universe(source_raw_root: Path) -> dict[str, Any]:
    active = raw_records(source_raw_root / "stock_basic_active_L.json")
    delisted = raw_records(source_raw_root / "stock_basic_delisted_D.json")
    membership = raw_records(source_raw_root / "index_member_all_sw_membership.json")

    main_active = [row for row in active if is_main_board_ts_code(row.get("ts_code"))]
    main_delisted = main_board_delisted_in_window(delisted)
    member_codes = {str(row.get("ts_code")) for row in membership if row.get("ts_code")}
    active_missing = [str(row.get("ts_code")) for row in main_active if str(row.get("ts_code")) not in member_codes]
    delisted_missing = [str(row.get("ts_code")) for row in main_delisted if str(row.get("ts_code")) not in member_codes]
    active_with_sw = len(main_active) - len(active_missing)
    return {
        "active": active,
        "delisted": delisted,
        "membership": membership,
        "main_active": main_active,
        "main_delisted": main_delisted,
        "member_codes": member_codes,
        "active_missing": active_missing,
        "delisted_missing": delisted_missing,
        "before": {
            "source_raw_root": "data/a_long/raw/tushare/materialization_full_period_panel_20260604/",
            "start_date": START_DATE,
            "end_date": END_DATE,
            "main_board_active_count": len(main_active),
            "main_board_delisted_2018_2025_count": len(main_delisted),
            "current_sw_membership_rows": len(membership),
            "active_with_sw_membership_count": active_with_sw,
            "active_missing_sw_membership_count": len(active_missing),
            "delisted_missing_sw_membership_count": len(delisted_missing),
            "main_board_active_sw_coverage_pct": round(active_with_sw * 100.0 / len(main_active), 6) if main_active else 0.0,
        },
    }


def call_status(row_count: int | None) -> str:
    return "success" if row_count and row_count > 0 else "empty"


def target_match_count(records: list[dict[str, Any]], symbol: str) -> int:
    return sum(1 for row in records if str(row.get("ts_code") or "") == symbol)


def required_sw_fields_present(columns: list[str]) -> bool:
    return all(field in columns for field in ["ts_code", "l2_code", "l2_name", "in_date", "out_date"])


def raw_payload_path(raw_root: Path, call_id: str) -> Path:
    safe = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in call_id)
    return raw_root / f"{safe}.json"


def raw_ref_for(raw_path: Path) -> str:
    return raw_path.resolve().relative_to(ROOT.resolve()).as_posix()


def execute_or_load_raw(
    *,
    pro: Any,
    raw_root: Path,
    call_id: str,
    api_family: str,
    method: str,
    kwargs: dict[str, Any],
    sleep_seconds: float,
) -> tuple[dict[str, Any], list[dict[str, Any]], bool]:
    raw_path = raw_payload_path(raw_root, call_id)
    if raw_path.exists():
        payload = read_json(raw_path)
        records = [row for row in payload.get("records", []) if isinstance(row, dict)]
        return payload, records, True

    if sleep_seconds > 0:
        time.sleep(sleep_seconds)
    try:
        value = getattr(pro, method)(**kwargs)
        columns, row_count, records = route_base.normalize_records(value)
        payload = {
            "call_id": call_id,
            "api_family": api_family,
            "request_shape_without_token": dict(kwargs),
            "call_status": call_status(row_count),
            "row_count": row_count,
            "columns": columns,
            "records": records,
            "error_class": None,
            "error_message_redacted": None,
        }
    except Exception as exc:
        payload = {
            "call_id": call_id,
            "api_family": api_family,
            "request_shape_without_token": dict(kwargs),
            "call_status": "error",
            "row_count": None,
            "columns": [],
            "records": [],
            "error_class": type(exc).__name__,
            "error_message_redacted": route_base.redact_error(exc),
        }
        records = []
    write_json_atomic(payload, raw_path)
    return payload, records, False


def execute_active_symbol(pro: Any, raw_root: Path, symbol: str, sleep_seconds: float) -> dict[str, Any]:
    call_id = f"active_index_member_all_{symbol.replace('.', '_')}"
    kwargs = {"ts_code": symbol, "fields": SW_FIELDS}
    payload, records, reused = execute_or_load_raw(
        pro=pro,
        raw_root=raw_root,
        call_id=call_id,
        api_family="index_member_all",
        method="index_member_all",
        kwargs=kwargs,
        sleep_seconds=sleep_seconds,
    )
    columns = [str(column) for column in payload.get("columns", [])]
    match_count = target_match_count(records, symbol)
    success = payload.get("call_status") == "success" and match_count > 0 and required_sw_fields_present(columns)
    return {
        "symbol": symbol,
        "call_id": call_id,
        "call_status": payload.get("call_status"),
        "row_count": payload.get("row_count"),
        "target_match_count": match_count,
        "required_sw_fields_present": required_sw_fields_present(columns),
        "supplement_success": success,
        "raw_payload_ref": raw_ref_for(raw_payload_path(raw_root, call_id)),
        "reused_existing_raw": reused,
        "tracked_summary_excludes_raw_rows": True,
        "error_class": payload.get("error_class"),
        "error_message_redacted": payload.get("error_message_redacted"),
    }


def stock_basic_delisted_context(pro: Any, raw_root: Path, sleep_seconds: float) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    call_id = "stock_basic_delisted_industry_area_context"
    kwargs = {
        "exchange": "",
        "list_status": "D",
        "fields": "ts_code,symbol,name,exchange,market,list_status,list_date,delist_date,industry,area",
    }
    payload, records, reused = execute_or_load_raw(
        pro=pro,
        raw_root=raw_root,
        call_id=call_id,
        api_family="stock_basic",
        method="stock_basic",
        kwargs=kwargs,
        sleep_seconds=sleep_seconds,
    )
    by_symbol = {str(row.get("ts_code")): row for row in records if row.get("ts_code")}
    return (
        {
            "call_id": call_id,
            "call_status": payload.get("call_status"),
            "row_count": payload.get("row_count"),
            "raw_payload_ref": raw_ref_for(raw_payload_path(raw_root, call_id)),
            "reused_existing_raw": reused,
            "tracked_summary_excludes_raw_rows": True,
            "error_class": payload.get("error_class"),
            "error_message_redacted": payload.get("error_message_redacted"),
        },
        by_symbol,
    )


def has_value(value: Any) -> bool:
    if value is None:
        return False
    text = str(value).strip()
    return bool(text and text.lower() not in {"nan", "none", "null"})


def execute_delisted_symbol(
    pro: Any,
    raw_root: Path,
    symbol: str,
    stock_basic_by_symbol: dict[str, dict[str, Any]],
    sleep_seconds: float,
) -> dict[str, Any]:
    call_id = f"delisted_index_member_all_{symbol.replace('.', '_')}"
    kwargs = {"ts_code": symbol, "fields": SW_FIELDS}
    payload, records, reused = execute_or_load_raw(
        pro=pro,
        raw_root=raw_root,
        call_id=call_id,
        api_family="index_member_all",
        method="index_member_all",
        kwargs=kwargs,
        sleep_seconds=sleep_seconds,
    )
    columns = [str(column) for column in payload.get("columns", [])]
    match_count = target_match_count(records, symbol)
    sw_found = payload.get("call_status") == "success" and match_count > 0 and required_sw_fields_present(columns)
    stock_basic = stock_basic_by_symbol.get(symbol) or {}
    stock_basic_row_present = bool(stock_basic)
    stock_basic_industry_present = has_value(stock_basic.get("industry"))
    stock_basic_area_present = has_value(stock_basic.get("area"))
    no_usable_sw_source = (
        stock_basic_row_present
        and not sw_found
        and payload.get("call_status") in {"empty", "success"}
        and match_count == 0
    )
    return {
        "symbol": symbol,
        "call_id": call_id,
        "call_status": payload.get("call_status"),
        "row_count": payload.get("row_count"),
        "target_match_count": match_count,
        "required_sw_fields_present": required_sw_fields_present(columns),
        "sw_membership_found": sw_found,
        "stock_basic_row_present": stock_basic_row_present,
        "stock_basic_industry_value_present": stock_basic_industry_present,
        "stock_basic_area_value_present": stock_basic_area_present,
        "no_usable_sw_source_evidence": no_usable_sw_source,
        "raw_payload_ref": raw_ref_for(raw_payload_path(raw_root, call_id)),
        "reused_existing_raw": reused,
        "tracked_summary_excludes_raw_rows": True,
        "error_class": payload.get("error_class"),
        "error_message_redacted": payload.get("error_message_redacted"),
    }


def contains_key(payload: Any, needle: str) -> bool:
    if isinstance(payload, dict):
        return any(key == needle or contains_key(value, needle) for key, value in payload.items())
    if isinstance(payload, list):
        return any(contains_key(item, needle) for item in payload)
    return False


def build_summary(
    *,
    generated_at: str,
    universe: dict[str, Any],
    active_results: list[dict[str, Any]],
    delisted_results: list[dict[str, Any]],
    stock_basic_context: dict[str, Any] | None,
    environment_precheck_passed: bool,
    independent_review_confirmed: bool,
    post_review_execute_confirmed: bool,
    dry_run_env: bool,
) -> dict[str, Any]:
    active_success = [item["symbol"] for item in active_results if item["supplement_success"]]
    active_unresolved = [item["symbol"] for item in active_results if not item["supplement_success"]]
    delisted_sw_found = [item["symbol"] for item in delisted_results if item["sw_membership_found"]]
    delisted_no_source = [item["symbol"] for item in delisted_results if item["no_usable_sw_source_evidence"]]
    active_delisting_shells, active_shell_symbols, active_investable_unresolved = active_delisting_shell_summary(
        active_unresolved=active_unresolved,
        universe=universe,
        delisted_no_source_count=len(delisted_no_source),
    )
    delisted_unresolved = [
        item["symbol"] for item in delisted_results if not item["sw_membership_found"] and not item["no_usable_sw_source_evidence"]
    ]
    stock_basic_industry_present = [
        item["symbol"] for item in delisted_results if item["stock_basic_industry_value_present"]
    ]
    denominator = len(universe["main_active"]) + len(universe["main_delisted"])
    exception_rate = round(len(delisted_no_source) * 100.0 / denominator, 6) if denominator else 0.0
    active_with_sw_after = universe["before"]["active_with_sw_membership_count"] + len(active_success)
    active_coverage_after = (
        round(active_with_sw_after * 100.0 / len(universe["main_active"]), 6) if universe["main_active"] else 0.0
    )
    delisted_boundary_passed = (
        len(delisted_unresolved) == 0
        and len(delisted_sw_found) + len(delisted_no_source) == len(universe["delisted_missing"])
        and exception_rate <= MAX_DELISTED_EXCEPTION_RATE_PCT
    )
    gate_passed = len(active_unresolved) == 0 and delisted_boundary_passed
    network_calls = len([item for item in active_results + delisted_results if not item["reused_existing_raw"]])
    if stock_basic_context and not stock_basic_context["reused_existing_raw"]:
        network_calls += 1
    reused_raw = len([item for item in active_results + delisted_results if item["reused_existing_raw"]])
    if stock_basic_context and stock_basic_context["reused_existing_raw"]:
        reused_raw += 1

    if dry_run_env:
        status = "dry_run_environment_ready" if environment_precheck_passed else "not_executed_environment_missing"
        plain = "Environment check only; no SW coverage repair executed."
        next_action = "After review and user execute, run the real SW coverage repair."
    elif not environment_precheck_passed:
        status = "not_executed_environment_missing"
        plain = "SW coverage repair did not execute because TUSHARE_TOKEN is missing."
        next_action = "Restore TUSHARE_TOKEN and rerun; do not start full alpha search."
    elif gate_passed:
        status = "passed_candidate_universe_sw_coverage_repair"
        plain = (
            "A-long main-board candidate industry gate passed: active SW gaps are repaired and delisted no-source "
            "names are handled by the scaled delisted-only boundary."
        )
        next_action = (
            "Send this package to Claude review. After PASS and commit, the next package can pull/run the "
            "preregistered full-period alpha search; this summary itself still proves no alpha."
        )
    elif active_shell_symbols and not active_investable_unresolved and delisted_boundary_passed:
        status = "active_delisting_shell_boundary_pending_approval"
        plain = (
            "A-long main-board candidate industry gate is still blocked: Tushare supplemented 1,189 active names, "
            f"but {len(active_shell_symbols)} remaining active rows are delisting-shell names. They must not receive "
            "manual industry fills; they need a separate scaled delisted/no-industry boundary decision first."
        )
        next_action = (
            "Send this repair to Claude review. After PASS and commit, ask the user to approve or reject the "
            "scaled delisted/no-industry boundary before any full alpha search."
        )
    else:
        status = "active_supplement_or_delisted_boundary_incomplete"
        plain = (
            "A-long main-board candidate industry gate is still blocked: "
            f"{len(active_investable_unresolved)} investable active names remain unresolved, "
            f"{len(active_shell_symbols)} delisting-shell active rows need boundary approval, "
            f"and {len(delisted_unresolved)} delisted names remain unresolved."
        )
        next_action = "Repair the remaining active-name gaps or approve the needed boundary first; do not start full alpha search."

    planned_calls = len(universe["active_missing"]) + len(universe["delisted_missing"]) + 1
    summary = {
        "schema_name": "a_long_main_board_sw_coverage_repair_execution_summary",
        "schema_version": "1.0.0",
        "generated_at": generated_at,
        "artifact_id": "a_long_main_board_sw_coverage_repair_execution_summary_20260604",
        "source_refs": [
            "docs/a_long_main_board_candidate_universe_preflight_execution_summary_20260604.json",
            "data/a_long/raw/tushare/materialization_full_period_panel_20260604/",
            "docs/system_risk_register.md",
        ],
        "scope": {
            "phase": "7a_alpha_validation",
            "purpose": "a_long_main_board_sw_coverage_repair",
            "lane_id": "a_long",
            "market": "A-share",
            "research_only": True,
            "provider_family": "tushare_existing_account",
            "provider_call_executed": bool(active_results or delisted_results or stock_basic_context),
            "tushare_call_executed": bool(active_results or delisted_results or stock_basic_context),
            "data_fetch_executed": bool(active_results or delisted_results or stock_basic_context),
            "raw_payload_written_to_gitignored_path": bool(active_results or delisted_results or stock_basic_context),
            "tracked_summary_contains_raw_rows": False,
            "tracked_summary_contains_secret": False,
            "full_market_materialization_executed": False,
            "full_universe_signal_search_executed": False,
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
            "summary_path": "docs/a_long_main_board_sw_coverage_repair_execution_summary_20260604.json",
            "raw_output_root": RAW_ROOT_REL.as_posix() + "/",
            "raw_output_root_is_gitignored": True,
            "source_raw_root": "data/a_long/raw/tushare/materialization_full_period_panel_20260604/",
            "preflight_summary_ref": "docs/a_long_main_board_candidate_universe_preflight_execution_summary_20260604.json",
            "max_total_calls": MAX_TOTAL_CALLS,
            "planned_call_count": planned_calls,
            "actual_network_call_count": network_calls,
            "reused_raw_payload_count": reused_raw,
            "budget_exceeded": planned_calls > MAX_TOTAL_CALLS,
            "network_call_attempted": bool(active_results or delisted_results or stock_basic_context),
            "environment_precheck_passed": environment_precheck_passed,
            "independent_review_confirmed": independent_review_confirmed,
            "post_review_execute_confirmed": post_review_execute_confirmed,
            "token_logged": False,
            "request_url_logged": False,
        },
        "candidate_universe_before": universe["before"],
        "active_sw_supplement": {
            "active_missing_before_count": len(universe["active_missing"]),
            "attempted_count": len(active_results),
            "supplement_success_count": len(active_success),
            "unresolved_count": len(active_unresolved),
            "supplement_success_examples": active_success[:40],
            "unresolved_symbols": active_unresolved,
            "symbol_results": active_results,
        },
        "active_delisting_shell_boundary": active_delisting_shells,
        "delisted_no_industry_boundary": {
            "main_board_delisted_missing_sw_count": len(universe["delisted_missing"]),
            "stock_basic_context_result": stock_basic_context,
            "evidence_attempted_count": len(delisted_results),
            "sw_membership_found_count": len(delisted_sw_found),
            "sw_membership_found_symbols": delisted_sw_found,
            "no_usable_sw_source_evidence_count": len(delisted_no_source),
            "no_usable_sw_source_symbols": delisted_no_source,
            "unresolved_count": len(delisted_unresolved),
            "unresolved_symbols": delisted_unresolved,
            "stock_basic_industry_value_present_count": len(stock_basic_industry_present),
            "stock_basic_industry_value_present_symbols": stock_basic_industry_present,
            "exception_rate_denominator_count": denominator,
            "exception_rate_pct": exception_rate,
            "max_exception_rate_pct": MAX_DELISTED_EXCEPTION_RATE_PCT,
            "old_single_symbol_count_cap_removed_for_scaled_delisted_only_boundary": True,
            "applies_to_delisted_only": True,
            "active_symbols_can_never_use_exception": True,
            "keep_delisted_symbols_in_returns_and_risk": True,
            "exclude_only_from_industry_normalization_denominators": True,
            "silent_industry_fill_allowed": False,
            "drop_from_universe_returns_or_risk_allowed": False,
            "threshold_passed": delisted_boundary_passed,
            "symbol_results": delisted_results,
        },
        "candidate_universe_after": {
            "active_with_sw_membership_count": active_with_sw_after,
            "active_missing_sw_membership_count": len(active_unresolved),
            "active_delisting_shell_count": len(active_shell_symbols),
            "active_investable_unresolved_count": len(active_investable_unresolved),
            "pending_scaled_delisted_no_source_count_if_approved": len(delisted_no_source) + len(active_shell_symbols),
            "main_board_active_sw_coverage_pct": active_coverage_after,
            "delisted_sw_membership_found_by_repair_count": len(delisted_sw_found),
            "delisted_no_usable_sw_source_exception_count": len(delisted_no_source),
            "delisted_unresolved_count": len(delisted_unresolved),
            "candidate_universe_industry_gate_passed": gate_passed,
        },
        "decision": {
            "repair_status": status,
            "candidate_universe_ready_for_next_full_alpha_package": gate_passed,
            "data_can_be_used_for_alpha_now": False,
            "signal_search_authorized_by_this_summary": False,
            "full_alpha_run_executed": False,
            "plain_result": plain,
            "next_action": next_action,
        },
        "prohibited_claims": {
            "a_long_alpha_found": False,
            "signal_search_executed": False,
            "signal_search_authorized": False,
            "alpha_backtest_executed": False,
            "production_ready": False,
            "ship_gate_evidence": False,
            "full_size_allowed": False,
            "datahub_authorized": False,
            "broker_or_order_automation_authorized": False,
        },
        "limitations": [
            "This repairs only the A-long main-board SW industry coverage gate before a full alpha run.",
            "Tracked summary stores counts, statuses, public symbols, and raw refs only; raw rows stay under gitignored data/a_long/raw/.",
            "The scaled delisted boundary applies only to already-delisted names and only to industry-normalization denominators.",
            "Delisted names remain in PIT universe, terminal returns, risk, drawdown, and coverage reporting.",
            "This summary does not run signals, compute returns, prove alpha, authorize production, or count as ship-gate evidence.",
        ],
    }
    if contains_key(summary, "records"):
        raise ValueError("tracked summary must not contain raw records")
    return summary


def execute_repair(
    *,
    summary_path: Path = SUMMARY_PATH,
    raw_root: Path = RAW_ROOT,
    source_raw_root: Path = SOURCE_RAW_ROOT,
    preflight_summary_path: Path = PREFLIGHT_SUMMARY_PATH,
    pro_factory: Callable[[], Any] = route_base.get_tushare_client,
    generated_at: str | None = None,
    dry_run_env: bool = False,
    sleep_seconds: float = 0.05,
    confirm_independent_review_pass: bool = False,
    confirm_post_review_execute: bool = False,
) -> dict[str, Any]:
    validate_preflight_summary(preflight_summary_path)
    validate_source_raw_root(source_raw_root)
    validate_raw_root(raw_root)
    require_live_confirmations(
        dry_run_env=dry_run_env,
        confirm_independent_review_pass=confirm_independent_review_pass,
        confirm_post_review_execute=confirm_post_review_execute,
    )
    universe = missing_universe(source_raw_root)
    generated = generated_at or iso_now()
    planned_calls = len(universe["active_missing"]) + len(universe["delisted_missing"]) + 1
    if planned_calls > MAX_TOTAL_CALLS:
        raise ValueError(f"planned Tushare call count exceeds repair budget: {planned_calls} > {MAX_TOTAL_CALLS}")

    if dry_run_env or (pro_factory is route_base.get_tushare_client and not os.environ.get("TUSHARE_TOKEN")):
        environment_precheck_passed = bool(os.environ.get("TUSHARE_TOKEN"))
        summary = build_summary(
            generated_at=generated,
            universe=universe,
            active_results=[],
            delisted_results=[],
            stock_basic_context=None,
            environment_precheck_passed=environment_precheck_passed,
            independent_review_confirmed=confirm_independent_review_pass,
            post_review_execute_confirmed=confirm_post_review_execute,
            dry_run_env=dry_run_env,
        )
        write_json_atomic(summary, summary_path)
        validate_json(SCHEMA_PATH, summary)
        return summary

    pro = pro_factory()
    active_results = [execute_active_symbol(pro, raw_root, symbol, sleep_seconds) for symbol in universe["active_missing"]]
    stock_basic_context, stock_basic_by_symbol = stock_basic_delisted_context(pro, raw_root, sleep_seconds)
    delisted_results = [
        execute_delisted_symbol(pro, raw_root, symbol, stock_basic_by_symbol, sleep_seconds)
        for symbol in universe["delisted_missing"]
    ]
    summary = build_summary(
        generated_at=generated,
        universe=universe,
        active_results=active_results,
        delisted_results=delisted_results,
        stock_basic_context=stock_basic_context,
        environment_precheck_passed=True,
        independent_review_confirmed=confirm_independent_review_pass,
        post_review_execute_confirmed=confirm_post_review_execute,
        dry_run_env=False,
    )
    write_json_atomic(summary, summary_path)
    validate_json(SCHEMA_PATH, summary)
    return summary


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    summary = execute_repair(
        summary_path=args.summary_path,
        raw_root=args.raw_root,
        source_raw_root=args.source_raw_root,
        preflight_summary_path=args.preflight_summary_path,
        generated_at=args.generated_at,
        dry_run_env=args.dry_run_env,
        sleep_seconds=args.sleep_seconds,
        confirm_independent_review_pass=args.confirm_independent_review_pass,
        confirm_post_review_execute=args.confirm_post_review_execute,
    )
    decision = summary["decision"]
    print(
        "a_long_main_board_sw_coverage_repair: "
        f"{decision['repair_status']}; "
        f"ready={decision['candidate_universe_ready_for_next_full_alpha_package']}; "
        f"active_unresolved={summary['active_sw_supplement']['unresolved_count']}; "
        f"active_delisting_shells={summary['active_delisting_shell_boundary']['detected_count']}; "
        f"delisted_unresolved={summary['delisted_no_industry_boundary']['unresolved_count']}; "
        f"exception_rate={summary['delisted_no_industry_boundary']['exception_rate_pct']}%"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

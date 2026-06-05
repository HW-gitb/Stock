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

from engine.data.a_share_board_scope import is_main_board_ts_code
from runners import a_long_main_board_candidate_universe_preflight as preflight
from runners import a_long_tushare_broader_materialization_packet as broader_runner
from runners import a_long_tushare_incremental_materialization_packet as raw_base
from runners import a_long_tushare_route_validation_packet as route_base


PACKET_PATH = ROOT / "docs" / "a_long_full_main_board_signal_search_execution_packet_20260605.json"
BOUNDARY_PATH = ROOT / "docs" / "a_long_scaled_delisted_no_industry_boundary_decision_20260605.json"
SW_REPAIR_SUMMARY_PATH = ROOT / "docs" / "a_long_main_board_sw_coverage_repair_execution_summary_20260604.json"
SUMMARY_PATH = ROOT / "docs" / "a_long_full_main_board_materialization_execution_summary_20260605.json"
SCHEMA_PATH = ROOT / "schemas" / "a_long_full_main_board_materialization_execution_summary.schema.json"
RAW_ROOT_REL = Path("data/a_long/raw/tushare/full_main_board_signal_search_20260605")
RAW_ROOT = ROOT / RAW_ROOT_REL

START_DATE = "20180101"
END_DATE = "20251231"
EXPECTED_ACTIVE_COUNT = 3200
EXPECTED_DELISTED_COUNT = 187
EXPECTED_UNIVERSE_COUNT = 3387
REVIEWED_NO_INDUSTRY_EXCEPTION_COUNT = 191
MAX_TOTAL_ENDPOINT_CALLS = 24000
PLANNED_TOTAL_ENDPOINT_CALLS = 23717
BASE_CALL_COUNT = 8
CALLS_PER_SYMBOL = 7
DEFAULT_MIN_SECONDS_BETWEEN_NETWORK_CALLS = 1.25
BENCHMARK_INDICES = ["000300.SH", "000852.SH"]
ACTIVE_DELISTING_SHELL_SYMBOLS = ["600421.SH", "600599.SH", "600636.SH", "600696.SH"]
DATA_TABLE_IDS = [
    "trade_calendar",
    "stock_basic_active",
    "stock_basic_delisted",
    "income",
    "balancesheet",
    "cashflow",
    "fina_indicator",
    "industry_classification",
    "industry_membership",
    "daily_price",
    "adj_factor",
    "dividend",
    "benchmark_index_daily",
]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run only the reviewed A-long full main-board data materialization step. "
            "This writes raw Tushare payloads under gitignored data/a_long/raw/ and a tracked "
            "no-secret summary. It does not run the data-integrity audit or signal search."
        )
    )
    parser.add_argument("--packet-path", type=Path, default=PACKET_PATH)
    parser.add_argument("--summary-path", type=Path, default=SUMMARY_PATH)
    parser.add_argument("--raw-root", type=Path, default=RAW_ROOT)
    parser.add_argument("--generated-at", help="Optional deterministic timestamp for tests.")
    parser.add_argument(
        "--confirm-independent-review-pass",
        action="store_true",
        help="Required for live execution; confirms Claude review passed this runner/package.",
    )
    parser.add_argument(
        "--confirm-post-review-execute",
        action="store_true",
        help="Required for live execution; confirms the user issued the post-review execute command.",
    )
    parser.add_argument(
        "--dry-run-env",
        action="store_true",
        help="Validate packet, gates, gitignore, and environment boundary without Tushare calls.",
    )
    parser.add_argument(
        "--min-seconds-between-network-calls",
        type=float,
        default=DEFAULT_MIN_SECONDS_BETWEEN_NETWORK_CALLS,
        help="Minimum start-to-start delay for live Tushare calls. Unit tests may pass 0.",
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


def load_and_validate_packet(path: Path = PACKET_PATH) -> dict[str, Any]:
    packet = read_json(path)
    if packet.get("schema_name") != "a_long_full_main_board_signal_search_execution_packet":
        raise ValueError("A-long full main-board execution packet schema_name mismatch")

    scope = packet.get("scope") or {}
    required_true = [
        "research_only",
        "ready_for_later_execution_after_independent_review",
        "actual_tushare_calls_require_post_review_execute_command",
        "network_access_required_for_later_execution",
        "full_main_board_data_pull_allowed_after_gates",
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
        "signal_search_executed_by_this_artifact",
        "alpha_backtest_executed_by_this_artifact",
        "full_market_or_cross_board_pull_allowed",
        "provider_expansion_allowed",
        "datahub_allowed",
        "production_use_allowed",
        "ship_gate_claim_allowed",
        "full_size_manual_use_allowed",
        "broker_or_order_automation_allowed",
    ]
    for field in required_false:
        if scope.get(field) is not False:
            raise ValueError(f"packet scope.{field} must be false")

    boundary = packet.get("execution_boundary") or {}
    expected_boundary = {
        "board_scope": "main_board_only",
        "start_date": START_DATE,
        "end_date": END_DATE,
        "main_board_active_count_from_preflight": EXPECTED_ACTIVE_COUNT,
        "main_board_delisted_2018_2025_count_from_preflight": EXPECTED_DELISTED_COUNT,
        "candidate_universe_count_before_boundary": EXPECTED_UNIVERSE_COUNT,
        "reviewed_no_industry_exception_count": REVIEWED_NO_INDUSTRY_EXCEPTION_COUNT,
        "active_investable_missing_industry_allowed": False,
        "manual_industry_fill_allowed": False,
        "silent_unknown_or_default_industry_allowed": False,
        "drop_boundary_names_from_returns_or_risk_allowed": False,
        "industry_denominator_exclusion_only": True,
        "terminal_delisting_return_required": True,
        "selection_time_st_or_delisting_name_veto_required": True,
    }
    for field, expected in expected_boundary.items():
        if boundary.get(field) != expected:
            raise ValueError(f"packet execution_boundary.{field} mismatch")
    if boundary.get("active_delisting_shell_symbols") != ACTIVE_DELISTING_SHELL_SYMBOLS:
        raise ValueError("packet active delisting-shell symbol boundary mismatch")

    pull = packet.get("data_pull_plan") or {}
    if pull.get("estimated_symbol_count") != EXPECTED_UNIVERSE_COUNT:
        raise ValueError("packet estimated_symbol_count mismatch")
    if pull.get("planned_total_endpoint_calls") != PLANNED_TOTAL_ENDPOINT_CALLS:
        raise ValueError("packet planned_total_endpoint_calls mismatch")
    if pull.get("max_total_endpoint_calls") != MAX_TOTAL_ENDPOINT_CALLS:
        raise ValueError("packet max_total_endpoint_calls mismatch")
    if pull.get("retry_count_allowed") != 0:
        raise ValueError("packet retry_count_allowed must be zero")
    if pull.get("abort_if_budget_exceeded") is not True:
        raise ValueError("packet must abort on budget exceed")
    if set(pull.get("tables") or []) != set(DATA_TABLE_IDS):
        raise ValueError("packet table set mismatch")

    storage = packet.get("storage_and_output_boundary") or {}
    if storage.get("raw_output_root") != RAW_ROOT_REL.as_posix() + "/":
        raise ValueError("packet raw output root mismatch")
    if storage.get("materialization_summary_path") != "docs/a_long_full_main_board_materialization_execution_summary_20260605.json":
        raise ValueError("packet materialization summary path mismatch")
    for field in [
        "raw_output_root_must_be_gitignored",
        "tracked_outputs_must_exclude_raw_rows",
        "tracked_outputs_must_exclude_request_urls",
        "tracked_outputs_must_exclude_secret",
    ]:
        if storage.get(field) is not True:
            raise ValueError(f"packet storage.{field} must be true")
    if storage.get("raw_retention_authorizes_production_storage") is not False:
        raise ValueError("packet storage must not authorize production raw storage")

    for field, value in (packet.get("pre_execution_gates") or {}).items():
        if value is not True:
            raise ValueError(f"packet gate must stay true: {field}")
    for field, value in (packet.get("prohibited_claims") or {}).items():
        if value is not False:
            raise ValueError(f"packet prohibited claim must stay false: {field}")
    if planned_total_call_count(EXPECTED_UNIVERSE_COUNT) != PLANNED_TOTAL_ENDPOINT_CALLS:
        raise ValueError("runner call-plan formula no longer matches packet planned_total_endpoint_calls")
    return packet


def validate_boundary_and_repair_refs() -> None:
    boundary = read_json(BOUNDARY_PATH)
    reviewed = boundary.get("reviewed_boundary") or {}
    if reviewed.get("scaled_no_industry_boundary_count_if_approved") != REVIEWED_NO_INDUSTRY_EXCEPTION_COUNT:
        raise ValueError("approved no-industry boundary count mismatch")
    treatment = reviewed.get("boundary_treatment") or {}
    if treatment.get("exclude_only_from_industry_normalization_denominators") is not True:
        raise ValueError("boundary must remain industry-denominator-only")
    if treatment.get("keep_in_pit_universe_returns_risk_drawdown_and_coverage") is not True:
        raise ValueError("boundary names must stay in returns/risk/coverage")
    if treatment.get("manual_industry_fill_allowed") is not False:
        raise ValueError("manual industry assignment must stay forbidden")

    repair = read_json(SW_REPAIR_SUMMARY_PATH)
    if repair.get("schema_name") != "a_long_main_board_sw_coverage_repair_execution_summary":
        raise ValueError("SW repair summary schema_name mismatch")
    active = repair.get("active_sw_supplement") or {}
    if active.get("supplement_success_count") != 1189:
        raise ValueError("SW repair active supplement success count mismatch")
    if active.get("unresolved_count") != 4:
        raise ValueError("SW repair unresolved active shell count mismatch")
    shell = repair.get("active_delisting_shell_boundary") or {}
    if shell.get("detected_symbols") != ACTIVE_DELISTING_SHELL_SYMBOLS:
        raise ValueError("SW repair active delisting-shell symbols mismatch")
    if shell.get("active_investable_unresolved_count") != 0:
        raise ValueError("SW repair must leave no active investable unresolved names")
    delisted = repair.get("delisted_no_industry_boundary") or {}
    if delisted.get("no_usable_sw_source_evidence_count") != EXPECTED_DELISTED_COUNT:
        raise ValueError("SW repair delisted no-source count mismatch")


def path_is_gitignored_by_policy(raw_root: Path) -> bool:
    return raw_base.path_is_gitignored_by_policy(raw_root)


def validate_raw_root(raw_root: Path) -> None:
    resolved = raw_root.resolve()
    approved = (ROOT / RAW_ROOT_REL).resolve()
    try:
        resolved.relative_to(approved)
    except ValueError as exc:
        raise ValueError("raw output must stay under data/a_long/raw/tushare/full_main_board_signal_search_20260605/") from exc
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
    if not confirm_independent_review_pass:
        raise RuntimeError("live execution requires --confirm-independent-review-pass")
    if not confirm_post_review_execute:
        raise RuntimeError("live execution requires --confirm-post-review-execute")


def raw_payload_path(raw_root: Path, call_id: str) -> Path:
    safe = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in call_id)
    return raw_root / f"{safe}.json"


def raw_ref(path: Path) -> str:
    return path.resolve().relative_to(ROOT.resolve()).as_posix()


def load_existing_raw_payload(raw_root: Path, call_id: str) -> tuple[dict[str, Any], str] | None:
    path = raw_payload_path(raw_root, call_id)
    if not path.exists():
        return None
    return read_json(path), raw_ref(path)


def write_raw_payload(raw_root: Path, call_id: str, payload: dict[str, Any]) -> str:
    path = raw_payload_path(raw_root, call_id)
    write_json_atomic(payload, path)
    return raw_ref(path)


def normalize_records(value: Any) -> tuple[list[str], int | None, list[dict[str, Any]]]:
    return route_base.normalize_records(value)


def base_call_plan() -> list[dict[str, Any]]:
    calls = [
        {
            "call_id": "trade_calendar_2018_2025",
            "table_id": "trade_calendar",
            "api_family": "trade_cal",
            "method": "trade_cal",
            "kwargs": {
                "exchange": "SSE",
                "start_date": START_DATE,
                "end_date": END_DATE,
                "is_open": "1",
                "fields": "cal_date,is_open,exchange",
            },
            "minimum_fields": ["cal_date", "is_open", "exchange"],
        },
        {
            "call_id": "stock_basic_active_L",
            "table_id": "stock_basic_active",
            "api_family": "stock_basic",
            "method": "stock_basic",
            "kwargs": {
                "exchange": "",
                "list_status": "L",
                "fields": "ts_code,symbol,name,exchange,market,list_status,list_date,delist_date",
            },
            "minimum_fields": ["ts_code", "name", "list_status", "list_date", "delist_date"],
        },
        {
            "call_id": "stock_basic_delisted_D",
            "table_id": "stock_basic_delisted",
            "api_family": "stock_basic",
            "method": "stock_basic",
            "kwargs": {
                "exchange": "",
                "list_status": "D",
                "fields": "ts_code,symbol,name,exchange,market,list_status,list_date,delist_date",
            },
            "minimum_fields": ["ts_code", "name", "list_status", "list_date", "delist_date"],
        },
        {
            "call_id": "index_classify_sw_L1",
            "table_id": "industry_classification",
            "api_family": "index_classify",
            "method": "index_classify",
            "kwargs": {"level": "L1", "fields": "index_code,industry_name,level,parent_code"},
            "minimum_fields": ["index_code", "industry_name", "level", "parent_code"],
        },
        {
            "call_id": "index_classify_sw_L2",
            "table_id": "industry_classification",
            "api_family": "index_classify",
            "method": "index_classify",
            "kwargs": {"level": "L2", "fields": "index_code,industry_name,level,parent_code"},
            "minimum_fields": ["index_code", "industry_name", "level", "parent_code"],
        },
        {
            "call_id": "index_member_all_sw_membership",
            "table_id": "industry_membership",
            "api_family": "index_member_all",
            "method": "index_member_all",
            "kwargs": {"fields": "ts_code,name,l1_code,l1_name,l2_code,l2_name,in_date,out_date,is_new"},
            "minimum_fields": ["ts_code", "l2_code", "l2_name", "in_date", "out_date"],
        },
    ]
    for index_code in BENCHMARK_INDICES:
        calls.append(
            {
                "call_id": f"index_daily_{index_code.replace('.', '_')}_2018_2025",
                "table_id": "benchmark_index_daily",
                "api_family": "index_daily",
                "method": "index_daily",
                "kwargs": {
                    "ts_code": index_code,
                    "start_date": START_DATE,
                    "end_date": END_DATE,
                    "fields": "ts_code,trade_date,open,close",
                },
                "minimum_fields": ["ts_code", "trade_date", "open", "close"],
            }
        )
    return calls


def symbol_call_plan(symbols: list[str]) -> list[dict[str, Any]]:
    fundamental_fields = {
        "income": "ts_code,ann_date,f_ann_date,end_date,report_type,revenue,n_income_attr_p",
        "balancesheet": "ts_code,ann_date,f_ann_date,end_date,report_type,total_assets,total_liab,total_hldr_eqy_exc_min_int",
        "cashflow": "ts_code,ann_date,f_ann_date,end_date,report_type,n_cashflow_act",
        "fina_indicator": "ts_code,ann_date,end_date,roe,profit_dedt",
    }
    fundamental_minimums = {
        "income": ["ts_code", "ann_date", "end_date", "revenue", "n_income_attr_p"],
        "balancesheet": ["ts_code", "ann_date", "end_date", "total_assets", "total_liab", "total_hldr_eqy_exc_min_int"],
        "cashflow": ["ts_code", "ann_date", "end_date", "n_cashflow_act"],
        "fina_indicator": ["ts_code", "ann_date", "end_date", "roe", "profit_dedt"],
    }
    calls: list[dict[str, Any]] = []
    for symbol in symbols:
        suffix = symbol.replace(".", "_")
        for table_id in ["income", "balancesheet", "cashflow", "fina_indicator"]:
            calls.append(
                {
                    "call_id": f"{table_id}_{suffix}_2018_2025",
                    "table_id": table_id,
                    "api_family": table_id,
                    "method": table_id,
                    "kwargs": {
                        "ts_code": symbol,
                        "start_date": START_DATE,
                        "end_date": END_DATE,
                        "fields": fundamental_fields[table_id],
                    },
                    "minimum_fields": fundamental_minimums[table_id],
                }
            )
        calls.extend(
            [
                {
                    "call_id": f"daily_{suffix}_2018_2025",
                    "table_id": "daily_price",
                    "api_family": "daily",
                    "method": "daily",
                    "kwargs": {
                        "ts_code": symbol,
                        "start_date": START_DATE,
                        "end_date": END_DATE,
                        "fields": "ts_code,trade_date,open,close,vol,amount",
                    },
                    "minimum_fields": ["ts_code", "trade_date", "open", "close"],
                },
                {
                    "call_id": f"adj_factor_{suffix}_2018_2025",
                    "table_id": "adj_factor",
                    "api_family": "adj_factor",
                    "method": "adj_factor",
                    "kwargs": {
                        "ts_code": symbol,
                        "start_date": START_DATE,
                        "end_date": END_DATE,
                        "fields": "ts_code,trade_date,adj_factor",
                    },
                    "minimum_fields": ["ts_code", "trade_date", "adj_factor"],
                },
                {
                    "call_id": f"dividend_{suffix}",
                    "table_id": "dividend",
                    "api_family": "dividend",
                    "method": "dividend",
                    "kwargs": {
                        "ts_code": symbol,
                        "fields": "ts_code,ann_date,record_date,ex_date,pay_date,stk_div,cash_div_tax",
                    },
                    "minimum_fields": ["ts_code", "ann_date", "ex_date"],
                },
            ]
        )
    return calls


def planned_total_call_count(symbol_count: int) -> int:
    return BASE_CALL_COUNT + symbol_count * CALLS_PER_SYMBOL


def result_from_payload(call: dict[str, Any], payload: dict[str, Any], raw_payload_ref: str, checkpoint_status: str) -> dict[str, Any]:
    columns = [str(col) for col in payload.get("columns") or []]
    minimum = list(call["minimum_fields"])
    present = [field for field in minimum if field in columns]
    missing = [field for field in minimum if field not in columns]
    return {
        "call_id": call["call_id"],
        "table_id": call["table_id"],
        "api_family": call["api_family"],
        "call_status": payload.get("call_status", "error"),
        "row_count": payload.get("row_count"),
        "columns": columns,
        "minimum_fields_present": present,
        "minimum_fields_missing": missing,
        "raw_payload_ref": raw_payload_ref,
        "checkpoint_status": checkpoint_status,
        "tracked_summary_excludes_raw_rows": True,
        "error_class": payload.get("error_class"),
        "error_message_redacted": payload.get("error_message_redacted"),
    }


def execute_call_with_checkpoint(
    pro: Any,
    call: dict[str, Any],
    raw_root: Path,
    *,
    pacer: broader_runner.NetworkPacer,
) -> tuple[dict[str, Any], bool]:
    existing = load_existing_raw_payload(raw_root, call["call_id"])
    if existing is not None:
        payload, ref = existing
        return result_from_payload(call, payload, ref, "reused_existing_raw"), False

    request_shape_without_token = dict(call["kwargs"])
    pacer.before_network_call()
    try:
        value = getattr(pro, call["method"])(**call["kwargs"])
        columns, row_count, records = normalize_records(value)
        status = "success" if row_count and row_count > 0 else "empty"
        ref = write_raw_payload(
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
            "error_class": None,
            "error_message_redacted": None,
        }
    except Exception as exc:
        ref = write_raw_payload(
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
            "error_class": type(exc).__name__,
            "error_message_redacted": route_base.redact_error(exc),
        }
    return result_from_payload(call, payload, ref, "written_new_raw"), True


def raw_records_for_call(raw_root: Path, call_id: str) -> list[dict[str, Any]]:
    payload = read_json(raw_payload_path(raw_root, call_id))
    records = payload.get("records")
    if not isinstance(records, list):
        raise ValueError(f"raw payload records missing for {call_id}")
    return [row for row in records if isinstance(row, dict)]


def main_board_delisted_in_window(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return preflight.main_board_delisted_in_window(records)


def build_candidate_universe_from_records(
    active_records: list[dict[str, Any]],
    delisted_records: list[dict[str, Any]],
) -> dict[str, Any]:
    main_active = [row for row in active_records if is_main_board_ts_code(row.get("ts_code"))]
    main_delisted = main_board_delisted_in_window(delisted_records)
    active_symbols = sorted(str(row.get("ts_code")) for row in main_active if row.get("ts_code"))
    delisted_symbols = sorted(str(row.get("ts_code")) for row in main_delisted if row.get("ts_code"))
    return {
        "status": "validated_exact_boundary",
        "start_date": START_DATE,
        "end_date": END_DATE,
        "main_board_active_count": len(active_symbols),
        "main_board_delisted_2018_2025_count": len(delisted_symbols),
        "candidate_universe_count": len(active_symbols) + len(delisted_symbols),
        "active_symbols_sample": active_symbols[:20],
        "delisted_symbols_sample": delisted_symbols[:20],
        "symbols_for_materialization": active_symbols + delisted_symbols,
        "matches_reviewed_execution_packet": (
            len(active_symbols) == EXPECTED_ACTIVE_COUNT
            and len(delisted_symbols) == EXPECTED_DELISTED_COUNT
            and len(active_symbols) + len(delisted_symbols) == EXPECTED_UNIVERSE_COUNT
        ),
    }


def empty_candidate_universe(status: str) -> dict[str, Any]:
    return {
        "status": status,
        "start_date": START_DATE,
        "end_date": END_DATE,
        "main_board_active_count": 0,
        "main_board_delisted_2018_2025_count": 0,
        "candidate_universe_count": 0,
        "active_symbols_sample": [],
        "delisted_symbols_sample": [],
        "matches_reviewed_execution_packet": False,
    }


def endpoint_shape_complete(result: dict[str, Any]) -> bool:
    return result["call_status"] in {"success", "empty"} and not result.get("minimum_fields_missing")


def base_shape_complete(results: list[dict[str, Any]]) -> bool:
    expected_base_ids = {call["call_id"] for call in base_call_plan()}
    result_ids = {item["call_id"] for item in results}
    return result_ids == expected_base_ids and all(endpoint_shape_complete(item) for item in results)


def table_rollup(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for table_id in DATA_TABLE_IDS:
        table_results = [item for item in results if item["table_id"] == table_id]
        missing = sorted({field for item in table_results for field in item.get("minimum_fields_missing", [])})
        error_count = sum(1 for item in table_results if item["call_status"] == "error")
        complete_count = sum(1 for item in table_results if endpoint_shape_complete(item))
        total = len(table_results)
        row_counts = [item["row_count"] for item in table_results if isinstance(item.get("row_count"), int)]
        status = (
            "passed_full_main_board_materialization_shape"
            if total > 0 and error_count == 0 and not missing
            else "partial_or_failed_full_main_board_materialization_shape"
            if total > 0
            else "not_tested"
        )
        out.append(
            {
                "table_id": table_id,
                "status": status,
                "calls_total": total,
                "calls_success_or_empty": complete_count,
                "calls_error": error_count,
                "missing_minimum_fields": missing,
                "min_row_count": min(row_counts) if row_counts else None,
                "max_row_count": max(row_counts) if row_counts else None,
            }
        )
    return out


def write_endpoint_manifest(results: list[dict[str, Any]], raw_root: Path) -> str | None:
    if not results:
        return None
    path = raw_root / "endpoint_results_manifest.no_raw_rows.json"
    payload = {
        "schema_name": "a_long_full_main_board_materialization_endpoint_manifest",
        "schema_version": "1.0.0",
        "generated_at": iso_now(),
        "tracked_summary_excludes_raw_rows": True,
        "tracked_summary_excludes_secret": True,
        "endpoint_results": results,
    }
    write_json_atomic(payload, path)
    return raw_ref(path)


def build_summary(
    *,
    results: list[dict[str, Any]],
    generated_at: str,
    candidate_universe: dict[str, Any],
    endpoint_manifest_ref: str | None,
    environment_precheck_passed: bool,
    independent_review_confirmed: bool,
    post_review_execute_confirmed: bool,
    new_network_call_count: int,
    reused_raw_payload_count: int,
    min_seconds_between_network_calls: float,
    dry_run_env: bool = False,
) -> dict[str, Any]:
    rollup = table_rollup(results)
    full_plan_processed = len(results) == PLANNED_TOTAL_ENDPOINT_CALLS
    all_tables_pass = all(item["status"] == "passed_full_main_board_materialization_shape" for item in rollup)
    universe_matches = candidate_universe.get("matches_reviewed_execution_packet") is True

    if dry_run_env and environment_precheck_passed:
        status = "dry_run_environment_ready"
        plain_result = "Environment and contract checks passed. No data was pulled."
        next_action = "Send this runner/package to independent review. After PASS and user execute, run the live materialization."
    elif not environment_precheck_passed:
        status = "not_executed_environment_missing"
        plain_result = "No data was pulled because TUSHARE_TOKEN is missing."
        next_action = "Set TUSHARE_TOKEN, then rerun only after independent review PASS and user execute."
    elif results and not universe_matches:
        status = "blocked_universe_drift_before_full_pull"
        plain_result = "Base data was checked, but the main-board universe no longer matches the reviewed packet. Full pull stopped."
        next_action = "Review the changed universe before any full materialization or signal search."
    elif full_plan_processed and all_tables_pass:
        status = "passed_full_main_board_materialization_shape"
        plain_result = "Full main-board raw data was materialized. It still cannot be used for alpha until the full data audit passes."
        next_action = "Run the separate reviewed full main-board data-integrity audit. If that audit fails, stop before signal search."
    elif results:
        status = "partial_or_failed_full_main_board_materialization"
        plain_result = "Full main-board raw data materialization is incomplete or has endpoint errors. Do not search alpha."
        next_action = "Fix the failed data calls or record the blocker before any audit or signal search."
    else:
        status = "not_executed_environment_missing"
        plain_result = "No data was pulled."
        next_action = "Review environment, review gate, and execute gate before any live run."

    return {
        "schema_name": "a_long_full_main_board_materialization_execution_summary",
        "schema_version": "1.0.0",
        "generated_at": generated_at,
        "artifact_id": "a_long_full_main_board_materialization_execution_summary_20260605",
        "packet_ref": "docs/a_long_full_main_board_signal_search_execution_packet_20260605.json",
        "scope": {
            "phase": "7a_alpha_validation",
            "purpose": "a_long_full_main_board_materialization_execution",
            "lane_id": "a_long",
            "market": "A-share",
            "research_only": True,
            "provider_family": "tushare_existing_account",
            "provider_call_executed": new_network_call_count > 0,
            "tushare_call_executed": new_network_call_count > 0,
            "data_fetch_executed": new_network_call_count > 0,
            "raw_payload_written_to_gitignored_path": new_network_call_count > 0,
            "raw_payload_read_for_checkpoint_or_universe_derivation": bool(results),
            "tracked_summary_contains_raw_rows": False,
            "tracked_summary_contains_secret": False,
            "tracked_summary_contains_request_url": False,
            "full_main_board_materialization_attempted": bool(results),
            "full_market_or_cross_board_pull_executed": False,
            "data_integrity_audit_executed": False,
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
            "summary_path": "docs/a_long_full_main_board_materialization_execution_summary_20260605.json",
            "raw_output_root": RAW_ROOT_REL.as_posix() + "/",
            "raw_output_root_is_gitignored": True,
            "max_total_endpoint_calls": MAX_TOTAL_ENDPOINT_CALLS,
            "planned_total_endpoint_calls": PLANNED_TOTAL_ENDPOINT_CALLS,
            "base_call_count": BASE_CALL_COUNT,
            "calls_per_symbol": CALLS_PER_SYMBOL,
            "endpoint_results_count": len(results),
            "new_network_call_count": new_network_call_count,
            "reused_raw_payload_count": reused_raw_payload_count,
            "min_seconds_between_network_calls": min_seconds_between_network_calls,
            "budget_exceeded": False,
            "network_call_attempted": new_network_call_count > 0,
            "environment_precheck_passed": environment_precheck_passed,
            "independent_review_confirmed": independent_review_confirmed,
            "post_review_execute_confirmed": post_review_execute_confirmed,
            "token_logged": False,
            "request_url_logged": False,
        },
        "execution_boundary": {
            "board_scope": "main_board_only",
            "start_date": START_DATE,
            "end_date": END_DATE,
            "expected_active_count": EXPECTED_ACTIVE_COUNT,
            "expected_delisted_count": EXPECTED_DELISTED_COUNT,
            "expected_candidate_universe_count": EXPECTED_UNIVERSE_COUNT,
            "reviewed_no_industry_exception_count": REVIEWED_NO_INDUSTRY_EXCEPTION_COUNT,
            "active_investable_missing_industry_allowed": False,
            "active_delisting_shell_symbols": ACTIVE_DELISTING_SHELL_SYMBOLS,
            "manual_industry_fill_allowed": False,
            "silent_unknown_or_default_industry_allowed": False,
            "drop_boundary_names_from_returns_or_risk_allowed": False,
            "industry_denominator_exclusion_only": True,
            "terminal_delisting_return_required": True,
        },
        "prior_industry_repair_dependency": {
            "summary_ref": "docs/a_long_main_board_sw_coverage_repair_execution_summary_20260604.json",
            "active_sw_supplement_success_count": 1189,
            "active_investable_unresolved_count": 0,
            "active_delisting_shell_count": 4,
            "delisted_no_usable_sw_source_count": 187,
            "extra_tushare_calls_in_this_runner_for_sw_repair": 0,
            "plain_result": "This runner does not redo the 1,189 active industry supplement calls; it consumes the reviewed repair summary and approved 191-name boundary.",
        },
        "candidate_universe": {
            key: value
            for key, value in candidate_universe.items()
            if key != "symbols_for_materialization"
        },
        "endpoint_manifest": {
            "tracked_summary_embeds_endpoint_results": False,
            "manifest_ref": endpoint_manifest_ref,
            "manifest_is_gitignored": endpoint_manifest_ref is not None,
        },
        "table_rollup": rollup,
        "decision": {
            "materialization_status": status,
            "raw_materialization_shape_available": status == "passed_full_main_board_materialization_shape",
            "data_can_be_used_for_alpha_now": False,
            "data_integrity_audit_authorized_by_this_summary": False,
            "next_reviewed_step_can_be_full_data_integrity_audit": status == "passed_full_main_board_materialization_shape",
            "signal_search_authorized_by_this_summary": False,
            "alpha_found": False,
            "plain_result": plain_result,
            "next_action": next_action,
        },
        "prohibited_claims": {
            "a_long_alpha_found": False,
            "data_integrity_audit_passed": False,
            "signal_search_executed": False,
            "signal_search_authorized": False,
            "production_ready": False,
            "ship_gate_evidence": False,
            "full_size_allowed": False,
            "datahub_authorized": False,
            "broker_or_order_automation_authorized": False,
        },
        "limitations": [
            "This summary records materialization shape and counts only; raw rows stay under gitignored data/a_long/raw/.",
            "A materialization pass is not data-integrity pass and is not alpha evidence.",
            "Signal search must not run unless a separate full main-board data-integrity audit passes first.",
            "No full-market or cross-board pull, DataHub, production, ship-gate, full-size use, or broker/order automation is authorized.",
        ],
    }


def execute_full_main_board_materialization(
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
    validate_boundary_and_repair_refs()
    validate_raw_root(raw_root)
    require_live_execution_confirmations(
        dry_run_env=dry_run_env,
        confirm_independent_review_pass=confirm_independent_review_pass,
        confirm_post_review_execute=confirm_post_review_execute,
    )

    generated = generated_at or iso_now()
    environment_precheck_passed = bool(os.environ.get("TUSHARE_TOKEN"))
    if dry_run_env:
        summary = build_summary(
            results=[],
            generated_at=generated,
            candidate_universe=empty_candidate_universe("not_loaded"),
            endpoint_manifest_ref=None,
            environment_precheck_passed=environment_precheck_passed,
            independent_review_confirmed=confirm_independent_review_pass,
            post_review_execute_confirmed=confirm_post_review_execute,
            new_network_call_count=0,
            reused_raw_payload_count=0,
            min_seconds_between_network_calls=min_seconds_between_network_calls,
            dry_run_env=True,
        )
        validate_json(SCHEMA_PATH, summary)
        write_json_atomic(summary, summary_path)
        return summary

    if pro_factory is route_base.get_tushare_client and not environment_precheck_passed:
        summary = build_summary(
            results=[],
            generated_at=generated,
            candidate_universe=empty_candidate_universe("not_loaded"),
            endpoint_manifest_ref=None,
            environment_precheck_passed=False,
            independent_review_confirmed=confirm_independent_review_pass,
            post_review_execute_confirmed=confirm_post_review_execute,
            new_network_call_count=0,
            reused_raw_payload_count=0,
            min_seconds_between_network_calls=min_seconds_between_network_calls,
        )
        validate_json(SCHEMA_PATH, summary)
        write_json_atomic(summary, summary_path)
        return summary

    pro = pro_factory()
    pacer = broader_runner.NetworkPacer(min_seconds_between_network_calls)
    results: list[dict[str, Any]] = []
    new_network_call_count = 0
    reused_raw_payload_count = 0

    for call in base_call_plan():
        result, used_network = execute_call_with_checkpoint(pro, call, raw_root, pacer=pacer)
        results.append(result)
        if used_network:
            new_network_call_count += 1
        else:
            reused_raw_payload_count += 1

    if not base_shape_complete(results):
        endpoint_manifest_ref = write_endpoint_manifest(results, raw_root)
        summary = build_summary(
            results=results,
            generated_at=generated,
            candidate_universe=empty_candidate_universe("blocked_universe_drift_or_base_failure"),
            endpoint_manifest_ref=endpoint_manifest_ref,
            environment_precheck_passed=True,
            independent_review_confirmed=confirm_independent_review_pass,
            post_review_execute_confirmed=confirm_post_review_execute,
            new_network_call_count=new_network_call_count,
            reused_raw_payload_count=reused_raw_payload_count,
            min_seconds_between_network_calls=min_seconds_between_network_calls,
        )
        validate_json(SCHEMA_PATH, summary)
        write_json_atomic(summary, summary_path)
        return summary

    candidate_universe = build_candidate_universe_from_records(
        raw_records_for_call(raw_root, "stock_basic_active_L"),
        raw_records_for_call(raw_root, "stock_basic_delisted_D"),
    )
    if not candidate_universe["matches_reviewed_execution_packet"]:
        endpoint_manifest_ref = write_endpoint_manifest(results, raw_root)
        summary = build_summary(
            results=results,
            generated_at=generated,
            candidate_universe=candidate_universe,
            endpoint_manifest_ref=endpoint_manifest_ref,
            environment_precheck_passed=True,
            independent_review_confirmed=confirm_independent_review_pass,
            post_review_execute_confirmed=confirm_post_review_execute,
            new_network_call_count=new_network_call_count,
            reused_raw_payload_count=reused_raw_payload_count,
            min_seconds_between_network_calls=min_seconds_between_network_calls,
        )
        validate_json(SCHEMA_PATH, summary)
        write_json_atomic(summary, summary_path)
        return summary

    symbol_calls = symbol_call_plan(candidate_universe["symbols_for_materialization"])
    if BASE_CALL_COUNT + len(symbol_calls) != PLANNED_TOTAL_ENDPOINT_CALLS:
        raise ValueError("full main-board call plan no longer matches reviewed packet budget")
    if BASE_CALL_COUNT + len(symbol_calls) > MAX_TOTAL_ENDPOINT_CALLS:
        raise ValueError("full main-board call plan exceeds max budget")

    for call in symbol_calls:
        result, used_network = execute_call_with_checkpoint(pro, call, raw_root, pacer=pacer)
        results.append(result)
        if used_network:
            new_network_call_count += 1
        else:
            reused_raw_payload_count += 1
        if new_network_call_count + reused_raw_payload_count > MAX_TOTAL_ENDPOINT_CALLS:
            raise ValueError("full main-board materialization call budget exceeded")

    endpoint_manifest_ref = write_endpoint_manifest(results, raw_root)
    summary = build_summary(
        results=results,
        generated_at=generated,
        candidate_universe=candidate_universe,
        endpoint_manifest_ref=endpoint_manifest_ref,
        environment_precheck_passed=True,
        independent_review_confirmed=confirm_independent_review_pass,
        post_review_execute_confirmed=confirm_post_review_execute,
        new_network_call_count=new_network_call_count,
        reused_raw_payload_count=reused_raw_payload_count,
        min_seconds_between_network_calls=min_seconds_between_network_calls,
    )
    validate_json(SCHEMA_PATH, summary)
    write_json_atomic(summary, summary_path)
    return summary


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    summary = execute_full_main_board_materialization(
        packet_path=args.packet_path,
        summary_path=args.summary_path,
        raw_root=args.raw_root,
        generated_at=args.generated_at,
        dry_run_env=args.dry_run_env,
        confirm_independent_review_pass=args.confirm_independent_review_pass,
        confirm_post_review_execute=args.confirm_post_review_execute,
        min_seconds_between_network_calls=args.min_seconds_between_network_calls,
    )
    decision = summary["decision"]
    print(
        f"{decision['materialization_status']}: {decision['plain_result']} "
        f"new_calls={summary['execution']['new_network_call_count']} "
        f"reused={summary['execution']['reused_raw_payload_count']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

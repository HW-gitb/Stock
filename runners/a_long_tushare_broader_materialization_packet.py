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

from runners import a_long_tushare_incremental_materialization_packet as thin_runner
from runners import a_long_tushare_route_validation_packet as route_base
from engine.data.a_share_board_scope import assert_main_board_only


PACKET_PATH = ROOT / "docs" / "a_long_tushare_broader_materialization_packet_20260604.json"
THIN_AUDIT_REPORT_PATH = ROOT / "research" / "results" / "a_long_materialized_thin_slice_data_integrity_audit_20260604" / "audit_report.json"
DAILY_ROUTE_DIAGNOSTIC_SUMMARY_PATH = ROOT / "docs" / "a_long_tushare_daily_price_route_diagnostic_execution_summary_20260604.json"
SUMMARY_PATH = ROOT / "docs" / "a_long_tushare_broader_materialization_execution_summary_20260604.json"
RAW_ROOT_REL = Path("data/a_long/raw/tushare/materialization_full_period_panel_20260604")
RAW_ROOT = ROOT / RAW_ROOT_REL

START_DATE = "20180101"
END_DATE = "20251231"
ACTIVE_SYMBOLS = [
    "000001.SZ",
    "600519.SH",
    "600887.SH",
    "601318.SH",
    "600036.SH",
    "000651.SZ",
    "002415.SZ",
    "600276.SH",
]
DELISTED_SYMBOLS = ["000666.SZ"]
SYMBOLS = ACTIVE_SYMBOLS + DELISTED_SYMBOLS
BENCHMARK_INDICES = ["000300.SH", "000852.SH"]
MAX_TOTAL_ENDPOINT_CALLS = 80
PLANNED_TOTAL_ENDPOINT_CALLS = 71
DEFAULT_MIN_SECONDS_BETWEEN_NETWORK_CALLS = 1.25
PACED_REFETCH_SUFFIX = "paced_refetch"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run the reviewed A-long Tushare 2018-2025 full-period panel materialization packet. "
            "This writes raw rows only under gitignored data/a_long/raw/ and tracked shape-only summary; "
            "it does not rerun audit or search signals."
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
        help="Validate packet, gitignore, and environment boundary without Tushare calls.",
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
    return thin_runner.read_json(path)


def write_json_atomic(payload: Any, path: Path) -> None:
    thin_runner.write_json_atomic(payload, path)


def load_and_validate_packet(path: Path = PACKET_PATH) -> dict[str, Any]:
    packet = read_json(path)
    if packet.get("schema_name") != "a_long_tushare_broader_materialization_packet":
        raise ValueError("A-long broader materialization packet schema_name mismatch")

    source_refs = packet.get("source_artifact_refs") or []
    if not any(
        ref.get("artifact_id") == "a_long_tushare_daily_price_route_diagnostic_execution_summary_20260604"
        for ref in source_refs
    ):
        raise ValueError("packet must reference the daily-route diagnostic summary before paced daily repair")

    scope = packet.get("scope") or {}
    required_true = [
        "research_only",
        "ready_for_later_execution_after_independent_review",
        "actual_tushare_calls_require_post_review_execute_command",
        "network_access_required_for_later_execution",
        "full_period_panel_materialization_allowed_after_gates",
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

    boundary = packet.get("broader_materialization_boundary") or {}
    if boundary.get("materialization_id") != "a_long_tushare_full_period_panel_2018_2025":
        raise ValueError("packet materialization_id mismatch")
    if boundary.get("start_date") != START_DATE or boundary.get("end_date") != END_DATE:
        raise ValueError("packet date boundary mismatch")
    assert_main_board_only(boundary.get("active_symbols") or [], context="A-long broader materialization packet active_symbols")
    assert_main_board_only(ACTIVE_SYMBOLS, context="A-long broader materialization runner active_symbols")
    if boundary.get("active_symbols") != ACTIVE_SYMBOLS:
        raise ValueError("packet active symbols must stay fixed")
    if boundary.get("delisted_symbols") != DELISTED_SYMBOLS:
        raise ValueError("packet delisted symbols must stay fixed")
    if boundary.get("benchmark_indices") != BENCHMARK_INDICES:
        raise ValueError("packet benchmark indices must stay fixed")
    if boundary.get("not_full_market") is not True or boundary.get("not_full_universe") is not True:
        raise ValueError("packet must remain non-full-market and non-full-universe")

    budget = packet.get("call_budget") or {}
    if budget.get("max_total_endpoint_calls") != MAX_TOTAL_ENDPOINT_CALLS:
        raise ValueError("packet max_total_endpoint_calls must be 80")
    if budget.get("planned_total_endpoint_calls") != PLANNED_TOTAL_ENDPOINT_CALLS:
        raise ValueError("packet planned_total_endpoint_calls must be 71")
    if budget.get("retry_count_allowed") != 0:
        raise ValueError("packet retry_count_allowed must be zero")
    if budget.get("abort_if_budget_exceeded") is not True:
        raise ValueError("packet must abort on budget exceed")

    storage = packet.get("storage_and_checkpoint_boundary") or {}
    if storage.get("raw_output_root") != RAW_ROOT_REL.as_posix() + "/":
        raise ValueError("packet raw output root mismatch")
    if storage.get("tracked_summary_path") != "docs/a_long_tushare_broader_materialization_execution_summary_20260604.json":
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
    if len(materialization_call_plan()) != PLANNED_TOTAL_ENDPOINT_CALLS:
        raise ValueError("runner call plan no longer matches packet planned_total_endpoint_calls")
    return packet


def validate_thin_slice_audit_pass(path: Path = THIN_AUDIT_REPORT_PATH) -> None:
    report = read_json(path)
    if report.get("schema_name") != "a_long_materialized_thin_slice_data_integrity_audit_report":
        raise ValueError("thin-slice audit report schema_name mismatch")
    decision = report.get("decision") or {}
    if decision.get("audit_status") != "passed_thin_slice_data_integrity_not_alpha_ready":
        raise ValueError("thin-slice audit must pass before broader materialization")
    if decision.get("data_can_be_used_for_alpha_now") is not False:
        raise ValueError("thin-slice audit must not claim data is alpha-ready")
    execution = report.get("execution") or {}
    if execution.get("self_tests_required") != 11 or execution.get("self_tests_passed") != 11:
        raise ValueError("thin-slice audit must retain 11/11 self-test evidence")


def validate_daily_route_diagnostic_supports_pacing(path: Path = DAILY_ROUTE_DIAGNOSTIC_SUMMARY_PATH) -> None:
    summary = read_json(path)
    if summary.get("schema_name") != "a_long_tushare_daily_price_route_diagnostic_execution_summary":
        raise ValueError("daily-route diagnostic summary schema_name mismatch")
    decision = summary.get("decision") or {}
    if decision.get("price_route_diagnostic_status") != "eight_year_isolated_returned_rows":
        raise ValueError("daily-route diagnostic does not support pacing repair")
    if decision.get("data_can_be_used_for_alpha_now") is not False:
        raise ValueError("daily-route diagnostic must not claim data is alpha-ready")
    if decision.get("signal_search_authorized_by_this_summary") is not False:
        raise ValueError("daily-route diagnostic must not authorize signal search")


def path_is_gitignored_by_policy(raw_root: Path) -> bool:
    return thin_runner.path_is_gitignored_by_policy(raw_root)


def validate_raw_root(raw_root: Path) -> None:
    resolved = raw_root.resolve()
    approved = (ROOT / RAW_ROOT_REL).resolve()
    try:
        resolved.relative_to(approved)
    except ValueError as exc:
        raise ValueError("raw output must stay under data/a_long/raw/tushare/materialization_full_period_panel_20260604/") from exc
    if not path_is_gitignored_by_policy(raw_root):
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


def materialization_call_plan() -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = [
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
    ]

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
    for table_id in ["income", "balancesheet", "cashflow", "fina_indicator"]:
        for symbol in SYMBOLS:
            calls.append(
                {
                    "call_id": f"{table_id}_{symbol.replace('.', '_')}_2018_2025",
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
    )

    for symbol in SYMBOLS:
        suffix = symbol.replace(".", "_")
        calls.extend(
            [
                {
                    "call_id": f"daily_{suffix}_2018_2025",
                    "table_id": "daily_price_adj_factor_dividend",
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
                    "table_id": "daily_price_adj_factor_dividend",
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
                    "table_id": "daily_price_adj_factor_dividend",
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


class NetworkPacer:
    def __init__(self, min_seconds_between_network_calls: float) -> None:
        if min_seconds_between_network_calls < 0:
            raise ValueError("min_seconds_between_network_calls must be non-negative")
        self.min_seconds_between_network_calls = min_seconds_between_network_calls
        self._last_network_start: float | None = None

    def before_network_call(self) -> None:
        if self.min_seconds_between_network_calls <= 0:
            self._last_network_start = time.monotonic()
            return
        now = time.monotonic()
        if self._last_network_start is not None:
            remaining = self.min_seconds_between_network_calls - (now - self._last_network_start)
            if remaining > 0:
                time.sleep(remaining)
        self._last_network_start = time.monotonic()


def paced_refetch_raw_id(call_id: str) -> str:
    return f"{call_id}_{PACED_REFETCH_SUFFIX}"


def is_empty_daily_payload(call: dict[str, Any], payload: dict[str, Any]) -> bool:
    return (
        call.get("api_family") == "daily"
        and payload.get("call_status") == "empty"
        and payload.get("row_count") == 0
    )


def execute_network_call(
    pro: Any,
    call: dict[str, Any],
    raw_root: Path,
    *,
    checkpoint_status: str,
    pacer: NetworkPacer,
    raw_file_id: str | None = None,
) -> tuple[dict[str, Any], bool]:
    request_shape_without_token = dict(call["kwargs"])
    file_id = raw_file_id or call["call_id"]
    pacer.before_network_call()
    try:
        value = getattr(pro, call["method"])(**call["kwargs"])
        columns, row_count, records = thin_runner.normalize_records(value)
        status = "success" if row_count and row_count > 0 else "empty"
        raw_ref = thin_runner.write_raw_payload(
            raw_root,
            file_id,
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
        raw_ref = thin_runner.write_raw_payload(
            raw_root,
            file_id,
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
    return thin_runner.result_from_raw_payload(call, payload, raw_ref, checkpoint_status), True


def execute_call_with_pacing(
    pro: Any,
    call: dict[str, Any],
    raw_root: Path,
    *,
    pacer: NetworkPacer,
) -> tuple[dict[str, Any], bool]:
    existing = thin_runner.load_existing_raw_payload(raw_root, call["call_id"])
    if existing is not None:
        payload, raw_ref = existing
        if not is_empty_daily_payload(call, payload):
            return thin_runner.result_from_raw_payload(call, payload, raw_ref, "reused_existing_raw"), False

        refetch_id = paced_refetch_raw_id(call["call_id"])
        refetched = thin_runner.load_existing_raw_payload(raw_root, refetch_id)
        if refetched is not None:
            refetched_payload, refetched_raw_ref = refetched
            return (
                thin_runner.result_from_raw_payload(call, refetched_payload, refetched_raw_ref, "reused_paced_refetch_raw"),
                False,
            )
        return execute_network_call(
            pro,
            call,
            raw_root,
            checkpoint_status="written_paced_refetch_raw",
            pacer=pacer,
            raw_file_id=refetch_id,
        )

    return execute_network_call(
        pro,
        call,
        raw_root,
        checkpoint_status="written_new_raw",
        pacer=pacer,
    )


def table_rollup(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    expected_tables = [row["table_id"] for row in read_json(PACKET_PATH)["materialization_tables"]]
    for table_id in expected_tables:
        table_results = [item for item in results if item["table_id"] == table_id]
        missing = sorted({field for item in table_results for field in item.get("minimum_fields_missing", [])})
        success_count = sum(1 for item in table_results if item["call_status"] == "success")
        total = len(table_results)
        status = (
            "passed_full_period_panel_shape"
            if total > 0 and success_count == total and not missing
            else "partial_or_failed_full_period_panel_shape"
            if total > 0
            else "not_tested"
        )
        plain = (
            "Full-period panel materialization shape is present for this table."
            if status == "passed_full_period_panel_shape"
            else "Full-period panel materialization shape is incomplete for this table."
            if status == "partial_or_failed_full_period_panel_shape"
            else "This table was not tested."
        )
        out.append(
            {
                "table_id": table_id,
                "status": status,
                "calls_total": total,
                "calls_success": success_count,
                "missing_minimum_fields": missing,
                "plain_result": plain,
            }
        )
    return out


def build_summary(
    *,
    results: list[dict[str, Any]],
    generated_at: str,
    environment_precheck_passed: bool,
    independent_review_confirmed: bool,
    post_review_execute_confirmed: bool,
    new_network_call_count: int,
    reused_raw_payload_count: int,
    min_seconds_between_network_calls: float,
) -> dict[str, Any]:
    rollup = table_rollup(results)
    passed = all(item["status"] == "passed_full_period_panel_shape" for item in rollup)
    daily_empty_raw_refetch_count = sum(
        1
        for item in results
        if item.get("checkpoint_status") in {"written_paced_refetch_raw", "reused_paced_refetch_raw"}
    )
    if not environment_precheck_passed:
        status = "not_executed_environment_missing"
        plain_result = "没有跑数据：缺 Tushare 环境。"
        next_action = "补齐 TUSHARE_TOKEN 后，仍需 Claude 通过和用户再次执行，才能跑固定样本池。"
    elif passed:
        status = "passed_full_period_panel_materialization_shape"
        plain_result = "2018-2025 固定样本池数据已落地，但还不能用来找 alpha。"
        next_action = "下一步是另起 reviewed full-period panel data-integrity audit；audit 通过后仍需判断是否足够进入信号搜索预注册。"
    else:
        status = "partial_or_failed_full_period_panel_materialization"
        plain_result = "固定样本池数据落地不完整；A 股长线仍不能找 alpha。"
        next_action = "先修失败的数据表或字段；不要全市场放大、重跑 audit 或开始 signal search。"

    return {
        "schema_name": "a_long_tushare_broader_materialization_execution_summary",
        "schema_version": "1.0.0",
        "generated_at": generated_at,
        "artifact_id": "a_long_tushare_broader_materialization_execution_summary_20260604",
        "packet_ref": "docs/a_long_tushare_broader_materialization_packet_20260604.json",
        "scope": {
            "phase": "7a_alpha_validation",
            "purpose": "a_long_tushare_full_period_panel_materialization_execution",
            "lane_id": "a_long",
            "market": "A-share",
            "research_only": True,
            "provider_family": "tushare_existing_account",
            "provider_call_executed": new_network_call_count > 0,
            "tushare_call_executed": new_network_call_count > 0,
            "data_fetch_executed": new_network_call_count > 0,
            "raw_payload_written_to_gitignored_path": new_network_call_count > 0 or reused_raw_payload_count > 0,
            "tracked_summary_contains_raw_rows": False,
            "tracked_summary_contains_secret": False,
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
            "summary_path": "docs/a_long_tushare_broader_materialization_execution_summary_20260604.json",
            "raw_output_root": RAW_ROOT_REL.as_posix() + "/",
            "raw_output_root_is_gitignored": True,
            "max_total_endpoint_calls": MAX_TOTAL_ENDPOINT_CALLS,
            "planned_total_endpoint_calls": PLANNED_TOTAL_ENDPOINT_CALLS,
            "endpoint_results_count": len(results),
            "new_network_call_count": new_network_call_count,
            "reused_raw_payload_count": reused_raw_payload_count,
            "min_seconds_between_network_calls": min_seconds_between_network_calls,
            "daily_empty_raw_refetch_count": daily_empty_raw_refetch_count,
            "budget_exceeded": False,
            "network_call_attempted": new_network_call_count > 0,
            "environment_precheck_passed": environment_precheck_passed,
            "independent_review_confirmed": independent_review_confirmed,
            "post_review_execute_confirmed": post_review_execute_confirmed,
            "token_logged": False,
            "request_url_logged": False,
        },
        "broader_materialization_boundary": {
            "materialization_id": "a_long_tushare_full_period_panel_2018_2025",
            "start_date": START_DATE,
            "end_date": END_DATE,
            "active_symbols": list(ACTIVE_SYMBOLS),
            "delisted_symbols": list(DELISTED_SYMBOLS),
            "benchmark_indices": list(BENCHMARK_INDICES),
            "not_full_market": True,
            "not_full_universe": True,
        },
        "endpoint_results": results,
        "table_rollup": rollup,
        "decision": {
            "materialization_status": status,
            "data_can_be_used_for_alpha_now": False,
            "audit_rerun_authorized_by_this_summary": False,
            "signal_search_authorized_by_this_summary": False,
            "plain_result": plain_result,
            "next_action": next_action,
        },
        "prohibited_claims": {
            "a_long_data_ready": False,
            "a_long_alpha_found": False,
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
            "This summary records full-period panel materialization shape and raw refs only; raw rows stay under gitignored data/a_long/raw/.",
            "A pass does not make A-long data ready and does not authorize signal search.",
            "A separate reviewed data-integrity audit is required before any A-long signal-search preregistration.",
            "No full-market pull, full-universe materialization, DataHub, production, ship-gate, full-size use, or broker/order automation is authorized.",
        ],
    }


def execute_broader_materialization(
    *,
    packet_path: Path = PACKET_PATH,
    summary_path: Path = SUMMARY_PATH,
    raw_root: Path = RAW_ROOT,
    pro_factory: Callable[[], Any] = route_base.get_tushare_client,
    generated_at: str | None = None,
    dry_run_env: bool = False,
    confirm_independent_review_pass: bool = False,
    confirm_post_review_execute: bool = False,
    min_seconds_between_network_calls: float = 0.0,
) -> dict[str, Any]:
    load_and_validate_packet(packet_path)
    validate_thin_slice_audit_pass()
    validate_daily_route_diagnostic_supports_pacing()
    validate_raw_root(raw_root)
    require_live_execution_confirmations(
        dry_run_env=dry_run_env,
        confirm_independent_review_pass=confirm_independent_review_pass,
        confirm_post_review_execute=confirm_post_review_execute,
    )
    generated = generated_at or iso_now()
    calls = materialization_call_plan()
    if len(calls) > MAX_TOTAL_ENDPOINT_CALLS:
        raise ValueError("planned broader materialization calls exceed max budget")

    if dry_run_env:
        summary = build_summary(
            results=[],
            generated_at=generated,
            environment_precheck_passed=bool(os.environ.get("TUSHARE_TOKEN")),
            independent_review_confirmed=confirm_independent_review_pass,
            post_review_execute_confirmed=confirm_post_review_execute,
            new_network_call_count=0,
            reused_raw_payload_count=0,
            min_seconds_between_network_calls=min_seconds_between_network_calls,
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
            min_seconds_between_network_calls=min_seconds_between_network_calls,
        )
        write_json_atomic(summary, summary_path)
        return summary

    pro = pro_factory()
    pacer = NetworkPacer(min_seconds_between_network_calls)
    results: list[dict[str, Any]] = []
    new_network_call_count = 0
    reused_raw_payload_count = 0
    for call in calls:
        result, used_network = execute_call_with_pacing(pro, call, raw_root, pacer=pacer)
        results.append(result)
        if used_network:
            new_network_call_count += 1
        else:
            reused_raw_payload_count += 1
        if new_network_call_count + reused_raw_payload_count > MAX_TOTAL_ENDPOINT_CALLS:
            raise ValueError("broader materialization call budget exceeded")

    summary = build_summary(
        results=results,
        generated_at=generated,
        environment_precheck_passed=True,
        independent_review_confirmed=confirm_independent_review_pass,
        post_review_execute_confirmed=confirm_post_review_execute,
        new_network_call_count=new_network_call_count,
        reused_raw_payload_count=reused_raw_payload_count,
        min_seconds_between_network_calls=min_seconds_between_network_calls,
    )
    write_json_atomic(summary, summary_path)
    return summary


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    summary = execute_broader_materialization(
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
        json.dumps(
            {
                "materialization_status": decision["materialization_status"],
                "plain_result": decision["plain_result"],
                "next_action": decision["next_action"],
                "new_network_call_count": summary["execution"]["new_network_call_count"],
                "reused_raw_payload_count": summary["execution"]["reused_raw_payload_count"],
                "daily_empty_raw_refetch_count": summary["execution"]["daily_empty_raw_refetch_count"],
                "min_seconds_between_network_calls": summary["execution"]["min_seconds_between_network_calls"],
                "summary_path": summary["execution"]["summary_path"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
